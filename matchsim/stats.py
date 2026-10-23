"""Team-level box score computed from a match event list."""
from __future__ import annotations

from collections import defaultdict

TEAM_KEYS = ("passes", "passes_completed", "open_play_passes", "open_play_completed", "crosses",
             "progressive_passes", "shots", "shots_on_target", "xg", "goals", "big_chances", "tackles",
             "interceptions", "pressures", "fouls", "clearances", "dribbles", "dribbles_won", "carries",
             "yellow_cards", "red_cards", "corners", "offsides", "tactical_changes", "substitutions")
SET_PIECE_PASSES = ("throw_in", "goal_kick", "corner", "free_kick")


def team_stats(events: list[dict]) -> dict:
    start = next(e for e in events if e["type"] == "match_start")
    ids = [start["details"]["home"]["team"]["id"], start["details"]["away"]["team"]["id"]]
    s = {tid: defaultdict(float) for tid in ids}
    poss_time = defaultdict(float)
    prev = None
    for e in events:
        if prev is not None and e["period"] == prev["period"] and e["period"] in (1, 2):
            dt = e["match_seconds"] - prev["match_seconds"]
            if 0 < dt < 20:  # ball-in-play approximation
                poss_time[prev["possession_team_id"]] += dt
        prev = e
        tid = e["team_id"]
        if tid not in s:
            continue
        st, t, d = s[tid], e["type"], e["details"]
        if t == "pass":
            st["passes"] += 1
            st["passes_completed"] += e["outcome"] == "complete"
            if d.get("pass_type") not in SET_PIECE_PASSES:
                st["open_play_passes"] += 1
                st["open_play_completed"] += e["outcome"] == "complete"
            st["crosses"] += bool(d.get("cross"))
            st["corners"] += d.get("pass_type") == "corner"
            st["progressive_passes"] += bool(d.get("progressive"))
        elif t == "shot":
            st["shots"] += 1
            st["shots_on_target"] += d["on_target"]
            st["xg"] += d["xg"]
            st["goals"] += e["outcome"] == "Goal"
            st["big_chances"] += d["big_chance"]
        elif t == "duel" and d.get("duel_type") == "Tackle":
            st["tackles"] += 1
        elif t == "interception":
            st["interceptions"] += 1
        elif t == "pressure":
            st["pressures"] += 1
        elif t == "foul":
            st["fouls"] += 1
        elif t == "clearance":
            st["clearances"] += 1
        elif t == "dribble":
            st["dribbles"] += 1
            st["dribbles_won"] += e["outcome"] == "complete"
        elif t == "carry":
            st["carries"] += 1
        elif t == "card":
            st["yellow_cards" if e["outcome"] == "yellow" else "red_cards"] += 1
        elif t == "offside":
            st["offsides"] += 1
        elif t == "tactical_change":
            st["tactical_changes"] += 1
        elif t == "substitution":
            st["substitutions"] += 1
    total = sum(poss_time.values()) or 1
    out = {}
    for tid in ids:
        st = s[tid]
        for k in TEAM_KEYS:
            st[k] += 0
        st["possession_pct"] = 100 * poss_time[tid] / total
        st["pass_accuracy_pct"] = 100 * st["open_play_completed"] / max(1, st["open_play_passes"])
        out[tid] = {k: round(v, 2) for k, v in st.items()}
    out["_ball_in_play_min"] = round(total / 60, 1)
    return out
