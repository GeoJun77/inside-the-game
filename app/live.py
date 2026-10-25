"""A live match session: replays a synthetic match in real time and runs the agents on it.

Two threads work together:
    - the CLOCK replays the match events at the chosen speed and streams them to the
      browsers for the animated pitch, the score and the clock; every few minutes of play
      (or at a key moment) it hands a batch of events to the agents;
    - the AGENTS worker runs the orchestrator on each batch (commentary, crowd, analysis,
      show plans) and every item it puts on air is streamed to the viewers who should see it.

At half-time the clock waits for the studio segment (analysis + show plans), like a real
broadcast break, then plays the second half.
"""
from __future__ import annotations

import itertools
import queue
import threading
import time
import uuid

from agents import voice as voice_mod
from agents.match_tools import match_minute, minute_label
from agents.narrator_agent import ViewerSettings
from agents.narrator_feed import is_key_moment
from agents.orchestrator import BroadcastItem, Orchestrator
from agents.producer_agent import ViewerProfile
from matchsim import build_league, get_team, simulate_match
from matchsim.formations import POSITION_XY

PITCH_TYPES = {"pass", "carry", "shot", "dribble", "duel", "interception", "foul", "card", "goal",
               "substitution", "period_start", "period_end", "kick_off", "goalkeeper", "offside",
               "clearance", "block", "ball_recovery", "tactical_change", "injury", "match_end"}
BATCH_MINUTES = 5
HALF_TIME_WAIT_S = 150        # longest the clock waits for the half-time studio
_ids = itertools.count(1)


def _pitch_event(e: dict) -> dict:
    """The few fields the browser needs to animate an event."""
    d = e.get("details") or {}
    out = {"type": e["type"], "team_id": e["team_id"], "player_id": e["player_id"], "player": e["player"],
           "loc": e["location_abs"], "end": e["end_location_abs"], "outcome": e["outcome"],
           "minute": minute_label(e) if e["period"] else "0", "period": e["period"],
           "score": e["score"], "duration": e.get("duration_s", 0)}
    if e["type"] == "shot":
        out.update(xg=d.get("xg"), body_part=d.get("body_part"), goalkeeper=d.get("goalkeeper"))
    elif e["type"] == "goal":
        out.update(scorer=d.get("scorer"), assist=d.get("assist"), xg=d.get("xg"))
    elif e["type"] == "substitution":
        out.update(player_on=d.get("player_on"), player_on_id=d.get("player_on_id"),
                   player_off=d.get("player_off"), player_off_id=d.get("player_off_id"), slot=d.get("slot"))
    elif e["type"] == "card":
        out.update(card=e["outcome"])
    elif e["type"] == "pass":
        out.update(recipient=d.get("recipient"), recipient_id=d.get("recipient_id"))
    elif e["type"] == "tactical_change":
        out.update(description=d.get("description"))
    return out


class LiveSession:
    def __init__(self, project, home: str, away: str, seed: int = 7, speed: float = 25.0):
        self.id = uuid.uuid4().hex[:8]
        league = build_league()
        self.events = simulate_match(get_team(league, home), get_team(league, away), seed=seed)
        self.start_info = self.events[0]["details"]
        self.speed = max(1.0, float(speed))
        self.orch = Orchestrator(project, self.events, viewers={}, commentary_window=None, echo=False)
        self.orch.listeners.append(self._on_item)
        self.viewers = self.orch.viewers            # shared dict: joining adds an audience
        self.subscribers: dict[str, queue.Queue] = {}
        self.work: queue.Queue = queue.Queue()
        self.status = "waiting"                     # waiting, live, half_time, full_time
        self.clock = {"minute": "0", "period": 0, "score": {"home": 0, "away": 0}}
        self.stop_flag = threading.Event()
        self.voice = voice_mod.Voice() if voice_mod.is_configured() else None
        self.audio_cache: dict[int, bytes] = {}
        self.audio_lock = threading.Lock()

    # ---------- viewers ----------
    def join(self, profile: dict) -> str:
        vid = "v" + uuid.uuid4().hex[:6]
        fav = profile.get("favourite_team") or None
        self.viewers[vid] = ViewerProfile(
            name=profile.get("name") or "Viewer", language=profile.get("language") or "English",
            audience=profile.get("audience") or "fan", favourite_team=fav,
            followed_player=profile.get("followed_player") or None)
        self.subscribers[vid] = queue.Queue()
        return vid

    def tag_of(self, vid: str) -> str:
        v = self.viewers[vid]
        return ViewerSettings(v.language, v.audience, v.favourite_team).tag()

    def visible(self, item: BroadcastItem, vid: str) -> bool:
        return item.audience in ("all", vid) or (vid in self.viewers and item.audience == self.tag_of(vid))

    def init_payload(self, vid: str) -> dict:
        s = self.start_info

        def lineup(side):
            return {"team": s[side]["team"], "formation": s[side]["formation"],
                    "players": [{"id": p["id"], "name": p["name"], "short": p["short_name"], "number": p["number"],
                                 "slot": p["slot"]} for p in s[side]["starting_xi"]],
                    "bench": [{"id": p["id"], "name": p["name"], "short": p["short_name"], "number": p["number"],
                               "position": p["position"]} for p in s[side]["bench"]]}
        past = [self.serialize(it) for it in self.orch.timeline if self.visible(it, vid)]
        return {"session": self.id, "viewer_id": vid, "viewer": self.viewers[vid].__dict__,
                "audience_tag": self.tag_of(vid), "home": lineup("home"), "away": lineup("away"),
                "venue": s["venue"], "referee": s["referee"], "weather": s["weather"],
                "attendance": s["attendance"], "positions": POSITION_XY, "status": self.status,
                "clock": self.clock, "speed": self.speed, "voice": self.voice is not None, "past": past}

    # ---------- streaming ----------
    def serialize(self, it: BroadcastItem) -> dict:
        return {"id": it.id, "minute": it.minute, "kind": it.kind, "agent": it.agent,
                "audience": it.audience, "payload": it.payload, "degraded": it.degraded}

    def _broadcast(self, message: dict, only: str | None = None) -> None:
        for vid, q in list(self.subscribers.items()):
            if only is None or vid == only:
                q.put(message)

    def _on_item(self, item: BroadcastItem) -> None:
        for vid, q in list(self.subscribers.items()):
            if self.visible(item, vid):
                q.put({"event": "item", "data": self.serialize(item)})

    def _set_status(self, status: str) -> None:
        self.status = status
        self._broadcast({"event": "status", "data": {"status": status, "clock": self.clock}})

    # ---------- the two threads ----------
    def start(self) -> None:
        if self.status != "waiting":
            return
        self._set_status("live")
        threading.Thread(target=self._agents_loop, daemon=True).start()
        threading.Thread(target=self._clock_loop, daemon=True).start()

    def _agents_loop(self) -> None:
        while not self.stop_flag.is_set():
            job = self.work.get()
            try:
                if job == "FULL_TIME":
                    self.orch.full_time()
                    self._broadcast({"event": "metrics", "data": self.orch.supervisor.report()})
                else:
                    self.orch.on_batch(job)
            except Exception as exc:          # noqa: BLE001 - the show must go on
                print(f"agents worker error: {type(exc).__name__}: {exc}")
            finally:
                self.work.task_done()

    def _clock_loop(self) -> None:
        start_wall, batch, last_cut = time.time(), [], 0
        for e in self.events:
            if self.stop_flag.is_set():
                return
            if e["type"] == "period_start":
                # the match clock restarts at 45:00 in the second half: re-anchor the replay
                start_wall = time.time() - e["match_seconds"] / self.speed
            target = e["match_seconds"] / self.speed
            delay = target - (time.time() - start_wall)
            if delay > 0:
                time.sleep(min(delay, 5.0))
            self.clock = {"minute": minute_label(e) if e["period"] else "0", "period": e["period"],
                          "score": e["score"]}
            if e["type"] in PITCH_TYPES:
                self._broadcast({"event": "pitch", "data": _pitch_event(e)})
            batch.append(e)
            minute = match_minute(e)
            if is_key_moment(e) or minute - last_cut >= BATCH_MINUTES:
                self.work.put(batch)
                batch, last_cut = [], minute
            if e["type"] == "period_end" and (e.get("details") or {}).get("period") == 1:
                # half-time studio: wait until the agents have finished the segment
                self._set_status("half_time")
                self._wait_for_agents(HALF_TIME_WAIT_S)
                self._set_status("live")
        if batch:
            self.work.put(batch)
        self.work.put("FULL_TIME")
        self._set_status("full_time")

    def _wait_for_agents(self, timeout: float) -> None:
        deadline = time.time() + timeout
        while self.work.unfinished_tasks and time.time() < deadline:
            time.sleep(0.5)

    def stop(self) -> None:
        self.stop_flag.set()

    # ---------- viewer actions ----------
    def ask(self, vid: str, question: str) -> list[dict]:
        return [self.serialize(it) for it in self.orch.ask(vid, question)]

    def audio(self, item_id: int) -> bytes | None:
        """The commentator's voice for one commentary item (synthesised once, then cached)."""
        if not self.voice:
            return None
        with self.audio_lock:
            if item_id in self.audio_cache:
                return self.audio_cache[item_id]
        item = next((it for it in self.orch.timeline if it.id == item_id), None)
        if not item or item.kind not in ("commentary", "recap"):
            return None
        language = item.audience.split("/")[0] if "/" in item.audience else "English"
        text = item.payload.get("speech") or item.payload.get("text", "")
        if item.kind == "recap":
            text = text.split(". ")[0] + "."
        data = self.voice.speak(text, language, item.payload.get("excitement", 2))
        with self.audio_lock:
            self.audio_cache[item_id] = data
        return data
