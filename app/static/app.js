/* Inside the Game - the live broadcast in the browser, played like a football manager game.
 *
 * The server prepares the match a little ahead of what you see and streams (Server-Sent Events):
 *   - "segment": a few minutes of play, ready to be played: the match events, the commentary
 *                line and its voice, the crowd reactions and the live stats;
 *   - "item":    what the studio puts on air (analysis, stats panels, show plans, answers,
 *                recap), with the segment after which it may be shown (no spoilers).
 * The player below plays each segment on ONE clock: the action on the pitch, the voice, the
 * GOAL screen, the crowd and the stats move together, so "GOAL" is heard when it is seen.
 */
"use strict";

const $ = (sel) => document.querySelector(sel);
const state = {
  session: null, viewer: null, init: null, squads: null,
  players: {},            // player id -> {side, slot, name, number, x, y, tx, ty, onPitch}
  ball: { x: 60, y: 40, fx: 60, fy: 40, tx: 60, ty: 40, t0: 0, dur: 400 },
  period: 1, actor: null, shotLine: null, seenItems: new Set(), lastPlan: null,
  colors: { home: ["#1f4e9c", "#ffffff"], away: ["#2f7d4f", "#ffffff"] },
  sound: { voice: true, crowd: true },
  voiceFreeAt: 0,         // when the commentator has finished his current line
};

/* ======================================================= setup ===== */
async function api(path, body) {
  const res = await fetch(path, body === undefined ? {} : {
    method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify(body),
  });
  if (!res.ok) throw new Error((await res.json().catch(() => ({}))).detail || res.statusText);
  return res.json();
}

async function loadTeams() {
  const teams = await api("/api/teams");
  const opts = teams.map((t) => `<option value="${t.code}">${t.name}</option>`).join("");
  $("#home-team").innerHTML = opts;
  $("#away-team").innerHTML = opts;
  $("#home-team").value = "HAR";
  $("#away-team").value = "KES";
}

$("#match-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  const home = $("#home-team").value, away = $("#away-team").value;
  const status = $("#match-status");
  if (home === away) { status.textContent = "Pick two different clubs."; status.classList.add("error"); return; }
  status.classList.remove("error");
  status.textContent = "Simulating the match and briefing the agents… (about 10 seconds)";
  ev.submitter.disabled = true;
  try {
    const s = await api("/api/session", { home, away, seed: +$("#seed").value || 7, speed: +$("#speed").value });
    state.session = s.session;
    state.squads = s;
    $("#favourite").innerHTML = `<option value="">No club, I'm neutral</option>
      <option value="${s.home.team.name}">${s.home.team.name}</option>
      <option value="${s.away.team.name}">${s.away.team.name}</option>`;
    const group = (side) => `<optgroup label="${s[side].team.name}">` +
      s[side].players.map((p) => `<option value="${p.name}">${p.number}. ${p.name}</option>`).join("") + "</optgroup>";
    $("#follow").innerHTML = `<option value="">Nobody in particular</option>${group("home")}${group("away")}`;
    status.textContent = `Ready at ${s.venue}.`;
    $("#profile-form").hidden = false;
    $("#profile-form").scrollIntoView({ behavior: "smooth", block: "start" });
  } catch (e) {
    status.textContent = `Could not set up the match: ${e.message}`;
    status.classList.add("error");
  } finally { ev.submitter.disabled = false; }
});

$("#profile-form").addEventListener("submit", async (ev) => {
  ev.preventDefault();
  ev.submitter.disabled = true;
  const status = $("#profile-status");
  status.textContent = "Taking your seat…";
  state.sound.voice = $("#opt-voice").checked;
  state.sound.crowd = $("#opt-crowd").checked;
  audio.unlock();
  try {
    const init = await api("/api/join", {
      audience: document.querySelector('input[name="audience"]:checked').value,
      favourite_team: $("#favourite").value || null,
      followed_player: $("#follow").value || null,
      language: $("#language").value,
    });
    startBroadcast(init);
    if (init.status === "waiting") await api("/api/kickoff", {});
  } catch (e) {
    status.textContent = `Could not join: ${e.message}`;
    status.classList.add("error");
    ev.submitter.disabled = false;
  }
});

/* ===================================================== broadcast ===== */
function startBroadcast(init) {
  state.init = init;
  state.viewer = init.viewer_id;
  state.speed = init.speed;
  Object.assign(state.colors, chooseKits(init.home.team.colors, init.away.team.colors));
  document.documentElement.style.setProperty("--home", state.colors.home[0]);   // the kits worn today
  document.documentElement.style.setProperty("--away", state.colors.away[0]);
  $("#home-name").textContent = init.home.team.name;
  $("#away-name").textContent = init.away.team.name;
  for (const side of ["home", "away"]) {
    for (const p of init[side].players) addPlayer(side, p, p.slot);
    for (const p of init[side].bench) state.players[p.id] = { side, name: p.name, short: p.short || p.name,
                                                              number: p.number, onPitch: false };
  }
  setToggle("#toggle-voice", state.sound.voice && init.voice);
  setToggle("#toggle-crowd", state.sound.crowd);
  if (!init.voice) $("#toggle-voice").title = "No speech key configured on the server";
  buildSuggestions();
  $("#setup").hidden = true;
  $("#broadcast").hidden = false;
  $("#clock").textContent = "0'";
  $("#phase").textContent = "Pre-match";
  connectStream();
  requestAnimationFrame(draw);
  if (state.sound.crowd) audio.startMurmur();
  setInterval(refreshMetrics, 10000);
  player.prematch();
}

function connectStream() {
  const es = new EventSource(`/api/stream?viewer=${state.viewer}`);
  es.addEventListener("segment", (e) => player.add(JSON.parse(e.data)));
  es.addEventListener("item", (e) => player.item(JSON.parse(e.data)));
  es.addEventListener("metrics", () => refreshMetrics());
}

function setScore(score) {
  const h = $("#home-score"), a = $("#away-score");
  if (h.textContent !== String(score.home) || a.textContent !== String(score.away)) {
    h.textContent = score.home; a.textContent = score.away;
    $(".score").classList.remove("flash"); void $(".score").offsetWidth; $(".score").classList.add("flash");
  }
}

/* ========================================================= pitch ===== */
const W = 1240, H = 840, M = 20;                 // canvas size and margin
const sx = (x) => M + (x / 120) * (W - 2 * M);
const sy = (y) => M + (y / 80) * (H - 2 * M);

function addPlayer(side, p, slot) {
  const base = state.init.positions[slot] || [60, 40];
  state.players[p.id] = { side, slot, name: p.name, short: p.short || p.name, number: p.number,
                          onPitch: true, x: 60, y: 40, tx: 60, ty: 40, base, ...rhythm(p.number) };
}

function toAbsFor(side, loc) { return toAbs(side, loc[0], loc[1]); }   // abs <-> team frame (a mirror)
function rhythm(n) { return { phase: (n * 1.7) % 6.28, f: 0.75 + (n % 5) * 0.12 }; }

/* matchsim's "abs" frame: the home team attacks left to right in the first half. */
function toAbs(side, x, y) {
  const homeRight = state.period !== 2;
  const right = (side === "home") === homeRight;
  return right ? [x, y] : [120 - x, 80 - y];
}

function onPitch(ev, gap = 0.6) {
  state.period = ev.period || state.period;
  if (ev.minute) $("#clock").textContent = `${ev.minute}'`;
  if (ev.score) setScore(ev.score);
  if (ev.type === "period_start") $("#phase").textContent = ev.period === 2 ? "Second half" : "First half";
  const t = performance.now();
  const travel = Math.max(0.15, gap) * 1000;      // the ball arrives before the next action
  if (ev.loc) {
    const b = state.ball;
    const [ex, ey] = ev.end || ev.loc;
    const from = ev.end ? [b.x, b.y] : ev.loc;
    if (ev.end && Math.hypot(b.x - ev.loc[0], b.y - ev.loc[1]) > 6) { from[0] = ev.loc[0]; from[1] = ev.loc[1]; }
    const len = Math.hypot(ex - from[0], ey - from[1]);
    Object.assign(b, { fx: from[0], fy: from[1], tx: ex, ty: ey, t0: t,
                       dur: Math.min(travel * 0.85, Math.max(220, len * (ev.type === "shot" ? 9 : 22))) });
    if (["pass", "shot", "clearance"].includes(ev.type) && len > 4) state.trail = { from, to: [ex, ey], t0: t, dur: b.dur + 500 };
  }
  if (ev.player_id && state.players[ev.player_id] && ev.loc) {
    const follow = ev.type === "carry" || ev.type === "dribble";    // he runs with the ball
    state.actor = { id: ev.player_id, until: t + (follow ? travel + 200 : 900), x: ev.loc[0], y: ev.loc[1], follow };
  }
  if (ev.type === "pass" && ev.recipient_id && state.players[ev.recipient_id] && ev.end) {
    state.receiver = { id: ev.recipient_id, until: t + travel + 600, x: ev.end[0], y: ev.end[1] };
  }
  if (ev.type === "pass" && ev.outcome === "offside" && ev.end) showOffside(ev, t, travel + 2600);
  if (["pass", "carry", "dribble", "shot", "kick_off"].includes(ev.type) && ev.team_id) state.possession = sideOf(ev.team_id);
  if (ev.type === "pressure" && ev.player_id && state.players[ev.player_id] && ev.loc) {
    state.presser = { id: ev.player_id, until: t + 1500, x: ev.loc[0], y: ev.loc[1] };
  }
  if (ev.type === "shot") {
    state.shotLine = { from: ev.loc, to: ev.end || ev.loc, xg: ev.xg, until: t + 2500, side: sideOf(ev.team_id) };
    if (ev.shot_type !== "Penalty" && ev.shot_type !== "Free Kick") state.setPiece = null;
  }
  if (ev.type === "pass" && !["corner", "free_kick"].includes(ev.pass_type) && state.setPiece && t > state.setPiece.until - 400) state.setPiece = null;
  if (ev.type === "foul") {
    const on = ev.on_player ? ` on ${short(ev.on_player_id, ev.on_player)}` : "";
    showChip(ev.in_box ? "Penalty!" : `Foul by ${short(ev.player_id, ev.player)}${on}`, ev.in_box ? "penalty" : "", ev.in_box ? 3200 : 2200);
    if (ev.in_box) addEventLine(ev.minute, `<span class="ev-pen">P</span> Penalty to ${teamOf(ev.on_player_id)}: ${escapeHtml(ev.on_player || "")} brought down by ${escapeHtml(ev.player)}`);
  }
  if (ev.type === "card") {
    const red = ev.card === "red" || ev.card === "second_yellow";
    showChip(`${ev.minute}'  ${ev.player}`, red ? "card red" : "card yellow", 3200, red ? "Red card" : "Yellow card");
    addEventLine(ev.minute, `<span class="ev-card ${red ? "red" : "yellow"}"></span> ${escapeHtml(ev.player)} (${teamOf(ev.player_id)})${ev.card === "second_yellow" ? ", second yellow" : ""}`);
  }
  if (ev.type === "substitution") {
    showChip(`On: ${ev.player_on}   Off: ${ev.player_off}`, "sub", 2600, "Substitution");
    addEventLine(ev.minute, `<span class="ev-sub">⇄</span> ${escapeHtml(ev.player_on)} on, ${escapeHtml(ev.player_off)} off (${teamOf(ev.player_on_id)})`);
  }
  if (ev.type === "offside") showChip(`Offside: ${short(ev.player_id, ev.player)}`, "", 1800);
  if (ev.type === "goal") {
    const how = ev.shot_type === "Penalty" ? " (penalty)" : ev.shot_type === "Free Kick" ? " (free kick)" : ev.body_part && /head/i.test(ev.body_part) ? " (header)" : "";
    addEventLine(ev.minute, `<span class="ev-goal"></span> <b>${escapeHtml(ev.scorer || ev.player)}</b>${how} ${ev.score.home}–${ev.score.away}`, "goal-line");
  }
  if (ev.type === "substitution") {
    const off = state.players[ev.player_off_id];
    if (off) off.onPitch = false;
    const on = state.players[ev.player_on_id];
    if (on) Object.assign(on, { onPitch: true, slot: ev.slot, base: state.init.positions[ev.slot] || [60, 40],
                                x: off ? off.x : 60, y: off ? off.y : 40, ...rhythm(on.number) });
  }
  if (ev.type === "goal") state.celebration = { side: sideOf(ev.team_id), at: ev.end || ev.loc, scorer: ev.player_id };
  if (ev.type === "kick_off" || ev.type === "period_start") state.celebration = null;
  if (ev.type === "card" && (ev.card === "red" || ev.card === "second_yellow")) showMoment("Red card", ev.player, "card", 3000);
  $("#ticker").textContent = tickerText(ev);
}

// Kits, like on a real matchday: the home side wears its first colour (a white outline keeps a
// dark kit visible on the grass). The away side changes kit when its colour is too close to the
// grass or to the home kit: second colour first, then a neutral change kit.
const GRASS = "#1E6B45";
function rgb(hex) { return [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16)); }
function colourDistance(a, b) {          // "redmean" distance: close to how different colours look
  const [r1, g1, b1] = rgb(a), [r2, g2, b2] = rgb(b), rm = (r1 + r2) / 2;
  return Math.sqrt((2 + rm / 256) * (r1 - r2) ** 2 + 4 * (g1 - g2) ** 2 + (2 + (255 - rm) / 256) * (b1 - b2) ** 2);
}
function numberColour(hex) {
  const [r, g, b] = rgb(hex).map((c) => c / 255);
  return 0.2126 * r + 0.7152 * g + 0.0722 * b > 0.45 ? "#10241A" : "#FFFFFF";
}
function chooseKits(homeColours, awayColours) {
  const onGrass = (c) => colourDistance(c, GRASS) >= 110;
  const home = [...homeColours, "#F5F5F5"].find(onGrass);
  const away = [...awayColours, "#F5F5F5", "#111111", "#E4572E"]
    .find((c) => onGrass(c) && colourDistance(c, home) >= 200);
  return { home: [home, numberColour(home)], away: [away, numberColour(away)] };
}

function sideOf(teamId) { return teamId === state.init.home.team.id ? "home" : "away"; }

function tickerText(ev) {
  const who = ev.player ? `${ev.player}` : "";
  switch (ev.type) {
    case "pass": return ev.recipient ? `${ev.minute}'  ${who} to ${ev.recipient}` : `${ev.minute}'  ${who} passes`;
    case "shot": return `${ev.minute}'  Shot by ${who} (xG ${(+ev.xg).toFixed(2)}): ${ev.outcome}`;
    case "goal": return `${ev.minute}'  Goal: ${ev.scorer}`;
    case "dribble": return `${ev.minute}'  ${who} takes on his man`;
    case "foul": return `${ev.minute}'  Foul by ${who}`;
    case "card": return `${ev.minute}'  ${ev.card.replace("_", " ")} card: ${who}`;
    case "substitution": return `${ev.minute}'  ${ev.player_on} on for ${ev.player_off}`;
    case "tactical_change": return `${ev.minute}'  ${ev.description}`;
    case "period_end": return ev.period === 1 ? "Half-time" : "Full time";
    default: return $("#ticker").textContent;
  }
}

function short(id, name) { return (state.players[id] && state.players[id].short) || name || ""; }
function teamOf(id) {
  const p = state.players[id];
  return p ? state.init[p.side].team.name : "";
}

/* Offside, as in the Laws of the Game: when the ball is played, the receiver is in the
 * opponents' half and nearer to their goal line than the second-last opponent (the
 * goalkeeper being the last). The scene is set a moment before the pass: the defending
 * team's outfield players step up into one line, the second-last defender on it; the
 * receiver is beyond it, his team-mates stay level or behind. */
function showOffside(ev, t, ms) {
  const side = sideOf(ev.team_id), other = side === "home" ? "away" : "home";
  const [rx, ry] = toAbsFor(side, ev.end);                 // receiver, in the attackers' frame
  const lineX = Math.min(Math.max(61, rx - 2.2), 112);     // always in the opponents' half
  const receiverX = Math.max(rx, lineX + 1.8);
  let marker = null, best = Infinity;
  for (const [id, q] of Object.entries(state.players)) {
    if (!q.onPitch || q.side !== other || q.slot === "GK") continue;
    const [, qy] = toAbsFor(side, [q.x, q.y]);
    if (Math.abs(qy - ry) < best) { best = Math.abs(qy - ry); marker = id; }
  }
  state.offside = { side, lineX, x: toAbs(side, lineX, 40)[0], until: t + ms,
                    receiver: ev.recipient_id, receiverAt: toAbs(side, receiverX, ry), marker };
}
/* Where the offside scene puts a player (abs coordinates), or null to leave him be. */
function offsideSpot(id, p, tx, ty) {
  const o = state.offside;
  if (id === o.receiver) return o.receiverAt;
  const [fx, fy] = toAbsFor(o.side, [tx, ty]);             // attackers' frame
  if (p.side !== o.side) {
    if (p.slot === "GK") return fx > o.lineX + 4 ? null : toAbs(o.side, Math.max(o.lineX + 6, 114), fy);
    if (id === o.marker) return toAbs(o.side, o.lineX, fy);            // the second-last defender
    return fx > o.lineX - 0.6 ? toAbs(o.side, o.lineX - 0.6 - Math.abs(Math.sin(p.phase)) * 2.5, fy) : null;
  }
  return fx > o.lineX - 1.2 ? toAbs(o.side, o.lineX - 1.2 - Math.abs(Math.cos(p.phase)) * 3, fy) : null;
}

let chipTimer = null;
function showChip(text, kind, ms, title) {
  const el = $("#chip");
  el.className = `chip ${kind || ""}`;
  el.innerHTML = (title ? `<b>${escapeHtml(title)}</b>` : "") + `<span>${escapeHtml(text)}</span>`;
  el.hidden = false;
  clearTimeout(chipTimer);
  chipTimer = setTimeout(() => { el.hidden = true; }, ms);
}

function addEventLine(minute, html, cls = "") {
  const li = document.createElement("li");
  li.className = `event ${cls}`;
  li.innerHTML = `<span class="min">${minute}'</span><div class="body"><p>${html}</p></div>`;
  $("#feed").prepend(li);
  $("#feed-empty").hidden = true;
}

/* Set pieces: before a corner, a free kick near the box or a penalty, the players take up
 * their places (in the attacking team's frame, x = 120 is the goal they attack). */
const SP_ATTACK = [[108, 34], [110, 41], [106, 47], [103, 37], [101, 44], [93, 30], [93, 51]];
const SP_DEFEND = [[113, 36], [113, 44], [110, 31], [108, 40], [110, 49], [105, 35], [105, 46], [100, 40], [97, 30]];
function setPieceSpot(p, sp, id) {
  if (id === sp.taker) return sp.ball;
  const mates = Object.entries(state.players)
    .filter(([, q]) => q.onPitch && q.side === p.side && q.slot !== "GK")
    .sort((a, b) => b[1].base[0] - a[1].base[0]).map(([qid]) => qid).filter((qid) => qid !== sp.taker);
  const rank = mates.indexOf(id);
  if (sp.kind === "penalty") {              // everyone outside the box, the taker on the spot
    const y = 24 + (rank % 10) * 3.4;
    return toAbs(sp.side, p.side === sp.side ? 97 : 99, y + (p.side === sp.side ? 0 : 1.7));
  }
  const spots = p.side === sp.side ? SP_ATTACK : SP_DEFEND;
  if (rank < 0 || rank >= spots.length) return null;   // the others hold their shape
  return toAbs(sp.side, ...spots[rank]);
}

let momentTimer = null;
function showMoment(title, sub, kind, ms) {
  const el = $("#moment");
  el.className = `moment ${kind || ""}`;
  el.innerHTML = `<div><b>${title}</b><br><span>${escapeHtml(sub || "")}</span></div>`;
  el.hidden = false;
  clearTimeout(momentTimer);
  momentTimer = setTimeout(() => { el.hidden = true; }, ms);
}

function draw(now) {
  const c = $("#pitch").getContext("2d");
  drawPitch(c);
  // ball interpolation
  const b = state.ball;
  const k = Math.min(1, (now - b.t0) / b.dur);
  b.x = b.fx + (b.tx - b.fx) * k; b.y = b.fy + (b.ty - b.fy) * k;

  // players: each keeps his slot in a block that slides with the ball
  for (const [id, p] of Object.entries(state.players)) {
    if (!p.onPitch) continue;
    const [bxT, byT] = toAbs(p.side, b.x, b.y);           // ball in this team's attacking frame
    const gk = p.slot === "GK";
    const attacking = state.possession === p.side;
    let fx = p.base[0], fy = p.base[1];
    if (gk) { fx += (bxT - 60) * 0.06; fy += (byT - 40) * 0.12; }
    else {
      fx += (bxT - 60) * 0.45 + (attacking ? 7 : -5);    // the block follows the ball; push up with it
      if (attacking && bxT > 80 && p.base[0] > 70) { fx += 6; fy += (p.base[1] - 40) * 0.25; }   // runs into the box
      if (!attacking && bxT > 80) fx = Math.min(fx, 34);   // the back line drops to protect the goal
      fy += (byT - 40) * 0.22;
      if (!attacking) fy = fy * 0.8 + byT * 0.2;          // without the ball: squeeze towards it
      fx += Math.sin(now / 900 * p.f + p.phase) * 1.4;     // nobody stands still
      fy += Math.cos(now / 1100 * p.f + p.phase * 1.7) * 1.4;
    }
    let tx = Math.max(2, Math.min(118, fx)), ty = Math.max(3, Math.min(77, fy));
    [tx, ty] = toAbs(p.side, tx, ty);
    const sp = state.setPiece;
    if (sp && now < sp.until && !gk) { const spot = setPieceSpot(p, sp, id); if (spot) [tx, ty] = spot; }
    for (const special of [state.actor, state.receiver, state.presser]) {
      if (special && special.id === id && now < special.until) {
        if (special.follow) { tx = b.x; ty = b.y + 1.2; }       // the ball at his feet
        else { tx = special.x; ty = special.y; }
      }
    }
    if (state.offside && now < state.offside.until) { const spot = offsideSpot(id, p, tx, ty); if (spot) [tx, ty] = spot; }
    const cel = state.celebration;
    if (cel && cel.at) {                       // after a goal: the scorers run to celebrate
      if (p.side === cel.side && !gk) {
        const n = (p.number * 37) % 360 * Math.PI / 180;
        const cx = Math.max(4, Math.min(116, cel.at[0] + (cel.at[0] > 60 ? -9 : 9)));
        tx = cx + Math.cos(n) * (id === cel.scorer ? 0 : 3.5); ty = Math.max(6, Math.min(74, cel.at[1] + Math.sin(n) * 3.5));
      } else if (p.side !== cel.side) {
        [tx, ty] = toAbs(p.side, p.base[0], p.base[1]);
      }
    }
    const carrying = state.actor && state.actor.follow && state.actor.id === id && now < state.actor.until;
    const pace = carrying ? 0.25 : state.celebration ? 0.035 : sp && now < sp.until ? 0.05 : 0.08;
    p.x += (tx - p.x) * pace; p.y += (ty - p.y) * pace;
    const [fill, text] = state.colors[p.side];
    c.beginPath(); c.arc(sx(p.x), sy(p.y), 15, 0, Math.PI * 2);
    c.fillStyle = fill; c.fill();
    c.lineWidth = 2; c.strokeStyle = gk ? "#F4D35E" : "rgba(255,255,255,0.85)"; c.stroke();
    c.fillStyle = text; c.font = "700 15px Barlow Condensed, sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(p.number, sx(p.x), sy(p.y) + 1);
    if (state.actor && state.actor.id === id && now < state.actor.until) {
      c.fillStyle = "#F1F4EC"; c.font = "600 17px Barlow Condensed, sans-serif";
      c.fillText(p.short, sx(p.x), sy(p.y) - 26);
    }
  }
  // ball trail: where the pass or the shot came from
  const tr = state.trail;
  if (tr && now < tr.t0 + tr.dur) {
    const k2 = Math.min(1, (now - tr.t0) / Math.max(1, b.dur));
    const alpha = Math.max(0, 1 - (now - tr.t0) / tr.dur) * 0.55;
    c.strokeStyle = `rgba(241, 244, 236, ${alpha})`; c.lineWidth = 3; c.lineCap = "round";
    c.beginPath(); c.moveTo(sx(tr.from[0]), sy(tr.from[1]));
    c.lineTo(sx(tr.from[0] + (tr.to[0] - tr.from[0]) * k2), sy(tr.from[1] + (tr.to[1] - tr.from[1]) * k2)); c.stroke();
  }
  // offside line through the last defender
  const off = state.offside;
  if (off && now < off.until) {
    c.strokeStyle = "rgba(244, 211, 94, 0.95)"; c.lineWidth = 3; c.setLineDash([14, 10]);
    c.beginPath(); c.moveTo(sx(off.x), sy(0)); c.lineTo(sx(off.x), sy(80)); c.stroke(); c.setLineDash([]);
    c.fillStyle = "#F4D35E"; c.font = "700 20px Barlow Condensed, sans-serif"; c.textAlign = "center";
    c.fillText("OFFSIDE LINE", sx(off.x), sy(0) + 22);
    const r = state.players[off.receiver];
    if (r) { c.strokeStyle = "#E4572E"; c.lineWidth = 4; c.beginPath(); c.arc(sx(r.x), sy(r.y), 22, 0, Math.PI * 2); c.stroke(); }
  }
  // shot line and xG
  const s = state.shotLine;
  if (s && now < s.until) {
    c.strokeStyle = "rgba(244, 211, 94, 0.9)"; c.lineWidth = 3; c.setLineDash([10, 8]);
    c.beginPath(); c.moveTo(sx(s.from[0]), sy(s.from[1])); c.lineTo(sx(s.to[0]), sy(s.to[1])); c.stroke();
    c.setLineDash([]);
    if (s.xg != null) {
      c.fillStyle = "#F4D35E"; c.font = "700 22px Barlow Condensed, sans-serif";
      c.fillText(`xG ${(+s.xg).toFixed(2)}`, sx(s.from[0]), sy(s.from[1]) + 34);
    }
  }
  // ball
  c.beginPath(); c.arc(sx(b.x) + 2, sy(b.y) + 3, 8, 0, Math.PI * 2); c.fillStyle = "rgba(0,0,0,0.3)"; c.fill();
  c.beginPath(); c.arc(sx(b.x), sy(b.y), 8, 0, Math.PI * 2); c.fillStyle = "#fff"; c.fill();
  player.tick(now);
  requestAnimationFrame(draw);
}

function drawPitch(c) {
  for (let i = 0; i < 12; i++) {                         // mowing stripes
    c.fillStyle = i % 2 ? "#1E6B45" : "#22764C";
    c.fillRect((W / 12) * i, 0, W / 12 + 1, H);
  }
  c.strokeStyle = "rgba(241, 244, 236, 0.85)"; c.lineWidth = 3;
  const rect = (x, y, w, h) => c.strokeRect(sx(x), sy(y), sx(x + w) - sx(x), sy(y + h) - sy(y));
  rect(0, 0, 120, 80);
  c.beginPath(); c.moveTo(sx(60), sy(0)); c.lineTo(sx(60), sy(80)); c.stroke();
  c.beginPath(); c.arc(sx(60), sy(40), sx(10) - sx(0), 0, Math.PI * 2); c.stroke();
  rect(0, 18, 18, 44); rect(102, 18, 18, 44); rect(0, 30, 6, 20); rect(114, 30, 6, 20);
  c.lineWidth = 5; c.strokeStyle = "#F1F4EC";
  c.beginPath(); c.moveTo(sx(0), sy(36)); c.lineTo(sx(0), sy(44)); c.moveTo(sx(120), sy(36)); c.lineTo(sx(120), sy(44)); c.stroke();
  c.fillStyle = "rgba(241,244,236,0.85)";
  for (const [x, y] of [[60, 40], [12, 40], [108, 40]]) { c.beginPath(); c.arc(sx(x), sy(y), 4, 0, Math.PI * 2); c.fill(); }
}

/* ========================================================== feed ===== */
const AGENT_NAMES = { narrator: "Narrator", stats: "Stats agent", tactical: "Tactical analyst",
                      producer: "Producer", router: "Router", python: "Match data", crowd: "Crowd" };

function renderItem(item, fromHistory = false) {
  if (state.seenItems.has(item.id)) return;
  state.seenItems.add(item.id);
  pulseAgent(item.agent);
  const p = item.payload;
  if (item.kind === "crowd") { if (!fromHistory) audio.crowdCues(p.cues); return; }
  if (item.kind === "stats_panel") { renderStats(p); return; }
  if (item.kind === "show_plan") {
    renderPlan(p, item);
    for (const o of p.overlays || []) if (o.data) renderStats(o.data);
  }
  const li = document.createElement("li");
  li.className = `${item.kind}${item.degraded ? " degraded" : ""}${p.excitement >= 4 ? " big" : ""}`;
  let body = "";
  if (item.kind === "commentary") {
    body = `<p>${escapeHtml(p.text)}</p>`;
  } else if (item.kind === "analysis") {
    body = `<div class="who">Tactical analyst</div><p>${escapeHtml(p.text)}</p>`;
  } else if (item.kind === "answer") {
    const asked = p.asked_by === "producer" ? "The Producer asked" : "You asked";
    body = `<div class="who"><span class="badge">${AGENT_NAMES[item.agent] || item.agent}</span>${asked}</div>
            <div class="q">${escapeHtml(p.question)}</div><p>${escapeHtml(p.answer)}</p>`;
    if (p.asked_by !== "producer") setThinking(false);
  } else if (item.kind === "show_plan") {
    body = `<div class="who">Producer, for you</div><p>${escapeHtml(p.headline)}</p>
            ${p.alert ? `<p>${escapeHtml(p.alert)}</p>` : ""}`;
  } else if (item.kind === "recap") {
    body = `<div class="who">Match report</div><p>${escapeHtml(p.text)}</p>`;
    if (!fromHistory && state.sound.voice && state.init.voice) audio.playUrl(`/api/audio/${item.id}`);
  } else return;
  li.innerHTML = `<span class="min">${item.minute === "FT" ? "FT" : item.minute + "'"}</span><div class="body">${body}</div>`;
  $("#feed").prepend(li);
  $("#feed-empty").hidden = true;
}

function renderStats(panel) {
  if (!panel || !panel.rows) return;
  renderLiveStrip(panel);
  const rows = panel.rows.map((r) => {
    const h = +r.home, a = +r.away, total = h + a || 1;
    return `<tr><td class="v h">${r.home}</td><td class="label">${r.label}
      <div class="bars"><span class="bh" style="width:${(100 * h) / total}%"></span><span class="ba" style="width:${(100 * a) / total}%"></span></div>
      </td><td class="v a">${r.away}</td></tr>`;
  }).join("");
  $("#stats-panel").innerHTML = `<table><caption>${panel.home} ${panel.score.home}–${panel.score.away} ${panel.away}
    <small>Match stats at ${panel.minute}'</small></caption>${rows}</table>`;
}

function renderPlan(plan, item) {
  state.lastPlan = plan;
  const hl = (plan.highlights || []).map((h) => `<li><span class="min">${h.minute}'</span><div><b>${escapeHtml(h.title)}</b>
     <span>${escapeHtml(h.why_for_you)}</span></div></li>`).join("");
  $("#show-plan").innerHTML = `<h3>${escapeHtml(plan.headline)}</h3>
    ${plan.alert ? `<div class="alert">${escapeHtml(plan.alert)}</div>` : ""}
    ${hl ? `<ol>${hl}</ol>` : ""}
    <p class="plan-meta">Prepared by your Producer at ${item.minute}'${item.degraded ? " (backup plan: the Producer was unavailable)" : ""}.</p>`;
}

/* ===================================================== questions ===== */
function buildSuggestions() {
  const v = state.init.viewer;
  const ideas = ["Why is the score what it is?", "When did the match turn?", "What did I miss?"];
  if (v.followed_player) ideas.unshift(`How is ${v.followed_player} playing?`);
  $("#suggestions").innerHTML = ideas.map((q) => `<button type="button">${escapeHtml(q)}</button>`).join("");
  $("#suggestions").querySelectorAll("button").forEach((b) => b.addEventListener("click", () => ask(b.textContent)));
}

$("#ask-form").addEventListener("submit", (ev) => {
  ev.preventDefault();
  const q = $("#question").value.trim();
  if (q) ask(q);
});

async function ask(question) {
  $("#question").value = "";
  setThinking(true);
  selectTab("feed");
  try {
    const res = await api("/api/ask", { viewer: state.viewer, question });
    for (const item of res.items) renderItem(item);
  } catch (e) {
    const li = document.createElement("li");
    li.innerHTML = `<span class="min"></span><div class="body"><p>The studio could not answer: ${escapeHtml(e.message)}</p></div>`;
    $("#feed").prepend(li);
  } finally { setThinking(false); }
}

function setThinking(on) {
  for (const a of ["router", "stats", "tactical"]) document.querySelector(`[data-agent="${a}"]`).classList.toggle("thinking", on);
}

const pulseTimers = {};
function pulseAgent(agent) {
  const name = agent === "recap" ? "narrator" : agent;
  const el = document.querySelector(`[data-agent="${name}"]`);
  if (!el) return;
  el.classList.add("active");
  clearTimeout(pulseTimers[name]);
  pulseTimers[name] = setTimeout(() => el.classList.remove("active"), 2500);
}

async function refreshMetrics() {
  try {
    const m = await api("/api/metrics");
    const rows = m.agents.map((r) => `<tr><td>${AGENT_NAMES[r.agent] || r.agent}</td><td>${r.calls}</td><td>${r.ok}</td>
      <td>${r.failures + r.timeouts}</td><td>${r.fallbacks}</td><td>${r.avg_seconds ?? "–"}</td></tr>`).join("");
    $("#agents-metrics").innerHTML = `<p>Five Foundry agents run this broadcast. Every call goes through a supervisor with a time
      limit, a retry and a backup, so the show never stops. ${m.items_on_air} items on air, ${m.memory_notes} notes passed between agents.</p>
      <table><thead><tr><th>Agent</th><th>Calls</th><th>OK</th><th>Failed</th><th>Backups</th><th>Avg s</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  } catch (_) { /* metrics are optional */ }
}

/* ========================================================== tabs ===== */
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
function selectTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  for (const t of ["feed", "stats", "show", "agents"]) $(`#tab-${t}`).hidden = t !== name;
  if (name === "agents") refreshMetrics();
}

function setToggle(sel, on) { $(sel).setAttribute("aria-pressed", String(on)); }
$("#toggle-voice").addEventListener("click", () => {
  state.sound.voice = !state.sound.voice && state.init.voice; setToggle("#toggle-voice", state.sound.voice);
  if (!state.sound.voice) audio.stopVoice();
});
$("#toggle-crowd").addEventListener("click", () => {
  state.sound.crowd = !state.sound.crowd; setToggle("#toggle-crowd", state.sound.crowd);
  state.sound.crowd ? audio.startMurmur() : audio.stopMurmur();
});

/* ======================================================== player ===== */
/* Plays the ready segments one after the other, on one clock, like the match view of a
 * football manager game:
 *   - the action runs at match speed; a commentary line starts on the moment it is about
 *     (the shot, the card, the change), and the segment lasts at least as long as the line;
 *   - on a goal, the GOAL screen, the score, the roar and the commentator's "GOAL!" all start
 *     on the goal itself, then the players celebrate while the call goes on (no frozen picture);
 *   - the live stats refresh after every shot, goal and card;
 *   - half-time and full time open the studio. */
/* Match pace, like the match view of a football manager game: build-up play in midfield
 * runs quickly, the game slows right down when it gets dangerous (final third, crosses,
 * through balls, set pieces, shots, fouls, offsides), and stoppages are skipped over.
 * The speed chosen at set-up scales everything (Relaxed, Broadcast, Quick). */
const DANGER_TYPES = new Set(["shot", "goal", "foul", "card", "offside", "substitution"]);
const DANGER_PASSES = new Set(["cross", "through_ball", "corner", "free_kick"]);
function frameX(ev) {                    // x in the acting team's attacking frame
  if (!ev.loc || !ev.team_id) return 60;
  const right = (sideOf(ev.team_id) === "home") === (ev.period !== 2);
  return right ? ev.loc[0] : 120 - ev.loc[0];
}
function paceGap(prev, ev) {
  const scale = 1 / (state.speed || 1);
  if (ev.type === "pressure") return 0.06 * scale;
  if (prev.period !== ev.period) return 1.0 * scale;
  const d = Math.max(0, ev.ms - prev.ms);
  if (d > 20) return Math.min(2.5, 0.7 + (d - 20) / 40) * scale;          // a stoppage: skip it
  const danger = DANGER_TYPES.has(ev.type) || DANGER_PASSES.has(ev.pass_type) || ev.outcome === "offside" || frameX(ev) > 80;
  let g = Math.max(0.22, d / (danger ? 4.8 : 14));
  if (prev.outcome === "offside") g += 1.4;                               // time to see the offside line
  if (ev.outcome === "offside") g = Math.max(g, 1.1);                     // and to set the scene before it
  return g * scale;
}

const NOTABLE = new Set(["shot", "card", "substitution", "tactical_change", "injury", "offside", "period_end", "match_end"]);
const player = (() => {
  const buffer = [], held = [];
  let seg = null, playedSeq = -1, started = false, pausedUntil = 0, finished = false;

  function add(segment) {
    if (state.sound.voice && segment.audio) segment.voice = audio.loadVoice(`/api/audio/${segment.audio}`);
    buffer.push(segment);
    updateWaiting();
  }
  function item(it) {
    if (it.seq == null || it.seq <= playedSeq) renderItem(it); else held.push(it);
  }
  function release() {
    held.sort((a, b) => a.id - b.id);
    for (let i = 0; i < held.length;) {
      if (held[i].seq <= playedSeq) renderItem(held.splice(i, 1)[0]); else i++;
    }
  }
  const sleep = (ms) => new Promise((r) => setTimeout(r, ms));
  function updateWaiting() {
    const w = $("#prematch-status");
    if (w && !started) w.textContent = buffer.length >= 2 ? "Teams are out. Kick-off any second." :
      "The agents are preparing the broadcast…";
  }

  async function prematch() {
    const i = state.init, h = i.home, a = i.away;
    const list = (side) => side.players.map((p) => `<li><b>${p.number}</b> ${escapeHtml(p.name)}</li>`).join("");
    $("#prematch").innerHTML = `
      <div class="pm-venue">${escapeHtml(i.venue)}</div>
      <div class="pm-teams"><span>${escapeHtml(h.team.name)}</span><em>v</em><span>${escapeHtml(a.team.name)}</span></div>
      <div class="pm-meta">Referee ${escapeHtml(i.referee)} · ${escapeHtml(String(i.weather?.condition ?? i.weather ?? ""))} · ${Number(i.attendance).toLocaleString("en-GB")} fans</div>
      <div class="pm-lineups">
        <div><h4><i style="background:${state.colors.home[0]}"></i>${escapeHtml(h.formation)}</h4><ol>${list(h)}</ol></div>
        <div><h4><i style="background:${state.colors.away[0]}"></i>${escapeHtml(a.formation)}</h4><ol>${list(a)}</ol></div>
      </div>
      <p class="pm-intro">${escapeHtml(i.intro)}</p>
      <p id="prematch-status" class="pm-status" role="status"></p>`;
    $("#prematch").hidden = false;
    updateWaiting();
    const intro = i.intro_audio && state.sound.voice ? await audio.loadVoice(`/api/audio/intro-${state.viewer}`) : null;
    if (intro) audio.playVoice(intro.el);
    await sleep(Math.max(8000, (intro ? intro.duration : 0) * 1000 + 800));
    while (buffer.length < 2 && !finished) { updateWaiting(); await sleep(300); if (buffer.some((s) => s.full_time)) break; }
    $("#prematch").hidden = true;
    $("#phase").textContent = "First half";
    showMoment("Kick-off", `${h.team.name} v ${a.team.name}`, "quiet", 1600);
    started = true;
  }

  async function next() {
    if (seg || !started || !buffer.length || performance.now() < pausedUntil) return;
    seg = buffer.shift();
    const v = seg.voice ? await seg.voice : null;
    const S = v ? v.duration : 0;
    const evs = seg.events;
    const times = new Map();
    let clock = 0;
    evs.forEach((ev, i) => { if (i) clock += paceGap(evs[i - 1], ev); times.set(ev, clock); });
    const at = (ev) => times.get(ev) ?? clock;
    let D = clock;
    const goalEv = seg.goal_idx != null ? evs.find((e) => e.idx === seg.goal_idx) : null;
    let voiceAt, celebrate = 0;
    if (goalEv) {                       // "GOAL!" on the goal itself, then the celebration
      voiceAt = at(goalEv);
      celebrate = Math.max(S, 3.5) + 0.8;
      D = voiceAt + celebrate;
    } else {                            // the line starts on the moment it is about
      // the line starts on the moment it is about, once the previous line has finished;
      // play goes on under it (it may run into the next segment)
      const notable = [...evs].reverse().find((e) => NOTABLE.has(e.type));
      voiceAt = notable ? at(notable) + 0.4 : Math.max(0, D - S - 0.4);
      voiceAt = Math.max(voiceAt, (state.voiceFreeAt - performance.now()) / 1000 || 0);
      D = Math.max(D, voiceAt + 0.6, 1.2);
    }
    state.voiceFreeAt = performance.now() + (voiceAt + S + 0.3) * 1000;
    const tasks = evs.map((ev, i) => ({ t: at(ev), run: () => onPitch(ev, i + 1 < evs.length ? at(evs[i + 1]) - at(ev) : 0.6) }));
    // offside: the back line steps up a moment before the pass, so the scene reads clearly
    for (const ev of evs) {
      if (ev.type === "pass" && ev.outcome === "offside" && ev.end) {
        tasks.push({ t: Math.max(0, at(ev) - 1.0), run: () => showOffside(ev, performance.now(), 1300) });
      }
    }
    // set pieces: the players take up their places just before the kick
    for (const ev of evs) {
      const kind = ev.type === "pass" && ev.pass_type === "corner" ? "corner"
        : ev.type === "pass" && ev.pass_type === "free_kick" ? "free kick"
        : ev.type === "shot" && ev.shot_type === "Free Kick" ? "free kick"
        : ev.type === "shot" && ev.shot_type === "Penalty" ? "penalty" : null;
      if (!kind || !ev.loc) continue;
      const side = sideOf(ev.team_id), [axT] = toAbsFor(side, ev.loc);
      const lead = kind === "penalty" ? 2.5 : 1.6;
      tasks.push({ t: Math.max(0, at(ev) - lead), run: () => {
        const box = kind !== "free kick" || axT > 80;      // a free kick far out: no wall of bodies
        const now = performance.now();
        state.setPiece = box ? { kind: kind === "penalty" ? "penalty" : "box", side, taker: ev.player_id,
                                 ball: ev.loc, until: now + (lead + 1.2) * 1000 } : null;
        Object.assign(state.ball, { fx: ev.loc[0], fy: ev.loc[1], tx: ev.loc[0], ty: ev.loc[1], t0: now, dur: 1 });
        const team = state.init[side].team.name;
        showChip(kind === "penalty" ? `${short(ev.player_id, ev.player)} steps up` : `${team}: ${short(ev.player_id, ev.player)} to take`,
                 kind === "penalty" ? "penalty" : "", lead * 1000 + 600,
                 kind === "corner" ? "Corner" : kind === "penalty" ? "Penalty" : "Free kick");
      } });
    }
    for (const st of seg.stats || []) {
      const ev = evs.find((e) => e.idx >= st.idx) || evs[evs.length - 1];
      tasks.push({ t: ev ? at(ev) + 0.05 : D, run: () => renderStats(st.panel) });
    }
    tasks.push({ t: voiceAt, run: () => {
      if (goalEv) {
        const how = goalEv.shot_type === "Penalty" ? "  ·  penalty" : goalEv.shot_type === "Free Kick" ? "  ·  free kick" : "";
        showMoment("GOAL", `${goalEv.scorer || goalEv.player} ${goalEv.minute}'${how}`, "", celebrate * 1000);
      }
      if (v) audio.playVoice(v.el);
      if (seg.commentary) { renderItem(seg.commentary, true); pulseAgent("narrator"); }
      if (seg.crowd.length) audio.crowdCues(seg.crowd);
    } });
    if (goalEv && seg.crowd.some((c) => c.kind === "anticipation")) {
      tasks.push({ t: Math.max(0, voiceAt - 2.5), run: () => audio.crowdCues([{ kind: "anticipation", intensity: 0.6 }]) });
      seg.crowd = seg.crowd.filter((c) => c.kind !== "anticipation");
    }
    tasks.sort((a, b) => a.t - b.t);
    seg.run = { start: performance.now(), tasks, i: 0, D };
  }

  function tick(now) {
    if (!seg) { next(); return; }
    if (!seg.run) return;                 // still loading its voice
    const t = (now - seg.run.start) / 1000, r = seg.run;
    while (r.i < r.tasks.length && r.tasks[r.i].t <= t) r.tasks[r.i++].run();
    if (t >= r.D && r.i >= r.tasks.length) end();
  }

  function end() {
    const done = seg; seg = null;
    playedSeq = done.seq;
    const last = done.events[done.events.length - 1];
    api("/api/progress", { viewer: state.viewer, seq: done.seq, idx: last ? last.idx : 0 }).catch(() => {});
    release();
    if (done.half_time) {
      $("#phase").textContent = "Half-time";
      showMoment("Half-time", "The studio takes over", "quiet", 4000);
      selectTab("stats");
      pausedUntil = performance.now() + 12000;
      setTimeout(() => { if (buffer.length) { $("#phase").textContent = "Second half"; selectTab("feed"); } }, 12000);
    }
    if (done.full_time) {
      finished = true;
      $("#phase").textContent = "Full time";
      showMoment("Full time", `${$("#home-name").textContent} ${$("#home-score").textContent}–${$("#away-score").textContent} ${$("#away-name").textContent}`, "quiet", 6000);
    }
  }
  return { add, item, prematch, tick };
})();

function renderLiveStrip(panel) {
  const row = (label) => panel.rows.find((r) => r.label === label) || { home: 0, away: 0 };
  const pos = row("Possession %"), shots = row("Shots"), on = row("Shots on target"), xg = row("Expected goals (xG)");
  const yc = row("Yellow cards");
  $("#live-strip").innerHTML = `
    <div class="ls-pos"><span>${pos.home}%</span><div class="ls-bar"><i style="width:${pos.home}%"></i></div><span>${pos.away}%</span><small>Possession</small></div>
    <div class="ls-cell"><b>${shots.home}</b><small>Shots</small><b>${shots.away}</b></div>
    <div class="ls-cell"><b>${on.home}</b><small>On target</small><b>${on.away}</b></div>
    <div class="ls-cell"><b>${(+xg.home).toFixed(2)}</b><small>xG</small><b>${(+xg.away).toFixed(2)}</b></div>
    <div class="ls-cell"><b>${yc.home}</b><small>Yellows</small><b>${yc.away}</b></div>`;
}

/* ========================================================= audio ===== */
const audio = (() => {
  let ctx = null, master = null, murmurNode = null;
  const buffers = {}, voiceQueue = [];
  let speaking = false, current = null;

  function unlock() {
    if (ctx) return;
    ctx = new (window.AudioContext || window.webkitAudioContext)();
    master = ctx.createGain(); master.gain.value = 0.9; master.connect(ctx.destination);
  }
  async function buffer(name) {
    if (buffers[name]) return buffers[name];
    const res = await fetch(`/api/crowd/${name}`);
    if (!res.ok) return null;
    buffers[name] = await ctx.decodeAudioData(await res.arrayBuffer());
    return buffers[name];
  }
  async function play(name, gain) {
    if (!ctx || !state.sound.crowd) return;
    const b = await buffer(name); if (!b) return;
    const src = ctx.createBufferSource(); src.buffer = b;
    const g = ctx.createGain(); g.gain.value = gain;
    src.connect(g).connect(master); src.start();
    return src;
  }
  async function startMurmur() {
    if (!ctx || murmurNode) return;
    const b = await buffer("murmur"); if (!b) { setTimeout(startMurmur, 3000); return; }
    murmurNode = ctx.createBufferSource(); murmurNode.buffer = b; murmurNode.loop = true;
    const g = ctx.createGain(); g.gain.value = 0.35;
    murmurNode.connect(g).connect(master); murmurNode.start();
  }
  function stopMurmur() { if (murmurNode) { murmurNode.stop(); murmurNode = null; } }

  function crowdCues(cues) {
    let delay = 0;
    for (const c of cues || []) {
      const level = c.intensity >= 0.8 ? "high" : c.intensity >= 0.5 ? "mid" : "low";
      const variant = 1 + Math.floor(Math.random() * 2);
      let name;
      switch (c.kind) {
        case "roar": name = `roar_${level}_${variant}`; break;
        case "ooh": case "boo": name = `${c.kind}_${level === "low" ? "low" : "high"}_${variant}`; break;
        default: name = `${c.kind}_${variant}`;
      }
      setTimeout(() => play(name, 0.35 + 0.55 * c.intensity), delay);
      delay += c.kind === "celebration" ? 2500 : 900;
    }
  }

  function duck(on) {
    if (!master) return;
    master.gain.cancelScheduledValues(ctx.currentTime);
    master.gain.linearRampToValueAtTime(on ? 0.35 : 0.9, ctx.currentTime + 0.3);
  }
  // The commentator's voice. The player starts each line at the exact moment it belongs to;
  // the crowd ducks under the voice.
  let voiceEl = null;
  async function loadVoice(url) {         // fetch the line in advance and learn its length
    try {
      const res = await fetch(url);
      if (!res.ok) return null;
      const el = new Audio(URL.createObjectURL(await res.blob()));
      await new Promise((ok, fail) => {
        el.addEventListener("loadedmetadata", ok, { once: true });
        el.addEventListener("error", fail, { once: true });
        setTimeout(ok, 4000);
      });
      return { el, duration: isFinite(el.duration) ? el.duration : 0 };
    } catch (_) { return null; }
  }
  function playVoice(el) {
    if (!el || !state.sound.voice) return;
    if (voiceEl && voiceEl !== el) voiceEl.pause();
    voiceEl = el; duck(true);
    el.addEventListener("ended", () => { if (voiceEl === el) { voiceEl = null; duck(false); } }, { once: true });
    el.play().catch(() => duck(false));
  }
  async function playUrl(url) { const v = await loadVoice(url); if (v) playVoice(v.el); return v; }
  function stopVoice() { if (voiceEl) voiceEl.pause(); voiceEl = null; duck(false); }
  return { unlock, startMurmur, stopMurmur, crowdCues, loadVoice, playVoice, playUrl, stopVoice };
})();

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

loadTeams().catch((e) => { $("#match-status").textContent = `Could not load the clubs: ${e.message}`; });
