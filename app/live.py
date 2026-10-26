"""A live match session, played like a match in a football manager game (Top Eleven style).

The match is simulated before kick-off, so the agents can work a little ahead of what the
viewer sees, like a broadcast delay. The DIRECTOR thread cuts the match into segments (a
few minutes of play, or up to a key moment such as a goal) and, for each one, ahead of time:
    - runs the orchestrator: commentary for every audience, crowd reactions, analyses;
    - makes the commentator's voice for each line;
    - computes the live stats after every shot, goal or card;
then sends the ready segment to the viewers. The browser plays each segment on ONE clock:
the action on the pitch, the voice, the GOAL screen, the crowd and the stats, so the
commentator says "GOAL" exactly when the goal is shown.

The director stays at most LOOKAHEAD segments ahead of the slowest viewer, so a question
asked during the match is answered with the match as the viewer has seen it (no spoilers).
At half-time the studio segment (analysis, show plans) runs after the half-time segment.
"""
from __future__ import annotations

import queue
import re
import threading
import time
import uuid
from concurrent.futures import ThreadPoolExecutor

from agents import voice as voice_mod
from agents.match_tools import MatchContext, match_minute, minute_label
from agents.narrator_agent import ViewerSettings
from agents.narrator_feed import is_key_moment
from agents.orchestrator import BroadcastItem, Orchestrator
from agents.producer_agent import ViewerProfile
from agents.producer_tools import ProducerTools
from matchsim import build_league, get_team, simulate_match
from matchsim.formations import POSITION_XY

PITCH_TYPES = {"pass", "carry", "shot", "dribble", "duel", "interception", "foul", "card", "goal",
               "substitution", "period_start", "period_end", "kick_off", "goalkeeper", "offside",
               "clearance", "block", "ball_recovery", "tactical_change", "injury", "match_end", "pressure"}
STATS_AFTER = {"shot", "goal", "card", "period_end", "match_end"}   # live stats refresh points
SEGMENT_MINUTES = 5          # a segment closes after this much play, or at a key moment
LOOKAHEAD = 2                # segments prepared ahead of the slowest viewer
PROGRESS_TIMEOUT_S = 90      # a silent viewer stops holding the director back after this


def _pitch_event(e: dict, idx: int) -> dict:
    """The few fields the browser needs to animate an event."""
    d = e.get("details") or {}
    out = {"idx": idx, "ms": e["match_seconds"], "type": e["type"], "team_id": e["team_id"],
           "player_id": e["player_id"], "player": e["player"], "loc": e["location_abs"],
           "end": e["end_location_abs"], "outcome": e["outcome"],
           "minute": minute_label(e) if e["period"] else "0", "period": e["period"], "score": e["score"]}
    if e["type"] == "shot":
        out.update(xg=d.get("xg"), body_part=d.get("body_part"), goalkeeper=d.get("goalkeeper"),
                   shot_type=d.get("shot_type"))
    elif e["type"] == "goal":
        out.update(scorer=d.get("scorer"), assist=d.get("assist"), xg=d.get("xg"))
    elif e["type"] == "foul":
        out.update(on_player=d.get("on_player"), on_player_id=d.get("on_player_id"),
                   in_box=bool(d.get("in_box")), card=d.get("card"))
    elif e["type"] == "pressure":
        out.update(on_player=d.get("on_player"))
    elif e["type"] == "substitution":
        out.update(player_on=d.get("player_on"), player_on_id=d.get("player_on_id"),
                   player_off=d.get("player_off"), player_off_id=d.get("player_off_id"), slot=d.get("slot"))
    elif e["type"] == "card":
        out.update(card=e["outcome"])
    elif e["type"] == "pass":
        out.update(recipient=d.get("recipient"), recipient_id=d.get("recipient_id"),
                   pass_type=d.get("pass_type"), cross=bool(d.get("cross")))
    elif e["type"] == "tactical_change":
        out.update(description=d.get("description"))
    elif e["type"] == "period_end":
        out.update(ended=d.get("period"))
    return out


def segments_of(events: list[dict]):
    """Cut the match into segments: a key moment (goal, big chance, card, half-time...)
    closes a segment at once, otherwise it closes every SEGMENT_MINUTES of play."""
    batch, start, last_cut = [], 0, 0
    for i, e in enumerate(events):
        batch.append(e)
        minute = match_minute(e)
        if is_key_moment(e) or minute - last_cut >= SEGMENT_MINUTES:
            yield start, batch
            start, batch, last_cut = i + 1, [], minute
    if batch:
        yield start, batch


class LiveSession:
    def __init__(self, project, home: str, away: str, seed: int = 7, speed: float = 15.0):
        self.id = uuid.uuid4().hex[:8]
        league = build_league()
        self.events = simulate_match(get_team(league, home), get_team(league, away), seed=seed)
        self.start_info = self.events[0]["details"]
        self.speed = max(1.0, float(speed))
        self.orch = Orchestrator(project, self.events, viewers={}, commentary_window=None, echo=False)
        self.orch.listeners.append(self._on_item)
        self.orch.background = ThreadPoolExecutor(max_workers=2)
        self.orch.defer_half_time = True
        self.viewers = self.orch.viewers            # shared dict: joining adds an audience
        self.subscribers: dict[str, queue.Queue] = {}
        self.progress: dict[str, dict] = {}         # viewer -> {"seq", "idx", "at"}
        self.status = "waiting"                     # waiting, live, half_time, full_time
        self.seq = -1                               # last segment sent
        self.working_seq = 0                        # segment the items published now belong to
        self.collect: list[BroadcastItem] | None = None   # commentary/crowd of the segment in work
        self.stop_flag = threading.Event()
        self.stats_ctx = MatchContext(self.events)  # its own context: stats at any moment
        self.stats_tools = ProducerTools(self.stats_ctx)
        self.voice = voice_mod.Voice() if voice_mod.is_configured() else None
        self.audio_cache: dict[str, bytes] = {}
        self.audio_lock = threading.Lock()
        self.voice_pool = ThreadPoolExecutor(max_workers=4)

    # ---------- viewers ----------
    def join(self, profile: dict) -> str:
        vid = "v" + uuid.uuid4().hex[:6]
        fav = profile.get("favourite_team") or None
        self.viewers[vid] = ViewerProfile(
            name=profile.get("name") or "Viewer", language=profile.get("language") or "English",
            audience=profile.get("audience") or "fan", favourite_team=fav,
            followed_player=profile.get("followed_player") or None)
        self.subscribers[vid] = queue.Queue()
        self.progress[vid] = {"seq": -1, "idx": 0, "at": time.time()}
        return vid

    def tag_of(self, vid: str) -> str:
        v = self.viewers[vid]
        return ViewerSettings(v.language, v.audience, v.favourite_team).tag()

    def visible(self, item: BroadcastItem, vid: str) -> bool:
        return item.audience in ("all", vid) or (vid in self.viewers and item.audience == self.tag_of(vid))

    def intro_text(self, vid: str) -> str:
        """The commentator's welcome, written by Python from the match facts (no model call)."""
        s = self.start_info
        h, a = s["home"], s["away"]
        return (f"Good evening, and welcome to {s['venue']}. {h['team']['name']} take on "
                f"{a['team']['name']}, with {s['referee']} the referee. {h['team']['name']} line up in a "
                f"{h['formation']}, {a['team']['name']} in a {a['formation']}. We are moments away from kick-off.")

    def init_payload(self, vid: str) -> dict:
        s = self.start_info

        def lineup(side):
            return {"team": s[side]["team"], "formation": s[side]["formation"],
                    "players": [{"id": p["id"], "name": p["name"], "short": p["short_name"], "number": p["number"],
                                 "slot": p["slot"]} for p in s[side]["starting_xi"]],
                    "bench": [{"id": p["id"], "name": p["name"], "short": p["short_name"], "number": p["number"],
                               "position": p["position"]} for p in s[side]["bench"]]}
        return {"session": self.id, "viewer_id": vid, "viewer": self.viewers[vid].__dict__,
                "audience_tag": self.tag_of(vid), "home": lineup("home"), "away": lineup("away"),
                "venue": s["venue"], "referee": s["referee"], "weather": s["weather"],
                "attendance": s["attendance"], "positions": POSITION_XY, "status": self.status,
                "speed": self.speed, "voice": self.voice is not None, "intro": self.intro_text(vid),
                "intro_audio": self.voice is not None and self.viewers[vid].language == "English"}

    # ---------- streaming ----------
    def serialize(self, it: BroadcastItem, seq: int | None = None) -> dict:
        return {"id": it.id, "minute": it.minute, "kind": it.kind, "agent": it.agent,
                "audience": it.audience, "payload": it.payload, "degraded": it.degraded,
                "seq": self.working_seq if seq is None else seq}

    def _send(self, vid: str, message: dict) -> None:
        q = self.subscribers.get(vid)
        if q:
            q.put(message)

    def _on_item(self, item: BroadcastItem) -> None:
        """Commentary and crowd go inside the segment being prepared; everything else
        (analysis, stats panels, show plans, answers, recap) is sent at once, tagged with
        the segment after which the browser may show it."""
        if self.collect is not None and item.kind in ("commentary", "crowd"):
            self.collect.append(item)
            return
        for vid in list(self.subscribers):
            if self.visible(item, vid):
                self._send(vid, {"event": "item", "data": self.serialize(item)})

    def _set_status(self, status: str) -> None:
        self.status = status
        for vid in list(self.subscribers):
            self._send(vid, {"event": "status", "data": {"status": status, "seq": self.seq}})

    # ---------- the director ----------
    def start(self) -> None:
        if self.status != "waiting":
            return
        self._set_status("live")
        threading.Thread(target=self._direct, daemon=True).start()

    def _slowest_seq(self) -> int:
        now = time.time()
        active = [p["seq"] for p in self.progress.values() if now - p["at"] < PROGRESS_TIMEOUT_S]
        return min(active) if active else self.seq

    def _direct(self) -> None:
        for start, batch in segments_of(self.events):
            # stay a little ahead of the viewers, never far: questions see what they saw
            while not self.stop_flag.is_set() and self.seq - self._slowest_seq() >= LOOKAHEAD:
                time.sleep(0.2)
            if self.stop_flag.is_set():
                return
            try:
                self._prepare_and_send(start, batch)
            except Exception as exc:          # noqa: BLE001 - the show must go on
                print(f"director error: {type(exc).__name__}: {exc}")
            if self.orch.half_time_due:
                self.orch.half_time_due = False
                self._set_status("half_time")
                try:
                    self.orch.half_time()      # analysis + show plans, shown during the break
                except Exception as exc:      # noqa: BLE001
                    print(f"half-time error: {type(exc).__name__}: {exc}")
                self._set_status("live")
        self._set_status("full_time")
        try:
            self.orch.full_time()
        except Exception as exc:              # noqa: BLE001
            print(f"full-time error: {type(exc).__name__}: {exc}")
        for vid in list(self.subscribers):
            self._send(vid, {"event": "metrics", "data": self.orch.supervisor.report()})

    def _prepare_and_send(self, start: int, batch: list[dict]) -> None:
        self.working_seq = self.seq + 1
        self.collect = []
        with self.orch.ctx_lock:
            self.orch.on_batch(batch)
        produced, self.collect = self.collect, None
        seq = self.seq + 1
        commentary = [it for it in produced if it.kind == "commentary"]
        crowd = next((it for it in produced if it.kind == "crowd"), None)
        # the voices, made now so they are ready before the segment is played
        if self.voice:
            list(self.voice_pool.map(lambda it: self.audio(str(it.id)), commentary))
        events, stats, last_shot = [], [], None
        for offset, e in enumerate(batch):
            idx = start + offset
            if e["type"] == "shot":
                last_shot = e
            if e["type"] in PITCH_TYPES:
                ev = _pitch_event(e, idx)
                if e["type"] == "goal" and last_shot is not None:
                    ev["shot_type"] = last_shot["details"].get("shot_type")
                    ev["body_part"] = last_shot["details"].get("body_part")
                events.append(ev)
            if e["type"] in STATS_AFTER or offset == len(batch) - 1:
                self.stats_ctx.seen = self.events[:idx + 1]
                stats.append({"idx": idx, "panel": self.stats_tools.match_stats_panel()})
        goal = next((ev["idx"] for ev in events if ev["type"] == "goal"), None)
        for vid in list(self.subscribers):
            line = next((it for it in commentary if self.visible(it, vid)), None)
            self._send(vid, {"event": "segment", "data": {
                "seq": seq, "events": events, "stats": stats, "goal_idx": goal,
                "commentary": self.serialize(line, seq) if line else None,
                "audio": f"{line.id}" if line and self.voice and self.audio_cache.get(str(line.id)) else None,
                "crowd": crowd.payload.get("cues", []) if crowd else [],
                "half_time": any(e["type"] == "period_end" and e["details"].get("period") == 1 for e in batch),
                "full_time": any(e["type"] == "match_end" for e in batch),
            }})
        self.seq = seq

    def stop(self) -> None:
        self.stop_flag.set()

    # ---------- viewer actions ----------
    def report_progress(self, vid: str, seq: int, idx: int) -> None:
        if vid in self.progress:
            self.progress[vid] = {"seq": seq, "idx": idx, "at": time.time()}

    def ask(self, vid: str, question: str) -> list[dict]:
        """A viewer question, answered with the match as this viewer has seen it so far."""
        seen_upto = self.progress.get(vid, {}).get("idx", 0) + 1
        with self.orch.ctx_lock:
            full = self.orch.ctx.seen
            rewind = 0 < seen_upto < len(full)
            if rewind:
                self.orch.ctx.seen = full[:seen_upto]
            try:
                items = self.orch.ask(vid, question)
            finally:
                if rewind:
                    self.orch.ctx.seen = full
        return [self.serialize(it, -1) for it in items]

    @staticmethod
    def spoken_text(item: BroadcastItem) -> str:
        """What the commentator says out loud. A goal is called in full and always starts
        with the goal call, so the voice says "GOAL" on the frame the goal is shown; an
        ordinary line is cut to its first sentence so the voice keeps pace with the match;
        the match report is introduced by its headline."""
        text = (item.payload.get("speech") or item.payload.get("text", "")).strip()
        if item.kind == "commentary" and item.payload.get("excitement", 2) >= 4:
            if not voice_mod.GOAL_WORD.match(text):
                text = "GOAL! " + text
            return text
        return re.split(r"(?<=[.!?])\s+", text, maxsplit=1)[0]

    def audio(self, key: str) -> bytes | None:
        """The commentator's voice for one item ("12") or the welcome ("intro-<viewer>")."""
        if not self.voice:
            return None
        with self.audio_lock:
            if key in self.audio_cache:
                return self.audio_cache[key]
        try:
            if key.startswith("intro-"):
                vid = key[6:]
                if vid not in self.viewers:
                    return None
                data = self.voice.speak(self.intro_text(vid), "English", 2)
            else:
                item = next((it for it in self.orch.timeline if str(it.id) == key), None)
                if not item or item.kind not in ("commentary", "recap"):
                    return None
                language = item.audience.split("/")[0] if "/" in item.audience else "English"
                excitement = item.payload.get("excitement", 2) if item.kind == "commentary" else 2
                data = self.voice.speak(self.spoken_text(item), language, excitement)
        except Exception as exc:              # noqa: BLE001 - no voice, the text is still on screen
            print(f"voice error: {type(exc).__name__}: {exc}")
            return None
        with self.audio_lock:
            self.audio_cache[key] = data
        return data
