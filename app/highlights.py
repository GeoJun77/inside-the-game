"""Match highlights at real football speed, the way a football manager game shows a match.

The pitch never speeds the ball or the players up: a 30 m pass takes about two seconds,
a player runs at most about 8.5 m/s. Ninety minutes at that speed last far longer than a
broadcast, so the time is saved by choosing WHAT to show, not by playing it faster:

- always shown: kick-offs, set pieces, shots, saves, fouls, cards, offsides, changes;
- each possession shows its last moments, longer the more dangerous it was (a move that
  ends in a shot shows its whole build-up, sideways passing in a team's own half shows
  next to nothing);
- between two shown moves the picture cuts, like a TV edit.

How long each move lasts on screen is computed here with the same timing as the browser
(app/static/app.js, paceGap), and the length of the moves is tuned so the whole match fits
the pace the viewer chose.
"""
from __future__ import annotations

import math

# what the pitch animates (the others only feed the stats and the agents)
PITCH_TYPES = {"pass", "carry", "shot", "dribble", "duel", "interception", "foul", "card", "goal",
               "substitution", "period_start", "period_end", "kick_off", "goalkeeper", "offside",
               "clearance", "block", "ball_recovery", "tactical_change", "injury", "match_end", "pressure"}

ALWAYS = {"shot", "goal", "foul", "card", "offside", "substitution", "tactical_change", "injury",
          "period_start", "period_end", "kick_off", "match_end", "goalkeeper", "block"}
ALWAYS_PASSES = {"corner", "free_kick"}

# ball speeds on screen, metres per second (averaged over the flight, as the ball slows down)
BALL_SPEED = {"ground": 15.0, "high": 18.0, "cross": 19.0, "shot": 26.0, "clearance": 20.0}
CARRY_SPEED = 5.0              # running with the ball
CONTROL = 0.3                  # time to control the ball before the next action
CUT = 0.9                      # a cut between two moves (fade out, fade in)
SET_PIECE_LEAD = {"corner": 3.8, "free kick": 3.8, "penalty": 3.8, "kickoff": 6.0}

MIN_MOVE = 3.0                 # a move shorter than this on screen is not worth a cut

# seconds of play on screen for the whole match, at pace 1 (the others divide it)
PLAY_SECONDS = 660.0           # extended highlights (pace 2)
KEY_MOMENTS_SECONDS = 290.0    # key moments only (pace 3)


def _dist(a, b) -> float:
    return math.hypot(b[0] - a[0], b[1] - a[1]) if a and b else 0.0


def flight(e: dict) -> float:
    """Seconds the ball (or the ball carrier) needs for this action."""
    t, d = e["type"], e.get("details") or {}
    length = _dist(e.get("location_abs"), e.get("end_location_abs"))
    if t == "pass":
        kind = "cross" if d.get("cross") or d.get("pass_type") == "cross" else \
            "ground" if d.get("height") in (None, "Ground Pass") else "high"
        return max(0.35, length / BALL_SPEED[kind])
    if t == "shot":
        return max(0.3, length / BALL_SPEED["shot"])
    if t == "clearance":
        return max(0.4, length / BALL_SPEED["clearance"])
    if t == "carry":
        return max(0.6, length / CARRY_SPEED)
    if t == "dribble":
        return 0.9
    return 0.2


def set_piece(e: dict) -> str | None:
    d = e.get("details") or {}
    if e["type"] == "pass" and d.get("pass_type") == "corner":
        return "corner"
    if e["type"] == "pass" and d.get("pass_type") == "free_kick":
        return "free kick"
    if e["type"] == "shot" and d.get("shot_type") == "Penalty":
        return "penalty"
    if e["type"] == "shot" and d.get("shot_type") == "Free Kick":
        return "free kick"
    if e["type"] == "kick_off":
        return "kickoff"
    return None


def gap(prev: dict, e: dict, cut: bool = False) -> float:
    """Seconds on screen between two shown events. Mirrors paceGap in app.js."""
    if e["type"] == "pressure":
        return 0.05
    if prev["period"] != e["period"]:
        return 1.0
    d = max(0.0, e["match_seconds"] - prev["match_seconds"])
    if cut:
        g = CUT
    elif d > 20:
        g = min(2.2, 0.8 + (d - 20) / 50)                    # a stoppage: skip most of it
    else:
        g = max(0.45, flight(prev) + CONTROL)
    if prev["type"] == "pass" and prev["outcome"] == "offside":
        g += 1.4                                              # time to see the offside line
    if e["type"] == "pass" and e["outcome"] == "offside":
        g = max(g, 2.6)
    if e["type"] == "foul":
        g = max(g, 1.0)                                       # time to close him down
    sp = set_piece(e)
    if sp:
        g = max(g, SET_PIECE_LEAD[sp] + 0.4)
    return g


def _always(e: dict) -> bool:
    d = e.get("details") or {}
    return e["type"] in ALWAYS or d.get("pass_type") in ALWAYS_PASSES or e["outcome"] == "offside"


def _danger(events: list[dict], idxs: list[int]) -> float:
    """How much of a possession deserves to be seen: the further it got, the more."""
    team = events[idxs[0]]["possession_team_id"]
    best = 0.0
    for i in idxs:
        e = events[i]
        if e["type"] == "shot" and e["team_id"] == team:
            return 3.0
        if e["team_id"] == team and e.get("location"):
            best = max(best, e["location"][0])
            if e.get("end_location") and e["type"] in ("pass", "carry") and e["outcome"] == "complete":
                best = max(best, e["end_location"][0])
    return 2.2 if best >= 102 else 1.6 if best >= 80 else 1.0 if best >= 60 else 0.3


def screen_seconds(events: list[dict], hidden: set[int]) -> float:
    """Length of the shown match on screen, with the browser's timing."""
    total, prev, cut = 0.0, None, False
    for i, e in enumerate(events):
        if e["type"] not in PITCH_TYPES:
            continue
        if i in hidden:
            cut = prev is not None
            continue
        if prev is not None:
            total += gap(prev, e, cut)
        if e["type"] != "pressure":
            prev, cut = e, False
    return total


def _choose(events: list[dict], possessions: list[tuple[float, list[int]]], seconds_per_unit: float) -> set[int]:
    hidden: set[int] = set()
    for danger, idxs in possessions:
        budget = seconds_per_unit * danger
        keeping = budget >= MIN_MOVE                         # too short to read: not shown at all
        shown = [i for i in idxs if events[i]["type"] in PITCH_TYPES]
        # walk back from the end of the move: its last moments are kept, the rest is cut
        for k in range(len(shown) - 1, -1, -1):
            i = shown[k]
            e = events[i]
            if _always(e):
                continue
            if keeping and k > 0:
                budget -= gap(events[shown[k - 1]], e)
                keeping = budget > 0
            if not keeping:
                hidden.add(i)
    return hidden


def target_seconds(speed: float) -> float | None:
    """Seconds of play on screen for a pace: 1 = the whole match (no cut), 2 = extended
    highlights, 3 = key moments only."""
    if speed <= 1.0:
        return None
    return PLAY_SECONDS if speed < 2.5 else KEY_MOMENTS_SECONDS


def condensed(events: list[dict], speed: float = 1.0) -> set[int]:
    """The indices of the events the pitch does not show (the stats still count them).
    Pace 1 shows the whole match, every action, at real speed: nothing is hidden."""
    target = target_seconds(speed)
    if target is None:
        return set()
    by_possession: dict = {}
    for i, e in enumerate(events):
        by_possession.setdefault(e["possession_id"], []).append(i)
    possessions = [(_danger(events, idxs), idxs) for idxs in by_possession.values()]
    lo, hi = 0.0, 40.0
    best = _choose(events, possessions, lo)
    for _ in range(18):                                      # longest moves that still fit
        mid = (lo + hi) / 2
        hidden = _choose(events, possessions, mid)
        if screen_seconds(events, hidden) <= target:
            lo, best = mid, hidden
        else:
            hi = mid
    return best
