/* Inside the Game - the live broadcast in the browser.
 *
 * The server streams two kinds of messages (Server-Sent Events):
 *   - "pitch": every match event (pass, shot, goal...) to animate the pitch, score and clock;
 *   - "item":  everything the agents put on air for this viewer (commentary, crowd,
 *              analysis, stats panel, show plans, answers, recap).
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
  state.colors.home = kitOnGrass(init.home.team.colors);
  state.colors.away = kitOnGrass(init.away.team.colors);
  document.documentElement.style.setProperty("--home", init.home.team.colors[0]);
  document.documentElement.style.setProperty("--away", init.away.team.colors[0]);
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
  updateClock(init.clock, init.status);
  for (const item of init.past) renderItem(item, true);
  connectStream();
  requestAnimationFrame(draw);
  if (state.sound.crowd) audio.startMurmur();
  setInterval(refreshMetrics, 10000);
}

function connectStream() {
  const es = new EventSource(`/api/stream?viewer=${state.viewer}`);
  es.addEventListener("pitch", (e) => onPitch(JSON.parse(e.data)));
  es.addEventListener("item", (e) => renderItem(JSON.parse(e.data)));
  es.addEventListener("status", (e) => { const d = JSON.parse(e.data); updateClock(d.clock, d.status); });
  es.addEventListener("metrics", () => refreshMetrics());
}

function updateClock(clock, status) {
  if (clock) {
    $("#clock").textContent = `${clock.minute}'`;
    setScore(clock.score);
  }
  const phases = { waiting: "Pre-match", live: state.period === 2 ? "Second half" : "First half",
                   half_time: "Half-time", full_time: "Full time" };
  if (status) $("#phase").textContent = phases[status] || status;
  if (status === "half_time") showMoment("Half-time", "The studio takes over", "quiet", 3500);
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
                          onPitch: true, x: 60, y: 40, tx: 60, ty: 40, base };
}

/* matchsim's "abs" frame: the home team attacks left to right in the first half. */
function toAbs(side, x, y) {
  const homeRight = state.period !== 2;
  const right = (side === "home") === homeRight;
  return right ? [x, y] : [120 - x, 80 - y];
}

function onPitch(ev) {
  state.period = ev.period || state.period;
  if (ev.minute) $("#clock").textContent = `${ev.minute}'`;
  if (ev.score) setScore(ev.score);
  if (ev.type === "period_start") $("#phase").textContent = ev.period === 2 ? "Second half" : "First half";
  const t = performance.now();
  if (ev.loc) {
    const b = state.ball;
    b.fx = b.x; b.fy = b.y;
    const [ex, ey] = ev.end || ev.loc;
    b.tx = ex; b.ty = ey;
    if (!ev.end) { b.fx = ev.loc[0]; b.fy = ev.loc[1]; }
    b.t0 = t; b.dur = ev.type === "pass" || ev.type === "shot" ? 450 : 300;
  }
  if (ev.player_id && state.players[ev.player_id] && ev.loc) {
    state.actor = { id: ev.player_id, until: t + 1200, x: ev.loc[0], y: ev.loc[1] };
  }
  if (ev.type === "pass" && ev.recipient_id && state.players[ev.recipient_id] && ev.end) {
    state.receiver = { id: ev.recipient_id, until: t + 1200, x: ev.end[0], y: ev.end[1] };
  }
  if (ev.type === "shot") {
    state.shotLine = { from: ev.loc, to: ev.end || ev.loc, xg: ev.xg, until: t + 2500, side: sideOf(ev.team_id) };
  }
  if (ev.type === "substitution") {
    const off = state.players[ev.player_off_id];
    if (off) off.onPitch = false;
    const on = state.players[ev.player_on_id];
    if (on) Object.assign(on, { onPitch: true, slot: ev.slot, base: state.init.positions[ev.slot] || [60, 40],
                                x: off ? off.x : 60, y: off ? off.y : 40 });
  }
  if (ev.type === "goal") showMoment("GOAL", `${ev.scorer} ${ev.minute}'`, "", 4000);
  if (ev.type === "card" && (ev.card === "red" || ev.card === "second_yellow")) showMoment("Red card", ev.player, "card", 3000);
  $("#ticker").textContent = tickerText(ev);
}

/* A green kit disappears on green grass: then the shirt uses the club's second colour. */
function kitOnGrass([primary, secondary]) {
  const lum = (hex) => {
    const [r, g, b] = [1, 3, 5].map((i) => parseInt(hex.slice(i, i + 2), 16) / 255)
      .map((c) => (c <= 0.03928 ? c / 12.92 : ((c + 0.055) / 1.055) ** 2.4));
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  const contrast = (a, b) => (Math.max(lum(a), lum(b)) + 0.05) / (Math.min(lum(a), lum(b)) + 0.05);
  return contrast(primary, "#1E6B45") < 1.6 ? [secondary, primary] : [primary, secondary];
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
    const shiftX = (bxT - 60) * (gk ? 0.08 : 0.42);
    const shiftY = (byT - 40) * (gk ? 0.05 : 0.18);
    let tx = Math.max(2, Math.min(118, p.base[0] + shiftX));
    let ty = Math.max(3, Math.min(77, p.base[1] + shiftY));
    [tx, ty] = toAbs(p.side, tx, ty);
    for (const special of [state.actor, state.receiver]) {
      if (special && special.id === id && now < special.until) { tx = special.x; ty = special.y; }
    }
    p.x += (tx - p.x) * 0.07; p.y += (ty - p.y) * 0.07;
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
    if (!fromHistory && state.sound.voice && state.init.voice) audio.speak(item.id);
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
    if (!fromHistory && state.sound.voice && state.init.voice) audio.speak(item.id);
  } else return;
  li.innerHTML = `<span class="min">${item.minute === "FT" ? "FT" : item.minute + "'"}</span><div class="body">${body}</div>`;
  $("#feed").prepend(li);
  $("#feed-empty").hidden = true;
}

function renderStats(panel) {
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
  function speak(itemId) { voiceQueue.push(itemId); if (voiceQueue.length > 3) voiceQueue.shift(); next(); }
  function next() {
    if (speaking || !voiceQueue.length || !state.sound.voice) return;
    speaking = true;
    const id = voiceQueue.shift();
    current = new Audio(`/api/audio/${id}`);
    duck(true);
    const done = () => { speaking = false; current = null; duck(false); next(); };
    current.addEventListener("ended", done);
    current.addEventListener("error", done);
    current.play().catch(done);
  }
  function stopVoice() { voiceQueue.length = 0; if (current) current.pause(); speaking = false; duck(false); }
  return { unlock, startMurmur, stopMurmur, crowdCues, speak, stopVoice };
})();

function escapeHtml(s) {
  return String(s ?? "").replace(/[&<>"']/g, (ch) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[ch]));
}

loadTeams().catch((e) => { $("#match-status").textContent = `Could not load the clubs: ${e.message}`; });
