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
  scorers: { home: [], away: [] },
  subtitles: "English",   // the commentator's subtitles: English by default, or "off"
  captainIds: new Set(),
  approaches: new Map(),
  ratings: {}, topRated: null,   // live player ratings; the best one wears the golden ball  // player id -> where and when he must be on the ball (his next action)
};

/* ======================================================= setup ===== */
// Every call carries the id of this browser's match (several matches can run at once).
const withSession = (url) => state.session ? `${url}${url.includes("?") ? "&" : "?"}s=${state.session}` : url;
async function api(path, body) {
  const headers = state.session ? { "X-Session": state.session } : {};
  const res = await fetch(path, body === undefined ? { headers } : {
    method: "POST", headers: { ...headers, "Content-Type": "application/json" }, body: JSON.stringify(body),
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
    const seed = +$("#seed").value || null;                 // empty: the server draws a new match
    const s = await api("/api/session", { home, away, seed, speed: +$("#speed").value });
    state.session = s.session;
    state.squads = s;
    $("#favourite").innerHTML = `<option value="">No club, I'm neutral</option>
      <option value="${s.home.team.name}">${s.home.team.name}</option>
      <option value="${s.away.team.name}">${s.away.team.name}</option>`;
    const group = (side) => `<optgroup label="${s[side].team.name}">` +
      s[side].players.map((p) => `<option value="${p.name}">${p.number}. ${p.name}</option>`).join("") + "</optgroup>";
    $("#follow").innerHTML = `<option value="">Nobody in particular</option>${group("home")}${group("away")}`;
    status.textContent = `Ready at ${s.venue}. This is match number ${s.seed}: enter it again to replay this exact match.`;
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
  // what the server is playing, always visible: the full match, or highlights
  $("#mode").textContent = init.mode ? `${init.mode}${init.hidden_events ? "" : " · every action"}` : "";
  Object.assign(state.colors, chooseKits(init.home.team.colors, init.away.team.colors));
  state.captainIds = new Set(Object.values(init.captains || {}));
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
  state.subtitles = init.viewer.language || "English";
  $("#cc").value = state.subtitles;
  $("#setup").hidden = true;
  $("#broadcast").hidden = false;
  $("#clock").textContent = "0'";
  $("#phase").textContent = "Pre-match";
  connectStream();
  requestAnimationFrame(draw);
  if (state.sound.crowd) audio.startMurmur();
  setInterval(() => { if (!$("#tab-agents").hidden) refreshMetrics(); }, 10000);   // only when it is open
  player.prematch();
}

function connectStream() {
  const es = new EventSource(withSession(`/api/stream?viewer=${state.viewer}`));
  es.addEventListener("segment", (e) => player.add(JSON.parse(e.data)));
  es.addEventListener("item", (e) => player.item(JSON.parse(e.data)));
  es.addEventListener("metrics", () => { if (!$("#tab-agents").hidden) refreshMetrics(); });
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
  let travel = flightOf(ev) * 1000;                // real football speed: the ball takes its time
  // the ball never jumps: in open play each action starts where the ball really is (the end
  // of the previous action), and the players come to the ball, not the other way round.
  // Set pieces, throw-ins and the kick-off start from their spot; after a cut the ball is
  // already there; a shot keeps its real spot (its xG is for that spot) unless the ball is
  // a stride away from it.
  const bNow = state.ball, ballAt = [bNow.tx, bNow.ty];
  const fixedSpot = ev.cut || setPieceKind(ev) || ev.pass_type === "throw_in" || ev.type === "period_start";
  if (ev.loc && !fixedSpot && bNow.t0) {
    const off = Math.hypot(ballAt[0] - ev.loc[0], ballAt[1] - ev.loc[1]);
    const shooter = ev.type === "shot" && state.players[ev.player_id];
    const onBall = shooter && Math.hypot(shooter.x - ballAt[0], shooter.y - ballAt[1]) < 3;
    if (ev.type !== "shot" || off < 8 || onBall) ev = { ...ev, loc: ballAt };
  }
  // a pass goes to a player: if the receiver cannot get to the spot in time, the ball is
  // played to where he can get to
  if (ev.type === "pass" && ev.outcome === "complete" && ev.end && ev.recipient_id && state.players[ev.recipient_id]
      && !setPieceKind(ev)) {
    const r = state.players[ev.recipient_id];
    const reach = TOP_SPEED * travel / 1000 + 1.5, far = Math.hypot(ev.end[0] - r.x, ev.end[1] - r.y);
    if (far > reach) ev = { ...ev, end: [r.x + (ev.end[0] - r.x) * reach / far, r.y + (ev.end[1] - r.y) * reach / far] };
  }
  travel = flightOf(ev) * 1000;                    // from where the ball really is
  if (ev.loc) {
    const b = state.ball;
    const [ex, ey] = ev.end || ev.loc;
    // if the ball is still on its way, it finishes its path first; if it has to be brought
    // to a spot (a set piece, a shot from its real spot), it rolls there at passing speed
    const gapToLoc = ev.cut ? 0 : Math.hypot(b.x - ev.loc[0], b.y - ev.loc[1]);
    const from = [ev.loc[0], ev.loc[1]];
    const len = Math.hypot(ex - from[0], ey - from[1]);
    const lead = gapToLoc > 1.5 ? Math.min(1500, gapToLoc / BALL_SPEED.ground * 1000) : 0;
    if (ev.cut) { b.x = from[0]; b.y = from[1]; }
    Object.assign(b, { fx: from[0], fy: from[1], tx: ex, ty: ey, t0: t, dur: travel + lead,
                       via: lead ? from : null, viaDur: lead, vx0: b.x, vy0: b.y,
                       ease: ["pass", "clearance", "shot"].includes(ev.type) });
    if (["pass", "shot", "clearance"].includes(ev.type) && len > 4) state.trail = { from, to: [ex, ey], t0: t, dur: b.dur + 500 };
  }
  if (ev.player_id && state.players[ev.player_id] && ev.loc) {
    const follow = ev.type === "carry" || ev.type === "dribble";    // he runs with the ball
    state.actor = { id: ev.player_id, until: t + (follow ? travel + 200 : 900), x: ev.loc[0], y: ev.loc[1], follow };
  }
  if (ev.type === "pass" && ev.recipient_id && state.players[ev.recipient_id] && ev.end) {
    state.receiver = { id: ev.recipient_id, until: t + travel + 600, x: ev.end[0], y: ev.end[1], arrive: t + state.ball.dur };
  }
  // turnovers: who won the ball, where, in his team's colour
  const won = { interception: "Interception", ball_recovery: "Won it back", goalkeeper: ev.outcome === "save" ? "Saved" : "Claimed" };
  if (ev.type === "duel" && ev.outcome === "won") won.duel = "Tackle";
  if (won[ev.type] && ev.player_id && state.players[ev.player_id]) {
    state.turnover = { id: ev.player_id, label: won[ev.type], until: t + 1600 };
  }
  if (["goalkeeper", "block", "clearance", "interception"].includes(ev.type) && ev.team_id) {
    state.lastTouch = { type: ev.type, outcome: ev.outcome, side: sideOf(ev.team_id), name: short(ev.player_id, ev.player), at: t };
  }
  // who has the ball: the player on it, then the receiver once the pass arrives
  if (ev.player_id && state.players[ev.player_id] && ["pass", "carry", "dribble", "shot", "kick_off"].includes(ev.type)) {
    state.holder = { id: ev.player_id, from: t };
    if (ev.type === "pass" && ev.outcome === "complete" && ev.recipient_id && state.players[ev.recipient_id]) {
      state.nextHolder = { id: ev.recipient_id, from: t + state.ball.dur };
    } else state.nextHolder = null;
  } else if (["interception", "ball_recovery", "goalkeeper"].includes(ev.type) && state.players[ev.player_id]) {
    state.holder = { id: ev.player_id, from: t }; state.nextHolder = null;
  } else if (["shot", "goal", "foul", "offside", "period_end"].includes(ev.type)) { state.holder = null; state.nextHolder = null; }
  if (ev.type === "pass" && ev.outcome === "offside" && ev.end) showOffside(ev, t, travel + 2600);
  if (["pass", "carry", "dribble", "shot", "kick_off", "interception", "ball_recovery"].includes(ev.type) && ev.team_id) {
    const side = sideOf(ev.team_id);
    if (side !== state.possession) {
      state.possession = side;
      document.querySelectorAll(".team").forEach((el) => el.classList.toggle("has-ball", el.classList.contains(side)));
    }
  }
  if (ev.type === "kick_off" && state.kickoff) state.kickoff.until = t + 250;     // the ball is in play
  // the referee's whistle
  if (ev.type === "kick_off") audio.whistle("ref_kickoff");
  else if (ev.type === "foul" || ev.type === "offside") audio.whistle("ref_short");
  else if (ev.type === "period_end") audio.whistle(ev.ended === 1 ? "ref_half" : "ref_full");
  if (ev.type === "pressure" && ev.player_id && state.players[ev.player_id] && ev.loc) {
    state.presser = { id: ev.player_id, until: t + 1500, x: ev.loc[0], y: ev.loc[1] };
  }
  if (ev.type === "shot") {
    state.shotLine = { from: ev.loc, to: ev.end || ev.loc, xg: ev.xg, until: t + 2800, side: sideOf(ev.team_id),
                       shooter: short(ev.player_id, ev.player) };

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
    const sent = red && state.players[ev.player_id];
    if (sent) { sent.sentOffAt = t; setTimeout(() => { sent.onPitch = false; }, 4000); }
    showChip(`${ev.minute}'  ${ev.player}`, red ? "card red" : "card yellow", 3200, red ? "Red card" : "Yellow card");
    addEventLine(ev.minute, `<span class="ev-card ${red ? "red" : "yellow"}"></span> ${escapeHtml(ev.player)} (${teamOf(ev.player_id)})${ev.card === "second_yellow" ? ", second yellow" : ""}`);
  }
  if (ev.type === "substitution") {
    showChip(`On: ${ev.player_on}   Off: ${ev.player_off}`, "sub", 2600, "Substitution");
    addEventLine(ev.minute, `<span class="ev-sub">⇄</span> ${escapeHtml(ev.player_on)} on, ${escapeHtml(ev.player_off)} off (${teamOf(ev.player_on_id)})`);
  }
  if (ev.type === "offside") showChip(`Offside: ${short(ev.player_id, ev.player)}`, "", 1800);
  if (ev.type === "goal") {
    const side = sideOf(ev.team_id), who = short(ev.player_id, ev.scorer || ev.player);
    // one entry per scorer, all his minutes together: "Thibault 46', 59', 67'"
    const list = state.scorers[side], minute = `${ev.minute}'${ev.shot_type === "Penalty" ? " (pen)" : ""}`;
    const entry = list.find((x) => x.who === who);
    if (entry) entry.minutes.push(minute); else list.push({ who, minutes: [minute] });
    $(`#${side}-scorers`).textContent = list.map((x) => `${x.who} ${x.minutes.join(", ")}`).join("  ·  ");
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
function showOffside(ev, t, ms, lineFrom = t) {
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
  state.offside = { side, lineX, x: toAbs(side, lineX, 40)[0], until: t + ms, lineFrom,
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

/* Walking on and off: out of the tunnel (halfway line, top touchline) at the start of each
 * half, back down it at half-time and full time. */
const TUNNEL = [60, -3], WALK_MS = 4200;
function tunnelSpot(p) {
  const k = (p.number % 11) - 5;
  return [TUNNEL[0] + (p.side === "home" ? -2.2 : 2.2) + k * 0.25, TUNNEL[1] + Math.abs(k) * 0.15];
}
function rollBall(to, ms) {                         // the ball is taken to a spot (no jump)
  const b = state.ball;
  Object.assign(b, { fx: b.x, fy: b.y, tx: to[0], ty: to[1], t0: performance.now(), dur: ms, via: null });
}
function walkOn(kicking = "home") {
  for (const p of Object.values(state.players)) if (p.onPitch) [p.x, p.y] = tunnelSpot(p);
  Object.assign(state.ball, { fx: 60, fy: 40, tx: 60, ty: 40, x: 60, y: 40 });
  state.celebration = null; state.setPiece = null;
  state.walk = { mode: "on", until: performance.now() + WALK_MS };
  setKickoff(kicking, null, Infinity);              // they walk straight to their kick-off places
}

/* Kick-off, as in the Laws: every player in his own half, the kicking team's two forwards
 * at the centre spot, the other team outside the centre circle. Used at the start of each
 * half and after every goal. */
function setKickoff(side, taker, ms) {
  state.kickoff = { side, taker, until: performance.now() + ms };
  state.celebration = null;
}
function kickoffSpot(p, id) {
  const k = state.kickoff;
  if (p.slot === "GK") return toAbs(p.side, 4, 40);
  const mates = Object.entries(state.players).filter(([, q]) => q.onPitch && q.side === p.side && q.slot !== "GK")
    .sort((a, b) => b[1].base[0] - a[1].base[0]).map(([qid]) => qid);
  if (p.side === k.side) {
    const front = k.taker && mates.includes(k.taker) ? [k.taker, ...mates.filter((q) => q !== k.taker)] : mates;
    const r = front.indexOf(id);
    if (r === 0) return toAbs(p.side, 59.4, 40);               // on the ball
    if (r === 1) return toAbs(p.side, 58.2, 33.5);             // his partner, ready for the first pass
  }
  // the rest keep their shape, squeezed into their own half (and out of the circle for the other team)
  let x = 6 + (p.base[0] / 120) * 48;
  const y = p.base[1];
  if (p.side !== k.side && Math.hypot(x - 60, y - 40) < 11) x = 60 - Math.sqrt(Math.max(0, 121 - (y - 40) ** 2));
  return toAbs(p.side, Math.min(x, 58.5), y);
}
function walkOff() { state.walk = { mode: "off", until: Infinity }; state.celebration = null; }

/* Subtitles: the commentator's words in the viewer's language, sentence by sentence,
 * each shown for a share of the voice's length that matches its own length. */
function splitSentences(text) { return String(text || "").split(/(?<=[.!?])\s+/).filter(Boolean); }
let subtitleTimers = [], subtitleUntil = 0;
const subtitleBusy = () => performance.now() < subtitleUntil;
function showSubtitles(sentences, totalMs) {
  subtitleTimers.forEach(clearTimeout); subtitleTimers = [];
  const el = $("#subtitle");
  if (!sentences.length || state.subtitles === "off") { el.hidden = true; return; }
  const chars = sentences.reduce((n, x) => n + x.length, 0) || 1;
  let at = 0;
  for (const line of sentences) {
    subtitleTimers.push(setTimeout(() => { el.textContent = line; el.hidden = false; }, at));
    at += Math.max(1600, (totalMs * line.length) / chars);
  }
  subtitleTimers.push(setTimeout(() => { el.hidden = true; }, at + 400));
  subtitleUntil = performance.now() + at;
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
  if (sp.kind === "freekick" && p.side !== sp.side) {   // the wall, 10 yards (9.15 m) from the ball
    const [bx, by] = toAbsFor(sp.side, sp.ball);
    const dx = 120 - bx, dy = 40 - by, len = Math.hypot(dx, dy) || 1;
    const ux = dx / len, uy = dy / len;
    const n = len < 28 ? 4 : 3;
    const wx = bx + ux * 10, wy = by + uy * 10;
    if (rank >= 0 && rank < n) {                         // shoulder to shoulder, across the line to goal
      const off = (rank - (n - 1) / 2) * 1.7;
      return toAbs(sp.side, wx - uy * off, wy + ux * off);
    }
    // the others mark in the box, away from the wall
    const free = SP_DEFEND.filter(([x, y]) => Math.hypot(x - wx, y - wy) > 5);
    const spot = free[rank - n];
    return rank >= n && spot ? toAbs(sp.side, ...spot) : null;
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

let lastFrame = 0, frameDt = 1 / 60;
function draw(now) {
  frameDt = lastFrame ? Math.min(0.1, (now - lastFrame) / 1000) : 1 / 60;   // seconds since the last frame
  lastFrame = now;
  const c = $("#pitch").getContext("2d");
  drawPitch(c);
  // ball interpolation
  const b = state.ball;
  if (b.via && now < b.t0 + b.viaDur) {                    // first leg: to where the action starts
    const k1 = (now - b.t0) / b.viaDur;
    b.x = b.vx0 + (b.via[0] - b.vx0) * k1; b.y = b.vy0 + (b.via[1] - b.vy0) * k1;
  } else {
    const start = b.via ? b.t0 + b.viaDur : b.t0, dur = b.via ? Math.max(1, b.dur - b.viaDur) : b.dur;
    let k = Math.min(1, (now - start) / dur);
    if (b.ease) k = 1 - Math.pow(1 - k, 1.6);              // a kicked ball slows down as it rolls
    b.x = b.fx + (b.tx - b.fx) * k; b.y = b.fy + (b.ty - b.fy) * k;
  }

  // the two outfield players nearest to the ball, in the team without it, go to press
  {
    const def = state.possession === "home" ? "away" : "home";
    state.pressers = Object.entries(state.players)
      .filter(([, q]) => q.onPitch && q.side === def && q.slot !== "GK")
      .map(([id, q]) => [id, Math.hypot(q.x - b.x, q.y - b.y)]).sort((a, b) => a[1] - b[1]).slice(0, 2).map(([id]) => id);
  }
  // the team shape follows the ball with a delay (a block shifts, it does not jerk)
  const lag = state.ballLag || (state.ballLag = { x: b.x, y: b.y });
  const kLag = Math.min(1, frameDt * 1.1);
  lag.x += (b.x - lag.x) * kLag; lag.y += (b.y - lag.y) * kLag;
  const snapping = state.snapUntil && now < state.snapUntil;
  // players: each keeps his slot in a block that slides with the ball
  for (const [id, p] of Object.entries(state.players)) {
    if (!p.onPitch) continue;
    const [bxT, byT] = toAbs(p.side, lag.x, lag.y);       // ball in this team's attacking frame
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
      if (!attacking && state.pressers && state.pressers.includes(id)) {   // the two nearest close him down
        const [lx, ly] = toAbs(p.side, b.x, b.y);
        fx = fx * 0.35 + (lx - 3) * 0.65; fy = fy * 0.35 + ly * 0.65;
      }
      fx += Math.sin(now / 900 * p.f + p.phase) * 1.4;     // nobody stands still
      fy += Math.cos(now / 1100 * p.f + p.phase * 1.7) * 1.4;
    }
    let tx = Math.max(2, Math.min(118, fx)), ty = Math.max(3, Math.min(77, fy));
    [tx, ty] = toAbs(p.side, tx, ty);
    for (const special of [state.actor, state.receiver, state.presser]) {
      if (special && special.id === id && now < special.until) {
        if (special.follow) { tx = b.x; ty = b.y + 1.2; }       // the ball at his feet
        else { tx = special.x; ty = special.y; }
      }
    }
    const sp = state.setPiece;                                  // a set piece comes first: everyone to his place
    if (sp && now < sp.until && !gk) { const spot = setPieceSpot(p, sp, id); if (spot) [tx, ty] = spot; }
    if (state.offside && now < state.offside.until) { const spot = offsideSpot(id, p, tx, ty); if (spot) [tx, ty] = spot; }
    // last word: the player about to play the ball goes to it (a shot, a pass, a header after a cross)
    { const a = state.approaches.get(id); if (a && now < a.until) [tx, ty] = [a.x, a.y]; }
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
    const walk = state.walk && now < state.walk.until ? state.walk.mode : null;
    if (state.kickoff && now < state.kickoff.until && walk !== "off") [tx, ty] = kickoffSpot(p, id);
    if (walk === "off" || p.sentOffAt) [tx, ty] = tunnelSpot(p);     // down the tunnel (or sent off)
    const carrying = state.actor && state.actor.follow && state.actor.id === id && now < state.actor.until;
    const receiving = state.receiver && state.receiver.id === id && now < state.receiver.until;
    const offsideScene = state.offside && now < state.offside.until;
    const ap = state.approaches.get(id);
    const approaching = ap && now < ap.until;
    const pressing = state.pressers && state.pressers.includes(id);
    const settingUp = (sp && now < sp.until) || offsideScene || (state.kickoff && now < state.kickoff.until && !walk);
    // nobody runs faster than a footballer: about 8.5 m/s for the player going for the ball,
    // less for the others keeping the team's shape. Stoppages are shortened on screen, so
    // getting into place for a set piece or walking out goes a little quicker.
    const cap = snapping ? Infinity : walk ? 22 : p.sentOffAt ? 3 : state.celebration ? 6
      : settingUp ? (state.kickoff && now < state.kickoff.until ? 14 : 11) : carrying || receiving || approaching || pressing ? TOP_SPEED : 6.5;
    const dist = Math.hypot(tx - p.x, ty - p.y);
    // he slows down as he gets to his spot (no jitter), and never goes over his top speed
    const v = snapping ? dist / frameDt : Math.min(cap, dist * (walk ? 1.2 : 2.4));
    const k = dist > 0.01 ? Math.min(1, (v * frameDt) / dist) : 0;
    const mx = (tx - p.x) * k, my = (ty - p.y) * k;
    p.x += mx; p.y += my;
    const [fill, text] = state.colors[p.side];
    c.beginPath(); c.arc(sx(p.x), sy(p.y), 15, 0, Math.PI * 2);
    c.fillStyle = fill; c.fill();
    c.lineWidth = 2; c.strokeStyle = gk ? "#F4D35E" : "rgba(255,255,255,0.85)"; c.stroke();
    c.fillStyle = text; c.font = "700 15px Barlow Condensed, sans-serif"; c.textAlign = "center"; c.textBaseline = "middle";
    c.fillText(p.number, sx(p.x), sy(p.y) + 1);
    const h = state.nextHolder && now >= state.nextHolder.from ? state.nextHolder : state.holder;
    if (h && h.id === id && now >= h.from) {                     // the player on the ball
      c.strokeStyle = "#F4D35E"; c.lineWidth = 3;
      c.beginPath(); c.arc(sx(p.x), sy(p.y), 21, 0, Math.PI * 2); c.stroke();
    }
    if (state.topRated === id) {                                  // golden ball: best rating so far
      const gx = sx(p.x) - 13, gy = sy(p.y) - 13;
      c.fillStyle = "#F4C430"; c.beginPath(); c.arc(gx, gy, 7, 0, Math.PI * 2); c.fill();
      c.strokeStyle = "#8A6A00"; c.lineWidth = 1.5; c.stroke();
      c.beginPath(); c.moveTo(gx - 4, gy - 2); c.lineTo(gx + 4, gy + 2); c.moveTo(gx - 1, gy - 5); c.lineTo(gx + 1, gy + 5); c.stroke();
    }
    const to = state.turnover;
    if (to && to.id === id && now < to.until) {                  // he has just won the ball
      const [kitFill] = state.colors[p.side];
      c.strokeStyle = kitFill === "#F5F5F5" || kitFill === "#ffffff" ? "#F1F4EC" : kitFill; c.lineWidth = 4;
      c.beginPath(); c.arc(sx(p.x), sy(p.y), 24 + 4 * Math.sin(now / 90), 0, Math.PI * 2); c.stroke();
      c.font = "700 16px Barlow Condensed, sans-serif";
      const w = c.measureText(to.label).width + 12;
      c.fillStyle = "rgba(13, 42, 30, 0.9)"; c.fillRect(sx(p.x) - w / 2, sy(p.y) + 22, w, 20);
      c.fillStyle = "#F1F4EC"; c.fillText(to.label, sx(p.x), sy(p.y) + 33);
    }
    if (state.captainIds.has(id)) {                               // the captain's armband
      c.fillStyle = "#F4D35E"; c.beginPath(); c.arc(sx(p.x) + 12, sy(p.y) - 12, 7, 0, Math.PI * 2); c.fill();
      c.fillStyle = "#10241A"; c.font = "700 10px Barlow, sans-serif"; c.fillText("C", sx(p.x) + 12, sy(p.y) - 11.5);
    }
    if (state.actor && state.actor.id === id && now < state.actor.until) {        // on the ball
      c.fillStyle = "#F1F4EC"; c.font = "600 18px Barlow Condensed, sans-serif";
      c.fillText(p.short, sx(p.x), sy(p.y) - 26);
    }
    const shotAp = state.approaches.get(id);
    if (shotAp?.shot && now < shotAp.until && now > shotAp.arrive - 2000) {         // the shooter, before the strike
      c.strokeStyle = "#E4572E"; c.lineWidth = 3;                                  // about to shoot
      c.beginPath(); c.arc(sx(p.x), sy(p.y), 21, 0, Math.PI * 2); c.stroke();
      c.fillStyle = "#F1F4EC"; c.font = "700 19px Barlow Condensed, sans-serif";
      c.fillText(p.short, sx(p.x), sy(p.y) - 27);
    }
    if (state.receiver && state.receiver.id === id && now < state.receiver.until) {  // the pass is for him
      c.fillStyle = "#F4D35E"; c.font = "700 18px Barlow Condensed, sans-serif";
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
  if (off && now < off.until && now >= off.lineFrom) {       // drawn when the pass is played, not before
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
      c.fillText(`${s.shooter ? s.shooter + "  ·  " : ""}xG ${(+s.xg).toFixed(2)}`, sx(s.from[0]), sy(s.from[1]) + 36);
    }
  }
  // ball (not while the teams walk on or off)
  if (state.walk && performance.now() < state.walk.until) { player.tick(now); requestAnimationFrame(draw); return; }
  c.beginPath(); c.arc(sx(b.x) + 2, sy(b.y) + 3, 8, 0, Math.PI * 2); c.fillStyle = "rgba(0,0,0,0.3)"; c.fill();
  c.beginPath(); c.arc(sx(b.x), sy(b.y), 8, 0, Math.PI * 2); c.fillStyle = "#fff"; c.fill();
  const cut = state.cut;                                   // a cut to the next move: the picture dips
  if (cut && now < cut.end) {
    const k = now < cut.mid ? (now - cut.t0) / (cut.mid - cut.t0) : 1 - (now - cut.mid) / (cut.end - cut.mid);
    c.fillStyle = `rgba(10, 28, 20, ${Math.max(0, Math.min(1, k)) * 0.92})`;
    c.fillRect(0, 0, c.canvas.width, c.canvas.height);
  }
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
  // corner arcs (1 m) and the penalty arcs at the edge of each box
  c.strokeStyle = "rgba(241, 244, 236, 0.85)"; c.lineWidth = 3;
  const r1 = sx(1.2) - sx(0);
  for (const [x, y, a0] of [[0, 0, 0], [120, 0, Math.PI / 2], [120, 80, Math.PI], [0, 80, 1.5 * Math.PI]]) {
    c.beginPath(); c.arc(sx(x), sy(y), r1, a0, a0 + Math.PI / 2); c.stroke();
  }
  const r10 = sx(10) - sx(0), half = Math.acos(6 / 10);
  c.beginPath(); c.arc(sx(12), sy(40), r10, -half, half); c.stroke();
  c.beginPath(); c.arc(sx(108), sy(40), r10, Math.PI - half, Math.PI + half); c.stroke();
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
    body = `<p>${escapeHtml(p.text)}</p>`;                 // Live is always in English (subtitles carry the translation)
  } else if (item.kind === "analysis") {
    body = `<div class="who">Tactical analyst</div><p>${escapeHtml(p.text)}</p>`;
  } else if (item.kind === "answer") {           // answers live in their own places, not in Live
    renderAnswer(item); return;
  } else if (item.kind === "show_plan") {
    body = `<div class="who">Producer, for you</div><p>${escapeHtml(p.headline)}</p>
            ${p.alert ? `<p>${escapeHtml(p.alert)}</p>` : ""}`;
  } else if (item.kind === "recap") {
    body = `<div class="who">Match report</div><p>${escapeHtml(p.text)}</p>`;
    showSubtitles(splitSentences(p.subtitle || p.text).slice(0, 1), 6000);
    if (!fromHistory && state.sound.voice && state.init.voice) audio.playUrl(withSession(`/api/audio/${item.id}`));
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

/* Ask the studio: a conversation of its own, the question then the specialists' answers. */
async function ask(question) {
  $("#question").value = "";
  selectTab("ask");
  $("#qa-empty").hidden = true;
  const li = document.createElement("li");
  li.className = "qa-item";
  li.innerHTML = `<div class="qa-q"><span>${$("#clock").textContent}</span>${escapeHtml(question)}</div>
                  <div class="qa-a pending">The Router is picking the right agent…</div>`;
  $("#qa").append(li);
  li.scrollIntoView({ block: "end", behavior: "smooth" });
  setThinking(true);
  try {
    const res = await api("/api/ask", { viewer: state.viewer, question });
    li.querySelector(".qa-a").remove();
    for (const item of res.items) li.append(answerBlock(item));
    if (!res.items.length) li.insertAdjacentHTML("beforeend", `<div class="qa-a">The studio has no answer to that one.</div>`);
  } catch (e) {
    li.querySelector(".qa-a").outerHTML = `<div class="qa-a error">The studio could not answer: ${escapeHtml(e.message)}</div>`;
  } finally { setThinking(false); }
}

function answerBlock(item) {
  const div = document.createElement("div");
  div.className = `qa-a${item.degraded ? " degraded" : ""}`;
  div.innerHTML = `<span class="badge">${AGENT_NAMES[item.agent] || item.agent}</span><p>${escapeHtml(item.payload.answer)}</p>`;
  return div;
}

/* An answer to a question the Producer handed over goes under the viewer's show. */
function renderAnswer(item) {
  if (item.payload.asked_by !== "producer") return;          // the viewer's own: shown by ask()
  const box = document.createElement("div");
  box.className = "show-answer";
  box.innerHTML = `<div class="who"><span class="badge">${AGENT_NAMES[item.agent] || item.agent}</span>The Producer asked, at ${item.minute}'</div>
    <div class="q">${escapeHtml(item.payload.question)}</div><p>${escapeHtml(item.payload.answer)}</p>`;
  $("#show-answers").append(box);
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
    const rw = m.rewrites || {};
    const rows = m.agents.map((r) => `<tr><td>${AGENT_NAMES[r.agent] || r.agent}</td><td>${r.calls}</td><td>${r.ok}</td>
      <td>${r.failures + r.timeouts}</td><td>${r.fallbacks}</td><td>${rw[r.agent] ?? "–"}</td><td>${r.avg_seconds ?? "–"}</td></tr>`).join("");
    $("#agents-metrics").innerHTML = `<p>Five Foundry agents run this broadcast. Every call goes through a supervisor with a time
      limit, a retry and a backup, so the show never stops. Python checks every answer before it goes on air (scores,
      numbers, no guessing) and sends it back to the agent when a rule is broken. ${m.items_on_air} items on air,
      ${m.memory_notes} notes passed between agents.</p>
      <table><thead><tr><th>Agent</th><th>Calls</th><th>OK</th><th>Failed</th><th>Backups</th><th>Rewrites</th><th>Avg s</th></tr></thead>
      <tbody>${rows}</tbody></table>`;
  } catch (_) { /* metrics are optional */ }
}

/* ========================================================== tabs ===== */
document.querySelectorAll(".tabs button").forEach((b) => b.addEventListener("click", () => selectTab(b.dataset.tab)));
function selectTab(name) {
  document.querySelectorAll(".tabs button").forEach((b) => b.setAttribute("aria-selected", String(b.dataset.tab === name)));
  for (const t of ["feed", "stats", "show", "ask", "agents"]) $(`#tab-${t}`).hidden = t !== name;
  if (name === "agents") refreshMetrics();
}

/* Subtitles language, switchable during the match: the Narrator writes the new language from
 * the next lines it prepares (the one or two already prepared stay in the old one). */
$("#cc").addEventListener("change", async () => {
  const lang = $("#cc").value;
  state.subtitles = lang;
  if (lang === "off") { $("#subtitle").hidden = true; return; }
  try { await api("/api/subtitles", { viewer: state.viewer, language: lang }); } catch (_) { /* keep the old one */ }
});

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
/* Match pace, like the match view of a football manager game: the ball and the players move
 * at real football speed (a 30 m pass takes about two seconds, nobody runs faster than about
 * 8.5 m/s), and time is saved by choosing what to show, not by playing it faster. The server
 * picks the moves (app/highlights.py, same timing as here); between two moves the picture cuts. */
/* Set pieces: how long the players take to get into place before the kick (seconds on
 * screen). The stoppage before the kick lasts at least that long, at every speed. */
function setPieceKind(ev) {
  if (ev.type === "pass" && ev.pass_type === "corner") return "corner";
  if ((ev.type === "pass" && ev.pass_type === "free_kick") || (ev.type === "shot" && ev.shot_type === "Free Kick")) return "free kick";
  if (ev.type === "shot" && ev.shot_type === "Penalty") return "penalty";
  if (ev.type === "kick_off") return "kickoff";
  return null;
}
// a kick-off after a goal: the scorers jog back from the other end, so it takes longest
const SET_PIECE_LEAD = { corner: 3.8, "free kick": 3.8, penalty: 3.8, kickoff: 6.0 };

// ball speeds on screen, metres per second, averaged over the flight (app/highlights.py)
const BALL_SPEED = { ground: 15, high: 18, cross: 19, shot: 26, clearance: 20 };
const CARRY_SPEED = 5.0, CONTROL = 0.3, CUT = 0.9, TOP_SPEED = 8.5;
function flightOf(ev) {                   // seconds the ball (or the carrier) needs for this action
  const len = ev.loc && ev.end ? Math.hypot(ev.end[0] - ev.loc[0], ev.end[1] - ev.loc[1]) : 0;
  if (ev.type === "pass") {
    const kind = ev.cross || ev.pass_type === "cross" ? "cross" : ev.high ? "high" : "ground";
    return Math.max(0.35, len / BALL_SPEED[kind]);
  }
  if (ev.type === "shot") return Math.max(0.3, len / BALL_SPEED.shot);
  if (ev.type === "clearance") return Math.max(0.4, len / BALL_SPEED.clearance);
  if (ev.type === "carry") return Math.max(0.6, len / CARRY_SPEED);
  if (ev.type === "dribble") return 0.9;
  return 0.2;
}
// seconds on screen between two shown events (prev: the last event that is not a pressure)
function paceGap(prev, ev) {
  if (ev.type === "pressure") return 0.05;
  if (prev.period !== ev.period) return 1.0;
  const d = Math.max(0, ev.ms - prev.ms);
  let g;
  if (ev.cut) g = CUT;                                                      // a cut to the next move
  else if (d > 20) g = Math.min(2.2, 0.8 + (d - 20) / 50);                  // a stoppage: skip most of it
  else g = Math.max(0.45, flightOf(prev) + CONTROL);                       // the ball arrives, he controls it
  if (prev.type === "pass" && prev.outcome === "offside") g += 1.4;        // time to see the offside line
  if (ev.type === "pass" && ev.outcome === "offside") g = Math.max(g, 2.6);  // time to set the scene
  if (ev.type === "foul") g = Math.max(g, 1.0);                            // time to close him down
  const sp = setPieceKind(ev);
  if (sp) g = Math.max(g, SET_PIECE_LEAD[sp] + 0.4);                       // time to take up positions
  return g;
}

/* A cut, as in a TV edit: the picture dips to dark, the ball and the players are put where
 * the next move starts, and the picture comes back. Nobody is seen running across the pitch. */
function cutTo(ev) {
  const now = performance.now();
  state.cut = { t0: now, mid: now + 300, end: now + 650, at: ev.loc };
  setTimeout(() => {
    const b = state.ball;
    Object.assign(b, { x: ev.loc[0], y: ev.loc[1], fx: ev.loc[0], fy: ev.loc[1], tx: ev.loc[0], ty: ev.loc[1],
                       t0: performance.now(), dur: 1, via: null, viaDur: 0 });
    state.ballLag = { x: ev.loc[0], y: ev.loc[1] };
    state.trail = null; state.shotLine = null; state.receiver = null; state.actor = null; state.presser = null;
    state.snapUntil = performance.now() + 120;          // everyone straight to his place
  }, 300);
}

/* One play-by-play call. The voice is shared: a goal call (3) beats a big call such as a
 * shot or a save (2), which beats the colour line (1.5), which beats a passing call (1).
 * A call never talks over a more important line; a small one is simply dropped. */
function sayCall(c, cv) {
  const busy = audio.voiceBusy();
  const voiced = cv && state.sound.voice && (!busy || busy.prio < c.priority);
  if (voiced) audio.playVoice(cv.el, c.priority);
  if (voiced || (!busy && !subtitleBusy()) || c.priority >= 2)
    showSubtitles([c.subtitle || c.text], Math.max(1400, (cv ? cv.duration : 1.2) * 1000));
}

/* Screen times of a segment's events (seconds from its start), and its length. */
function segmentTimes(evs) {
  const times = new Map();
  const firstSp = evs.length ? setPieceKind(evs[0]) : null;
  let clock = firstSp ? SET_PIECE_LEAD[firstSp] + 0.4          // a set piece first: time to set it up
    : evs.length && evs[0].outcome === "offside" ? 2.6           // an offside pass first: time for the line
    : evs.length && evs[0].cut ? CUT : 0;                      // a cut first: time for the picture to dip
  let lastBall = null;
  evs.forEach((ev) => {
    if (lastBall) clock += paceGap(lastBall, ev);
    times.set(ev, clock);
    if (ev.type !== "pressure") lastBall = ev;
  });
  return { times, end: clock };
}
/* The player of an upcoming action runs to its spot, to get there in `lead` seconds (at most
 * his top speed). For a foul, the player fouled goes there too: it takes two. */
function setApproach(ev, lead, hold = 600) {
  const now = performance.now(), arrive = now + lead * 1000;
  state.approaches.set(ev.player_id, { id: ev.player_id, x: ev.loc[0], y: ev.loc[1], arrive, forIdx: ev.idx,
                                       until: arrive + hold, shot: ev.type === "shot" });
  if (ev.type === "foul" && ev.on_player_id && state.players[ev.on_player_id]) {
    state.approaches.set(ev.on_player_id, { id: ev.on_player_id, x: ev.loc[0] + 0.8, y: ev.loc[1], arrive,
                                            forIdx: ev.idx, until: arrive + hold });
  }
}

const APPROACH_TYPES = new Set(["pass", "carry", "dribble", "shot", "clearance", "interception", "ball_recovery", "duel",
                                "goalkeeper", "foul"]);
const NOTABLE = new Set(["shot", "card", "substitution", "tactical_change", "injury", "offside", "period_end", "match_end"]);
const player = (() => {
  const buffer = [], held = [];
  let seg = null, playedSeq = -1, started = false, pausedUntil = 0, finished = false, secondHalfDue = false;

  function add(segment) {
    if (state.sound.voice && segment.audio) segment.voice = audio.loadVoice(withSession(`/api/audio/${segment.audio}`));
    // the play-by-play calls are fetched in advance too, so each starts on its action
    for (const c of segment.calls || []) {
      if (state.sound.voice && c.audio) c.voice = audio.loadVoice(withSession(`/api/audio/${c.audio}`));
    }
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
    const cap = i.captains || {};
    const list = (side) => side.players.map((p) => `<li><b>${p.number}</b> ${escapeHtml(p.name)}${Object.values(cap).includes(p.id) ? " (C)" : ""}</li>`).join("");
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
    const intro = i.intro_audio && state.sound.voice ? await audio.loadVoice(withSession(`/api/audio/intro-${state.viewer}`)) : null;
    if (intro) audio.playVoice(intro.el);
    await sleep(Math.max(8000, (intro ? intro.duration : 0) * 1000 + 800));
    while (buffer.length < 2 && !finished) { updateWaiting(); await sleep(300); if (buffer.some((s) => s.full_time)) break; }
    $("#prematch").hidden = true;
    walkOn(kickingSide());                        // the teams come out of the tunnel
    await sleep(WALK_MS);
    $("#phase").textContent = "First half";
    showMoment("Kick-off", `${h.team.name} v ${a.team.name}`, "quiet", 1600);
    started = true;
  }

  function kickingSide() {                        // who kicks off next, from the segments ready
    for (const s of buffer) { const k = s.events.find((e) => e.type === "kick_off"); if (k) return sideOf(k.team_id); }
    return "home";
  }

  async function next() {
    if (seg || !started || !buffer.length || performance.now() < pausedUntil) return;
    if (secondHalfDue) {                          // back out for the second half
      secondHalfDue = false;
      state.period = 2;                             // ends switched: they walk out to their new halves
      walkOn(kickingSide());
      $("#phase").textContent = "Second half";
      selectTab("feed");
      pausedUntil = performance.now() + WALK_MS;
      return;
    }
    seg = buffer.shift();
    const v = seg.voice ? await seg.voice : null;
    const S = v ? v.duration : 0;
    const evs = seg.events;
    const { times, end: clock } = segmentTimes(evs);
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
    // the player who makes the next action gets to the ball first: nobody kicks a ball from afar
    evs.forEach((ev, i) => {
      if (!ev.player_id || !ev.loc || !APPROACH_TYPES.has(ev.type) || setPieceKind(ev)) return;
      // he sets off early enough to get there at a footballer's speed: up to five seconds
      // (four actions) before, never before his own previous action
      // (his own pressing on the ball carrier is part of the same run, not a stop)
      // a defender who goes in for a tackle reads it from further back
      const horizon = ev.type === "foul" ? 8 : 5, maxActions = ev.type === "foul" ? 6 : 4;
      let j = i, actions = 0;
      while (j > 0 && actions < maxActions && at(ev) - at(evs[j - 1]) <= horizon) {
        const q = evs[j - 1];
        if (q.type !== "pressure" && (q.player_id === ev.player_id || q.recipient_id === ev.player_id)) break;
        j--; if (q.type !== "pressure") actions++;
      }
      if (j === i && i > 0) j = i - 1;
      // he runs to where the ball will be: the end of the pass he receives, else the spot
      const prev = evs.slice(0, i).reverse().find((q) => q.type !== "pressure");
      const spot = prev && prev.type === "pass" && prev.recipient_id === ev.player_id && prev.end ? prev.end : ev.loc;
      const before = i ? at(ev) - at(evs[j]) : 0.6;
      const lead = Math.min(horizon, Math.max(0.25, before));
      const tEv = at(ev), target = spot === ev.loc ? ev : { ...ev, loc: spot };
      // an action right at the start of the segment: his run began in the previous one,
      // keep it (do not cut it short to a fraction of a second)
      const ap = state.approaches.get(ev.player_id);
      if (i === 0 && ap && ap.forIdx === ev.idx) return;
      tasks.push({ t: Math.max(0, tEv - lead), run: () => setApproach(target, lead) });
    });
    // a corner or a free kick into the box: the player it is aimed at is there when it comes in
    evs.forEach((ev) => {
      if (ev.type !== "pass" || !["corner", "free_kick"].includes(ev.pass_type) || !ev.recipient_id || !ev.end) return;
      if (!state.players[ev.recipient_id]) return;
      const lead = SET_PIECE_LEAD[setPieceKind(ev)] || 3.8, arriveIn = lead + flightOf(ev);
      tasks.push({ t: Math.max(0, at(ev) - lead), run: () => {
        const now = performance.now();
        state.approaches.set(ev.recipient_id, { id: ev.recipient_id, x: ev.end[0], y: ev.end[1], forIdx: ev.idx,
                                                arrive: now + arriveIn * 1000, until: now + arriveIn * 1000 + 400 });
      } });
    });
    // the first actions of the NEXT segment: their players set off now, so a shot or a foul
    // at the very start of a segment still has its player on the spot
    const upcoming = buffer[0];
    if (upcoming && upcoming.events.length) {
      const nt = segmentTimes(upcoming.events).times;
      for (const ev of upcoming.events) {
        const tn = nt.get(ev);
        if (tn > 5) break;
        if (!ev.player_id || !ev.loc || !APPROACH_TYPES.has(ev.type) || setPieceKind(ev)) continue;
        const startAt = Math.max(0, D + tn - 5);
        // he waits on the spot if the next segment starts a little late (a line still being said)
        tasks.push({ t: startAt, run: () => setApproach(ev, D + tn - startAt + 0.3, 3000) });
      }
    }
    // a cut between two moves: the picture dips, everyone is in place for the next move
    for (const ev of evs) {
      if (ev.cut && ev.loc) tasks.push({ t: Math.max(0, at(ev) - CUT + 0.05), run: () => cutTo(ev) });
    }
    // offside: the back line steps up a moment before the pass, so the scene reads clearly
    for (const ev of evs) {
      if (ev.type === "pass" && ev.outcome === "offside" && ev.end) {
        // the players take up the scene before the pass; the line appears when the ball is played
        tasks.push({ t: Math.max(0, at(ev) - 2.4), run: () => {
          const now = performance.now(), passAt = now + (at(ev) - Math.max(0, at(ev) - 2.4)) * 1000;
          showOffside(ev, now, 2700, passAt);
        } });
      }
    }
    // set pieces: the players take up their places just before the kick
    for (const ev of evs) {
      const kind = setPieceKind(ev);
      if (kind === "kickoff") {                        // both teams back in their own half
        tasks.push({ t: Math.max(0, at(ev) - SET_PIECE_LEAD.kickoff), run: () => {
          setKickoff(sideOf(ev.team_id), ev.player_id, (SET_PIECE_LEAD.kickoff + 0.3) * 1000);
          rollBall([60, 40], 900);
        } });
        continue;
      }
      if (!kind || !ev.loc) continue;
      const side = sideOf(ev.team_id), [axT] = toAbsFor(side, ev.loc);
      const lead = SET_PIECE_LEAD[kind];
      tasks.push({ t: Math.max(0, at(ev) - lead), run: () => {
        const box = kind !== "free kick" || axT > 80;      // a free kick far out: no wall of bodies
        const now = performance.now();
        state.setPiece = box ? { kind: kind === "penalty" ? "penalty" : kind === "free kick" ? "freekick" : "box",
                                 side, taker: ev.player_id, ball: ev.loc, until: now + (lead + 1.2) * 1000 } : null;
        rollBall(ev.loc, 700);
        const team = state.init[side].team.name;
        let how = "";
        const lt = state.lastTouch;
        if (kind === "corner" && lt && lt.side !== side && now - lt.at < 15000) {
          how = lt.type === "goalkeeper" ? ` · ${lt.name} turned it behind` : lt.type === "block" ? ` · blocked by ${lt.name}`
            : ` · put behind by ${lt.name}`;
        }
        showChip(kind === "penalty" ? `${short(ev.player_id, ev.player)} steps up` : `${team}: ${short(ev.player_id, ev.player)} to take${how}`,
                 kind === "penalty" ? "penalty" : "", lead * 1000 + 600,
                 kind === "corner" ? "Corner" : kind === "penalty" ? "Penalty" : "Free kick");
      } });
    }
    for (const st of seg.stats || []) {
      const ev = evs.find((e) => e.idx >= st.idx) || evs[evs.length - 1];
      tasks.push({ t: ev ? at(ev) + 0.05 : D, run: () => { renderStats(st.panel); if (st.ratings) renderRatings(st.ratings); } });
    }
    // play-by-play: each call on its own action ("Pickering for Thibault." "Thibault shoots!")
    for (const c of seg.calls || []) {
      const ev = evs.find((e) => e.idx === c.idx) || evs.find((e) => e.idx > c.idx);
      if (!ev) continue;
      const cv = c.voice ? await c.voice : null;
      const shotLike = ["shot", "header", "fk_shot", "penalty_shot"].includes(c.kind);
      // a shot is called as the striker shapes to hit it; a pass as the ball leaves his foot
      const t = Math.max(0, at(ev) + (shotLike ? -0.45 : c.kind === "save" ? 0.15 : 0.1));
      tasks.push({ t, run: () => sayCall(c, cv) });
    }
    tasks.push({ t: voiceAt, run: function narratorLine() {
      if (!goalEv && v && audio.voiceBusy() && (this.waited || 0) < 2) {
        // the commentator finishes his call before adding the colour
        const wait = audio.voiceBusy().remaining + 0.25, r = seg && seg.run;
        if (r) {
          const t = (performance.now() - r.start) / 1000 + wait;
          const task = { t, waited: (this.waited || 0) + 1, run: narratorLine };
          task.run = narratorLine.bind(task);
          let k = r.i; while (k < r.tasks.length && r.tasks[k].t <= t) k++;
          r.tasks.splice(k, 0, task);
          r.D = Math.max(r.D, t + 0.6);
          return;
        }
      }
      if (goalEv) {
        const how = goalEv.shot_type === "Penalty" ? "  ·  penalty" : goalEv.shot_type === "Free Kick" ? "  ·  free kick" : "";
        showMoment("GOAL", `${goalEv.scorer || goalEv.player} ${goalEv.minute}'${how}`, "", Math.min(3500, celebrate * 1000));
      }
      if (v) audio.playVoice(v.el, goalEv ? 3 : 1.5);
      if (seg.commentary) {
        renderItem(seg.commentary, true); pulseAgent("narrator");
        const pl = seg.commentary.payload;
        const lines = splitSentences(pl.subtitle || pl.text);
        // the voice says a whole goal call, but only the first sentence of an ordinary line
        showSubtitles(pl.goal ? lines : lines.slice(0, 1), Math.max(S, 3.2) * 1000);
      }
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
      walkOff();                                  // the players head down the tunnel
      pausedUntil = performance.now() + 12000;
      secondHalfDue = true;
    }
    if (done.full_time) {
      finished = true;
      walkOff();
      audio.endOfMatch();                         // applause, then the stadium goes quiet
      $("#phase").textContent = "Full time";
      showMoment("Full time", `${$("#home-name").textContent} ${$("#home-score").textContent}–${$("#away-score").textContent} ${$("#away-name").textContent}`, "quiet", 6000);
    }
  }
  return { add, item, prematch, tick };
})();

/* Live player ratings (0-10) for both teams; the best-rated player gets the golden ball. */
function renderRatings(ratings) {
  state.ratings = ratings;
  let top = null;
  for (const [id, r] of Object.entries(ratings)) if (state.players[id] && (!top || r > ratings[top])) top = id;
  state.topRated = top;
  const col = (side) => {
    const rows = Object.entries(state.players)
      .filter(([id, p]) => p.side === side && ratings[id] != null)
      .sort((a, b) => ratings[b[0]] - ratings[a[0]])
      .map(([id, p]) => `<li class="${id === top ? "top" : ""}${p.onPitch ? "" : " off"}">
          <b>${p.number}</b><span>${escapeHtml(p.short)}${state.captainIds.has(id) ? " (C)" : ""}</span>
          ${id === top ? '<i class="golden-ball" title="Man of the match so far"></i>' : ""}
          <em class="${ratings[id] >= 8 ? "hi" : ratings[id] < 6 ? "lo" : ""}">${ratings[id].toFixed(1)}</em></li>`).join("");
    return `<div><h4>${escapeHtml(state.init[side].team.name)}</h4><ol>${rows}</ol></div>`;
  };
  $("#ratings").innerHTML = `<h3>Player ratings</h3><div class="ratings-cols">${col("home")}${col("away")}</div>`;
}

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
    if (!ctx || !state.sound.crowd || state.matchOver) return;
    const b = await buffer(name); if (!b) return;
    const src = ctx.createBufferSource(); src.buffer = b;
    const g = ctx.createGain(); g.gain.value = gain;
    src.connect(g).connect(master); src.start();
    return src;
  }
  async function startMurmur() {
    if (!ctx || murmurNode || state.matchOver) return;
    const b = await buffer("murmur"); if (!b) { setTimeout(startMurmur, 3000); return; }
    murmurNode = ctx.createBufferSource(); murmurNode.buffer = b; murmurNode.loop = true;
    const g = ctx.createGain(); g.gain.value = 0.35;
    murmurNode.connect(g).connect(master); murmurNode.start();
  }
  function stopMurmur() { if (murmurNode) { murmurNode.stop(); murmurNode = null; } }
  // full time: the applause dies down and the stadium goes quiet (the studio voice stays)
  function endOfMatch(afterMs = 7000) {
    setTimeout(() => {
      state.matchOver = true;
      if (!ctx || !master) { stopMurmur(); return; }
      master.gain.cancelScheduledValues(ctx.currentTime);
      master.gain.setValueAtTime(master.gain.value, ctx.currentTime);
      master.gain.linearRampToValueAtTime(0, ctx.currentTime + 4);
      setTimeout(stopMurmur, 4200);
    }, afterMs);
  }

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
    if (!master || state.matchOver) return;
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
  let voicePrio = 0;
  function playVoice(el, prio = 1.5) {
    if (!el || !state.sound.voice) return;
    if (voiceEl && voiceEl !== el) voiceEl.pause();
    voiceEl = el; voicePrio = prio; duck(true);
    try { el.currentTime = 0; } catch (_) { /* not loaded yet */ }
    el.addEventListener("ended", () => { if (voiceEl === el) { voiceEl = null; duck(false); } }, { once: true });
    el.play().catch(() => { if (voiceEl === el) voiceEl = null; duck(false); });
  }
  function voiceBusy() {               // what is being said now, and for how much longer
    if (!voiceEl || voiceEl.paused || voiceEl.ended) return null;
    const left = (isFinite(voiceEl.duration) ? voiceEl.duration : 2) - voiceEl.currentTime;
    return left > 0.05 ? { prio: voicePrio, remaining: left } : null;
  }
  async function playUrl(url) { const v = await loadVoice(url); if (v) playVoice(v.el); return v; }
  function stopVoice() { if (voiceEl) voiceEl.pause(); voiceEl = null; duck(false); }
  function whistle(name) { play(name, 0.55); }
  return { unlock, startMurmur, stopMurmur, endOfMatch, crowdCues, loadVoice, playVoice, voiceBusy, playUrl, stopVoice, whistle };
})();

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

loadTeams().catch((e) => { $("#match-status").textContent = `Could not load the clubs: ${e.message}`; });
