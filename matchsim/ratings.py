"""Per-player match statistics and ratings (0-10), computed from the event list.

The rating starts at 6.0 and moves with the player's contribution: goals, assists,
chance creation (xG, xA, key passes), passing volume and accuracy, dribbles,
defensive actions, goalkeeping (saves, goals prevented vs xG), discipline, goals
conceded for defenders and the team result. Players with few minutes are pulled
towards 6.0, like broadcast player ratings.
"""
from __future__ import annotations

from collections import defaultdict

DEFENSIVE_SLOTS = {"GK", "RB", "LB", "RCB", "CB", "LCB", "RWB", "LWB"}


def _new(pid, name, team_id, slot):
    return {"player_id": pid, "player": name, "team_id": team_id, "slot": slot, "minutes": 0,
            "goals": 0, "assists": 0, "shots": 0, "shots_on_target": 0, "xg": 0.0, "xa": 0.0,
            "key_passes": 0, "passes": 0, "passes_completed": 0, "progressive_passes": 0,
            "dribbles_won": 0, "dribbles_lost": 0, "tackles": 0, "interceptions": 0, "recoveries": 0,
            "clearances": 0, "blocks": 0, "pressures": 0, "fouls": 0, "yellow_cards": 0, "red_cards": 0,
            "saves": 0, "xg_faced_on_target": 0.0, "goals_conceded": 0, "rating": 6.0}


def _on_pitch_intervals(events):
    """player id -> list of [start_s, end_s] intervals on the pitch, plus slot and team."""
    start = next(e for e in events if e["type"] == "match_start")
    end_s = max(e["match_seconds"] for e in events)
    info, intervals = {}, defaultdict(list)
    for side in ("home", "away"):
        team_id = start["details"][side]["team"]["id"]
        for p in start["details"][side]["starting_xi"]:
            info[p["id"]] = (p["name"], team_id, p["slot"])
            intervals[p["id"]].append([0.0, end_s])
        for p in start["details"][side]["bench"]:
            info[p["id"]] = (p["name"], team_id, p["position"])
    for e in events:
        if e["type"] == "substitution":
            d = e["details"]
            if intervals[d["player_off_id"]]:
                intervals[d["player_off_id"]][-1][1] = e["match_seconds"]
            intervals[d["player_on_id"]].append([e["match_seconds"], end_s])
            name, team_id, _ = info[d["player_on_id"]]
            info[d["player_on_id"]] = (name, team_id, d["slot"])
        elif e["type"] == "card" and e["outcome"] in ("red", "second_yellow") and intervals[e["player_id"]]:
            intervals[e["player_id"]][-1][1] = e["match_seconds"]
    return info, intervals, end_s


def player_match_stats(events: list[dict]) -> dict:
    if not any(e["type"] == "match_start" for e in events):
        return {}
    info, intervals, end_s = _on_pitch_intervals(events)
    stats = {pid: _new(pid, *info[pid]) for pid in intervals}
    by_id = {e["event_id"]: e for e in events}
    final = events[-1]["score"]
    start = next(e for e in events if e["type"] == "match_start")
    home_id = start["details"]["home"]["team"]["id"]

    for pid, ivs in intervals.items():
        stats[pid]["minutes"] = round(sum(b - a for a, b in ivs) / 60)

    for e in events:
        pid, t = e["player_id"], e["type"]
        s = stats.get(pid)
        if t == "pass" and s:
            s["passes"] += 1
            s["passes_completed"] += e["outcome"] == "complete"
            s["progressive_passes"] += bool(e["details"].get("progressive")) and e["outcome"] == "complete"
        elif t == "shot" and s:
            d = e["details"]
            s["shots"] += 1
            s["shots_on_target"] += d["on_target"]
            s["goals"] += e["outcome"] == "Goal"
            s["xg"] += d["xg"]
            kp = d.get("key_pass_id")
            if kp and by_id[kp]["player_id"] in stats:
                k = stats[by_id[kp]["player_id"]]
                k["key_passes"] += 1
                k["xa"] += d["xg"]
                k["assists"] += e["outcome"] == "Goal"
            # goals conceded / saves for the defending side
            if e["outcome"] == "Goal":
                for opid, ivs in intervals.items():
                    if stats[opid]["team_id"] != e["team_id"] and any(a <= e["match_seconds"] <= b for a, b in ivs):
                        stats[opid]["goals_conceded"] += 1
            gk = d.get("goalkeeper_id")
            if gk in stats and d["on_target"]:
                stats[gk]["xg_faced_on_target"] += d["xg"]
        elif t == "goalkeeper" and s and e["outcome"] == "save":
            s["saves"] += 1
        elif t == "dribble" and s:
            s["dribbles_won" if e["outcome"] == "complete" else "dribbles_lost"] += 1
        elif t == "duel" and s and e["details"].get("duel_type") == "Tackle":
            s["tackles"] += 1
        elif t == "interception" and s:
            s["interceptions"] += 1
        elif t == "ball_recovery" and s:
            s["recoveries"] += 1
        elif t == "clearance" and s:
            s["clearances"] += 1
        elif t == "block" and s:
            s["blocks"] += 1
        elif t == "pressure" and s:
            s["pressures"] += 1
        elif t == "foul" and s:
            s["fouls"] += 1
        elif t == "card" and s:
            s["yellow_cards" if e["outcome"] == "yellow" else "red_cards"] += 1

    for s in stats.values():
        if s["minutes"] == 0:
            continue
        home = s["team_id"] == home_id
        gf, ga = (final["home"], final["away"]) if home else (final["away"], final["home"])
        r = 6.0
        r += 0.7 * s["goals"] + 0.5 * s["assists"] + 0.1 * s["key_passes"] + 0.3 * s["xg"] + 0.25 * s["xa"]
        r += max(-0.4, min(0.4, (s["passes_completed"] - 0.8 * s["passes"]) * 0.02))
        r += 0.003 * s["passes_completed"] + 0.02 * s["progressive_passes"]
        r += 0.10 * s["dribbles_won"] - 0.03 * s["dribbles_lost"]
        r += 0.12 * s["tackles"] + 0.12 * s["interceptions"] + 0.05 * s["clearances"] + 0.10 * s["blocks"]
        r += 0.02 * s["recoveries"]
        if s["slot"] == "GK":
            r += 0.25 * s["saves"] + 0.5 * (s["xg_faced_on_target"] - s["goals_conceded"])
        if s["slot"] in DEFENSIVE_SLOTS:
            r -= 0.25 * s["goals_conceded"]
            if s["goals_conceded"] == 0 and s["minutes"] >= 60:
                r += 0.7 if s["slot"] == "GK" else 0.4
        r -= 0.3 * s["yellow_cards"] + 1.5 * s["red_cards"] + 0.05 * s["fouls"]
        r += 0.3 if gf > ga else (-0.2 if gf < ga else 0.0)
        weight = min(1.0, s["minutes"] / 30)
        s["rating"] = round(max(3.0, min(10.0, 6.0 + (r - 6.0) * weight)), 1)
        s["xg"] = round(s["xg"], 2)
        s["xa"] = round(s["xa"], 2)
        s["xg_faced_on_target"] = round(s["xg_faced_on_target"], 2)
    return {pid: s for pid, s in stats.items() if s["minutes"] > 0}
