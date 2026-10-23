"""Replay a simulated match as a live feed (match-clock paced)."""
from __future__ import annotations

import asyncio
import json
import sys
import time
from typing import AsyncIterator, Iterator


def _gaps(events: list[dict]):
    prev = None
    for e in events:
        gap = 0.0
        if prev is not None and e["period"] == prev["period"]:
            gap = max(0.0, e["match_seconds"] - prev["match_seconds"])
        elif prev is not None:
            gap = 3.0  # half-time break, compressed
        yield gap, e
        prev = e


def replay(events: list[dict], speed: float = 1.0) -> Iterator[dict]:
    """Blocking generator: yields events at `speed` x real time (speed=60 -> 90 min in 90 s)."""
    for gap, e in _gaps(events):
        if gap and speed > 0:
            time.sleep(gap / speed)
        yield e


async def areplay(events: list[dict], speed: float = 1.0) -> AsyncIterator[dict]:
    """Async version, ready to plug into an SSE / WebSocket endpoint."""
    for gap, e in _gaps(events):
        if gap and speed > 0:
            await asyncio.sleep(gap / speed)
        yield e


def print_feed(events: list[dict], speed: float, pretty: bool = False, out=sys.stdout):
    for e in replay(events, speed):
        if pretty:
            out.write(_line(e) + "\n")
        else:
            out.write(json.dumps(e, ensure_ascii=False) + "\n")
        out.flush()


ICONS = {"goal": "⚽", "shot": "🎯", "card": "🟨", "substitution": "🔁", "foul": "⛔", "tactical_change": "🧠",
         "period_start": "▶️", "period_end": "⏸️", "match_end": "🏁", "match_start": "📋", "injury": "🚑"}


def _line(e: dict) -> str:
    t = e["type"]
    sc = f"{e['score']['home']}-{e['score']['away']}"
    who = f"{e['player'] or ''} ({e['team'] or ''})" if e["player"] else ""
    extra = ""
    d = e["details"]
    if t == "shot":
        extra = (f"xG {d['xg']:.2f} ({d['assist_type']}, {d['body_part']}, {d['distance']:.0f}m, "
                 f"{d['n_defenders_in_cone']} in cone) -> {e['outcome']}")
    elif t == "pass":
        extra = f"{d['pass_type']} {d['length']:.0f}m -> {d.get('recipient') or ''} [{e['outcome']}]"
    elif t == "carry":
        extra = f"{d['length']:.0f}m @ {d['max_speed_kmh']:.0f} km/h"
    elif t == "substitution":
        extra = f"{d['player_off']} -> {d['player_on']} ({d['reason']})"
    elif t == "tactical_change":
        extra = d["description"]
    elif t == "card":
        extra = e["outcome"]
    elif t == "goal":
        extra = f"assist: {d['assist'] or '-'} | xG {d['xg']:.2f} | {d['game_state']}"
    elif t == "match_start":
        extra = f"{d['home']['team']['name']} ({d['home']['formation']}) vs {d['away']['team']['name']} ({d['away']['formation']}) @ {d['venue']}"
    elif t == "match_state":
        extra = f"possession {d['possession_pct']['home']}-{d['possession_pct']['away']} | xG {d['xg']['home']}-{d['xg']['away']} | momentum {d['momentum']}"
    elif t == "match_end":
        motm = d.get("player_of_the_match") or {}
        extra = f"FT {d['final_score']['home']}-{d['final_score']['away']} | xG {d['xg']['home']}-{d['xg']['away']} | MOTM {motm.get('player')} ({motm.get('rating')})"
    return f"{e['clock']} [{sc}] {ICONS.get(t, '·')} {t:<16} {who} {extra}".rstrip()
