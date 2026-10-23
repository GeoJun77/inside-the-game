"""Extract Premier League 2015/16 statistics from StatsBomb Open Data to calibrate matchsim.

Run from the repo root:
    python tools/calibrate_from_statsbomb.py

It downloads the 380 matches once (cached in data/statsbomb_cache/, ignored by git),
then writes matchsim/calibration_data.py: plain Python numbers only (formations,
tactical shifts, substitution timing, shot characteristics, freeze-frame and outcome
tables, match-level targets). The match engine reads those numbers, so the
synthetic data follows real Premier League distributions without redistributing
any StatsBomb data.

Data source: StatsBomb Open Data (https://github.com/statsbomb/open-data).
"""
from __future__ import annotations

import json
import math
import sys
import time
import warnings
from collections import Counter, defaultdict
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from xg.features import (gk_distance_to_goal, n_defenders_in_cone, nearest_defender_dist,  # noqa: E402
                         shot_angle, shot_distance)

warnings.filterwarnings("ignore")
CACHE = ROOT / "data" / "statsbomb_cache"
OUT = ROOT / "matchsim" / "calibration_data.py"
COMPETITION_ID, SEASON_ID = 2, 27

KEEP_TYPES = {"Shot", "Pass", "Starting XI", "Tactical Shift", "Substitution", "Foul Committed", "Bad Behaviour",
              "Pressure", "Duel", "Interception", "Dribble", "Carry", "Clearance", "Block", "Ball Recovery",
              "Goal Keeper"}
COLS = ["id", "match_id", "period", "minute", "second", "type", "team", "player", "position", "location",
        "under_pressure", "tactics", "pass_end_location", "pass_length", "pass_height", "pass_outcome",
        "pass_cross", "pass_cut_back", "pass_through_ball", "pass_type", "shot_body_part", "shot_type",
        "shot_technique", "shot_first_time", "shot_one_on_one", "shot_aerial_won", "shot_key_pass_id",
        "shot_freeze_frame", "shot_outcome", "shot_statsbomb_xg", "substitution_outcome",
        "foul_committed_card", "bad_behaviour_card", "duel_type", "dribble_outcome"]


# ----------------------------------------------------------------------- download
def load_events() -> tuple[pd.DataFrame, pd.DataFrame]:
    CACHE.mkdir(parents=True, exist_ok=True)
    ev_path, m_path = CACHE / "events.pkl", CACHE / "matches.pkl"
    if ev_path.exists() and m_path.exists():
        return pd.read_pickle(ev_path), pd.read_pickle(m_path)
    from statsbombpy import sb
    matches = sb.matches(competition_id=COMPETITION_ID, season_id=SEASON_ID)
    parts = []
    for k, mid in enumerate(matches["match_id"]):
        for _ in range(3):
            try:
                ev = sb.events(match_id=mid)
                break
            except Exception:
                time.sleep(3)
        else:
            raise RuntimeError(f"could not download match {mid}")
        ev = ev[ev["type"].isin(KEEP_TYPES)].reindex(columns=COLS)
        ev["match_id"] = mid
        parts.append(ev)
        if k % 50 == 0:
            print(f"downloaded {k}/{len(matches)} matches", flush=True)
    events = pd.concat(parts, ignore_index=True)
    events.to_pickle(ev_path)
    matches.to_pickle(m_path)
    return events, matches


def flag(series: pd.Series) -> pd.Series:
    return series.fillna(False).astype(bool)


def dist_band(d: float) -> str:
    return "0-12" if d < 12 else "12-18" if d < 18 else "18-25" if d < 25 else "25+"


def probs(series: pd.Series, digits: int = 4) -> dict:
    vc = series.value_counts(normalize=True)
    return {str(k): round(float(v), digits) for k, v in vc.items()}


# ------------------------------------------------------------------- formations
def formations(events: pd.DataFrame) -> tuple[dict, dict]:
    from matchsim.formations import POSITION_CODE  # noqa: WPS433

    xi = events[events["type"] == "Starting XI"]
    codes = xi["tactics"].apply(lambda t: str(t["formation"]))
    weights = {k: round(float(v), 4) for k, v in codes.value_counts(normalize=True).items()}
    slots = {}
    for code in weights:
        lineups = Counter()
        for t in xi.loc[codes == code, "tactics"]:
            lineups[tuple(POSITION_CODE[p["position"]["name"]] for p in t["lineup"])] += 1
        slots[code] = list(lineups.most_common(1)[0][0])
    return slots, weights


# ---------------------------------------------------------------- score timeline
def score_timeline(events: pd.DataFrame, matches: pd.DataFrame) -> dict:
    """match_id -> list of (minute, scoring team) for every goal (own goals ignored)."""
    goals = events[(events["type"] == "Shot") & (events["shot_outcome"] == "Goal")]
    out = defaultdict(list)
    for mid, minute, team in zip(goals["match_id"], goals["minute"], goals["team"]):
        out[mid].append((minute, team))
    return out


def state_at(goal_list, team, minute) -> int:
    diff = 0
    for m, t in goal_list:
        if m < minute:
            diff += 1 if t == team else -1
    return diff


def tactical_shifts(events, matches, timeline) -> dict:
    ts = events[events["type"] == "Tactical Shift"]
    xi = events[events["type"] == "Starting XI"]
    start_form = {(m, t): str(tac["formation"]) for m, t, tac in zip(xi["match_id"], xi["team"], xi["tactics"])}
    last_form = dict(start_form)
    transitions = Counter()
    by_state = Counter()
    minute_hist = Counter()
    for mid, team, minute, tac in sorted(zip(ts["match_id"], ts["team"], ts["minute"], ts["tactics"]),
                                         key=lambda r: (r[0], r[2])):
        new = str(tac["formation"])
        old = last_form.get((mid, team), new)
        if new != old:
            transitions[(old, new)] += 1
        last_form[(mid, team)] = new
        s = state_at(timeline.get(mid, []), team, minute)
        by_state["trailing" if s < 0 else "drawing" if s == 0 else "leading"] += 1
        minute_hist[min(90, int(minute) // 15 * 15)] += 1
    team_matches = 2 * len(matches)
    return {
        "per_team_match": round(len(ts) / team_matches, 3),
        "formation_change_share": round(sum(transitions.values()) / max(1, len(ts)), 3),
        "by_score_state": {k: round(v / len(ts), 3) for k, v in by_state.items()},
        "minute_buckets": {str(k): round(v / len(ts), 3) for k, v in sorted(minute_hist.items())},
        "top_transitions": [[a, b, n] for (a, b), n in transitions.most_common(25)],
    }


def substitutions(events, matches, timeline) -> dict:
    sub = events[events["type"] == "Substitution"].sort_values(["match_id", "team", "minute"])
    order_minutes = defaultdict(list)
    by_state = Counter()
    for (mid, team), g in sub.groupby(["match_id", "team"]):
        for k, minute in enumerate(g["minute"]):
            order_minutes[k + 1].append(int(minute))
            s = state_at(timeline.get(mid, []), team, minute)
            by_state["trailing" if s < 0 else "drawing" if s == 0 else "leading"] += 1
    return {
        "per_team_match": round(len(sub) / (2 * len(matches)), 3),
        "minute_by_order": {str(k): [int(np.percentile(v, q)) for q in (10, 25, 50, 75, 90)]
                            for k, v in sorted(order_minutes.items()) if len(v) > 30},
        "by_score_state": {k: round(v / len(sub), 3) for k, v in by_state.items()},
        "injury_share_before_45": round(float((sub["minute"] < 45).mean()), 3),
    }


# ------------------------------------------------------------------------- shots
def shot_table(events: pd.DataFrame) -> pd.DataFrame:
    shots = events[events["type"] == "Shot"].copy()
    passes = events[events["type"] == "Pass"].set_index("id")
    kp = passes.reindex(shots["shot_key_pass_id"])
    kp.index = shots.index

    def atype(row, k):
        if pd.isna(row["shot_key_pass_id"]):
            return "no_assist"
        if k["pass_type"] in ("Corner", "Free Kick", "Throw-in"):
            return "set_piece"
        if k["pass_through_ball"] is True:
            return "through_ball"
        if k["pass_cut_back"] is True:
            return "cut_back"
        if k["pass_cross"] is True:
            return "cross"
        if k["pass_height"] == "High Pass":
            return "high_pass"
        return "ground_pass"

    shots["assist_type"] = [atype(r, k) for (_, r), (_, k) in zip(shots.iterrows(), kp.iterrows())]
    shots["x"] = shots["location"].str[0]
    shots["y"] = shots["location"].str[1]
    shots["distance"] = [shot_distance(x, y) for x, y in zip(shots["x"], shots["y"])]
    shots["angle"] = [shot_angle(x, y) for x, y in zip(shots["x"], shots["y"])]
    shots["nearest_defender_dist"] = [nearest_defender_dist(x, y, f) for x, y, f in
                                      zip(shots["x"], shots["y"], shots["shot_freeze_frame"])]
    shots["n_defenders_in_cone"] = [n_defenders_in_cone(x, y, f) for x, y, f in
                                    zip(shots["x"], shots["y"], shots["shot_freeze_frame"])]
    shots["gk_distance_to_goal"] = [gk_distance_to_goal(f) for f in shots["shot_freeze_frame"]]
    for c in ("under_pressure", "shot_first_time", "shot_one_on_one", "shot_aerial_won"):
        shots[c] = flag(shots[c])
    shots["band"] = shots["distance"].apply(dist_band)
    shots["foot_or_head"] = np.where(shots["shot_body_part"] == "Head", "head", "foot")
    return shots


def shot_characteristics(shots: pd.DataFrame) -> dict:
    op = shots[shots["shot_type"] != "Penalty"]
    out = {
        "assist_type": probs(op["assist_type"]),
        "shot_type": probs(shots["shot_type"]),
        "distance_quantiles": [round(float(np.percentile(op["distance"], q)), 1) for q in (10, 25, 50, 75, 90)],
        "by_assist": {},
    }
    for at, g in op.groupby("assist_type"):
        entry = {"n": int(len(g)), "band": probs(g["band"]), "by_band": {}}
        for band, gb in g.groupby("band"):
            if len(gb) < 15:
                continue
            foot = gb[gb["shot_body_part"] != "Head"]
            head = gb[gb["shot_body_part"] == "Head"]
            entry["by_band"][band] = {
                "n": int(len(gb)),
                "head": round(float((gb["shot_body_part"] == "Head").mean()), 4),
                "technique_foot": probs(foot["shot_technique"]) if len(foot) else {"Normal": 1.0},
                "technique_head": probs(head["shot_technique"]) if len(head) else {"Normal": 1.0},
                "first_time_head": round(float(head["shot_first_time"].mean()), 4) if len(head) else 0.0,
                "first_time_foot": round(float(foot["shot_first_time"].mean()), 4) if len(foot) else 0.0,
                "aerial_won_head": round(float(head["shot_aerial_won"].mean()), 4) if len(head) else 0.0,
                "one_on_one": round(float(gb["shot_one_on_one"].mean()), 4),
                "under_pressure": round(float(gb["under_pressure"].mean()), 4),
            }
        out["by_assist"][at] = entry
    # lateral offset |y - 40| of shots by assist type and distance band (shot geometry)
    out["lateral_q"] = {}
    for (at, band), g in op.groupby(["assist_type", "band"]):
        if len(g) >= 25:
            out["lateral_q"][f"{at}|{band}"] = [round(float(np.percentile((g["y"] - 40).abs(), q)), 2)
                                                for q in (5, 25, 50, 75, 95)]
    for band, g in op.groupby("band"):
        out["lateral_q"][f"any|{band}"] = [round(float(np.percentile((g["y"] - 40).abs(), q)), 2)
                                          for q in (5, 25, 50, 75, 95)]
    # distance within each band, by assist type
    out["distance_q"] = {}
    for (at, band), g in op.groupby(["assist_type", "band"]):
        if len(g) >= 25:
            out["distance_q"][f"{at}|{band}"] = [round(float(np.percentile(g["distance"], q)), 2)
                                                 for q in (5, 25, 50, 75, 95)]
    for band, g in op.groupby("band"):
        out["distance_q"][f"any|{band}"] = [round(float(np.percentile(g["distance"], q)), 2)
                                           for q in (5, 25, 50, 75, 95)]
    return out


def freeze_frame_targets(shots: pd.DataFrame) -> dict:
    op = shots[(shots["shot_type"] != "Penalty")].dropna(subset=["gk_distance_to_goal"])
    out = {"overall": {}, "by_assist": {}, "by_band": {}}

    def summarise(g):
        cone = g["n_defenders_in_cone"].astype(int).clip(upper=4)
        return {
            "n": int(len(g)),
            "cone": {str(k): round(float(v), 4) for k, v in cone.value_counts(normalize=True).sort_index().items()},
            "nearest_q": [round(float(np.percentile(g["nearest_defender_dist"], q)), 2) for q in (10, 25, 50, 75, 90)],
            "gk_q": [round(float(np.percentile(g["gk_distance_to_goal"], q)), 2) for q in (10, 25, 50, 75, 90)],
        }

    out["overall"] = summarise(op)
    # joint tables used by the synthetic freeze-frame generator
    cone = op["n_defenders_in_cone"].astype(int).clip(upper=4)
    out["cone_by_assist_band"] = {}
    for (at, b), g in op.assign(cone=cone).groupby(["assist_type", "band"]):
        if len(g) >= 25:
            out["cone_by_assist_band"][f"{at}|{b}"] = {
                str(k): round(float(v), 4) for k, v in g["cone"].value_counts(normalize=True).sort_index().items()}
    out["nearest_q_by_pressure_band"] = {}
    out["gk_q_by_band"] = {}
    for (pr, b), g in op.groupby(["under_pressure", "band"]):
        out["nearest_q_by_pressure_band"][f"{bool(pr)}|{b}"] = [
            round(float(np.percentile(g["nearest_defender_dist"], q)), 2) for q in (5, 25, 50, 75, 95)]
    for (oo, b), g in op.groupby(["shot_one_on_one", "band"]):
        if len(g) >= 20:
            out["gk_q_by_band"][f"{bool(oo)}|{b}"] = [
                round(float(np.percentile(g["gk_distance_to_goal"], q)), 2) for q in (5, 25, 50, 75, 95)]
    for at, g in op.groupby("assist_type"):
        out["by_assist"][at] = summarise(g)
    for b, g in op.groupby("band"):
        out["by_band"][b] = summarise(g)
    pressured = op[op["under_pressure"]]
    out["nearest_q_under_pressure"] = [round(float(np.percentile(pressured["nearest_defender_dist"], q)), 2)
                                       for q in (10, 25, 50, 75, 90)]
    free = op[~op["under_pressure"]]
    out["nearest_q_free"] = [round(float(np.percentile(free["nearest_defender_dist"], q)), 2)
                             for q in (10, 25, 50, 75, 90)]
    one = op[op["shot_one_on_one"]]
    out["gk_q_one_on_one"] = [round(float(np.percentile(one["gk_distance_to_goal"], q)), 2)
                              for q in (10, 25, 50, 75, 90)]
    return out


def outcome_tables(shots: pd.DataFrame) -> dict:
    """P(outcome | not a goal, situation): used once the xG model has decided it is not a goal."""
    ng = shots[(shots["shot_outcome"] != "Goal") & (shots["shot_type"] != "Penalty")].dropna(subset=["n_defenders_in_cone"])
    ng = ng.assign(cone=ng["n_defenders_in_cone"].astype(int).clip(upper=2).astype(str))
    table = {}
    for (fh, band, cone), g in ng.groupby(["foot_or_head", "band", "cone"]):
        if len(g) >= 20:
            table[f"{fh}|{band}|{cone}"] = probs(g["shot_outcome"])
    pens = shots[shots["shot_type"] == "Penalty"]
    return {
        "non_goal": table,
        "non_goal_fallback": probs(ng["shot_outcome"]),
        "penalty_conversion": round(float((pens["shot_outcome"] == "Goal").mean()), 3),
        "penalty_non_goal": probs(pens.loc[pens["shot_outcome"] != "Goal", "shot_outcome"]),
    }


# --------------------------------------------------------------- match targets
def match_targets(events: pd.DataFrame, shots: pd.DataFrame, matches: pd.DataFrame) -> dict:
    g = events.groupby(["match_id", "team"])
    passes = events[events["type"] == "Pass"]
    open_passes = passes[~passes["pass_type"].isin(["Throw-in", "Goal Kick", "Kick Off", "Corner", "Free Kick"])]
    per = pd.DataFrame({
        "passes": passes.groupby(["match_id", "team"]).size(),
        "pass_accuracy": open_passes.groupby(["match_id", "team"])["pass_outcome"].apply(lambda s: s.isna().mean() * 100),
        "shots": shots.groupby(["match_id", "team"]).size(),
        "shots_on_target": shots[shots["shot_outcome"].isin(["Goal", "Saved", "Saved to Post"])]
        .groupby(["match_id", "team"]).size(),
        "goals": shots[shots["shot_outcome"] == "Goal"].groupby(["match_id", "team"]).size(),
        "xg_statsbomb": shots.groupby(["match_id", "team"])["shot_statsbomb_xg"].sum(),
        "corners": passes[passes["pass_type"] == "Corner"].groupby(["match_id", "team"]).size(),
        "fouls": events[events["type"] == "Foul Committed"].groupby(["match_id", "team"]).size(),
        "yellow_cards": events[(events["foul_committed_card"].isin(["Yellow Card"]))
                               | (events["bad_behaviour_card"].isin(["Yellow Card"]))].groupby(["match_id", "team"]).size(),
        "pressures": events[events["type"] == "Pressure"].groupby(["match_id", "team"]).size(),
        "tackles": events[(events["type"] == "Duel") & (events["duel_type"] == "Tackle")].groupby(["match_id", "team"]).size(),
        "interceptions": events[events["type"] == "Interception"].groupby(["match_id", "team"]).size(),
        "dribbles": events[events["type"] == "Dribble"].groupby(["match_id", "team"]).size(),
        "crosses": passes[flag(passes["pass_cross"])].groupby(["match_id", "team"]).size(),
        "tactical_shifts": events[events["type"] == "Tactical Shift"].groupby(["match_id", "team"]).size(),
        "substitutions": events[events["type"] == "Substitution"].groupby(["match_id", "team"]).size(),
    }).fillna(0)
    res = matches.assign(
        r=np.where(matches["home_score"] > matches["away_score"], "H",
                   np.where(matches["home_score"] == matches["away_score"], "D", "A")))
    targets = {k: round(float(v), 2) for k, v in per.mean().items()}
    targets["home_draw_away_pct"] = {k: round(float(v) * 100, 1) for k, v in res["r"].value_counts(normalize=True).items()}
    targets["goals_per_match"] = round(float((matches["home_score"] + matches["away_score"]).mean()), 2)
    return targets


# --------------------------------------------------------------------- writer
def xg_reference(shots: pd.DataFrame) -> dict:
    """Frequencies of each model input on real non-penalty shots: the 'typical shot' used
    as reference when explaining an xG value feature by feature."""
    op = shots[shots["shot_type"] != "Penalty"]
    return {
        "categorical": {c: probs(op[c]) for c in ("shot_body_part", "shot_type", "shot_technique", "assist_type")},
        "boolean": {c: round(float(op[c].mean()), 4)
                    for c in ("under_pressure", "shot_first_time", "shot_one_on_one", "shot_aerial_won")},
    }


def write_xg_reference(ref: dict) -> None:
    path = ROOT / "xg" / "reference.py"
    text = ('"""Typical-shot reference for xG explanations. GENERATED by tools/calibrate_from_statsbomb.py."""\n\n'
            f"REFERENCE = {json.dumps(ref, indent=1, ensure_ascii=False)}\n")
    path.write_text(text, encoding="utf-8")
    print(f"wrote {path.relative_to(ROOT)}")


def write_module(payload: dict) -> None:
    lines = [
        '"""Premier League 2015/16 calibration data. GENERATED, do not edit by hand.',
        "",
        "Produced by tools/calibrate_from_statsbomb.py from StatsBomb Open Data",
        "(https://github.com/statsbomb/open-data). Aggregated statistics only, no raw events.",
        '"""',
        "",
    ]
    for name, value in payload.items():
        lines.append(f"{name} = {json.dumps(value, indent=1, ensure_ascii=False)}")
        lines.append("")
    text = "\n".join(lines).replace(": true", ": True").replace(": false", ": False").replace(": null", ": None")
    OUT.write_text(text, encoding="utf-8")
    print(f"wrote {OUT.relative_to(ROOT)}")


def main() -> None:
    events, matches = load_events()
    print(f"{len(matches)} matches, {len(events)} events")
    slots, weights = formations(events)
    timeline = score_timeline(events, matches)
    shots = shot_table(events)
    payload = {
        "SOURCE": "StatsBomb Open Data - Premier League 2015/16 (380 matches)",
        "FORMATIONS": slots,
        "FORMATION_WEIGHTS": weights,
        "TACTICAL_SHIFTS": tactical_shifts(events, matches, timeline),
        "SUBSTITUTIONS": substitutions(events, matches, timeline),
        "SHOTS": shot_characteristics(shots),
        "FREEZE_FRAME_TARGETS": freeze_frame_targets(shots),
        "OUTCOMES": outcome_tables(shots),
        "MATCH_TARGETS": match_targets(events, shots, matches),
    }
    write_module(payload)
    write_xg_reference(xg_reference(shots))


if __name__ == "__main__":
    main()
