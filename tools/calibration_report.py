"""Compare synthetic matches with real Premier League 2015/16 statistics.

    python tools/calibration_report.py 200            # prints the comparison
    python tools/calibration_report.py 200 --md docs/calibration_report.md

Real figures come from matchsim/calibration_data.py (StatsBomb Open Data).
"""
from __future__ import annotations

import argparse
import random
import statistics as st
import sys
import warnings
from collections import Counter
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
warnings.filterwarnings("ignore")

from matchsim import build_league, simulate_match, team_stats  # noqa: E402
from matchsim import calibration_data as cal  # noqa: E402
from matchsim.freeze import dist_band  # noqa: E402

MATCH_KEYS = [("passes", "passes"), ("pass_accuracy_pct", "pass_accuracy"), ("shots", "shots"),
              ("shots_on_target", "shots_on_target"), ("goals", "goals"), ("xg", "xg_statsbomb"),
              ("corners", "corners"), ("fouls", "fouls"), ("yellow_cards", "yellow_cards"),
              ("pressures", "pressures"), ("tackles", "tackles"), ("interceptions", "interceptions"),
              ("dribbles", "dribbles"), ("crosses", "crosses"), ("tactical_changes", "tactical_shifts")]


def run(n: int, seed: int = 1):
    league = build_league()
    rng = random.Random(seed)
    team_rows, shots, results, formations = [], [], Counter(), Counter()
    bip = []
    for k in range(n):
        h, a = rng.sample(league, 2)
        ev = simulate_match(h, a, seed=k)
        s = team_stats(ev)
        bip.append(s["_ball_in_play_min"])
        team_rows += [s[h.id], s[a.id]]
        fs = ev[-1]["details"]["final_score"]
        results["H" if fs["home"] > fs["away"] else "D" if fs["home"] == fs["away"] else "A"] += 1
        start = ev[0]["details"]
        formations[start["home"]["formation"]] += 1
        formations[start["away"]["formation"]] += 1
        shots += [e for e in ev if e["type"] == "shot"]
    return team_rows, shots, results, formations, bip


def report(n: int) -> str:
    rows, shots, results, formations, bip = run(n)
    T = cal.MATCH_TARGETS
    out = [f"# Calibration report: {n} synthetic matches vs Premier League 2015/16 (StatsBomb)", "",
           "## Per team per match", "", "| Metric | Synthetic | Real PL |", "|---|---|---|"]
    for k, rk in MATCH_KEYS:
        out.append(f"| {k} | {st.mean(r[k] for r in rows):.2f} | {T[rk]:.2f} |")
    out.append(f"| ball in play (min / match) | {st.mean(bip):.1f} | ~55 |")
    tot = sum(results.values())
    real = T["home_draw_away_pct"]
    out.append(f"| home / draw / away % | {100 * results['H'] / tot:.0f} / {100 * results['D'] / tot:.0f} / "
               f"{100 * results['A'] / tot:.0f} | {real['H']:.0f} / {real['D']:.0f} / {real['A']:.0f} |")
    goals = sum(r["goals"] for r in rows)
    xg = sum(r["xg"] for r in rows)
    out.append(f"| total goals vs total xG | {goals:.0f} vs {xg:.1f} | |")

    op = [s for s in shots if s["details"]["shot_type"] != "Penalty"]
    out += ["", "## Shots (non-penalty)", "", "| Metric | Synthetic | Real PL |", "|---|---|---|"]
    syn_assist = Counter(s["details"]["assist_type"] for s in op)
    for at, p in cal.SHOTS["assist_type"].items():
        out.append(f"| assist: {at} | {100 * syn_assist[at] / len(op):.1f}% | {100 * p:.1f}% |")
    q = np.percentile([s["details"]["distance"] for s in op], [10, 25, 50, 75, 90]).round(1).tolist()
    out.append(f"| distance quantiles 10/25/50/75/90 | {q} | {cal.SHOTS['distance_quantiles']} |")
    head = sum(s["details"]["body_part"] == "Head" for s in op) / len(op)
    out.append(f"| headers | {100 * head:.1f}% | 16.2% |")
    ff = cal.FREEZE_FRAME_TARGETS["overall"]
    cone = Counter(min(4, s["details"]["n_defenders_in_cone"]) for s in op)
    out.append("| defenders in cone 0/1/2/3/4+ | " + " / ".join(f"{100 * cone[k] / len(op):.0f}" for k in range(5))
               + " | " + " / ".join(f"{100 * ff['cone'].get(str(k), 0):.0f}" for k in range(5)) + " |")
    nq = np.percentile([s["details"]["nearest_defender_dist"] for s in op], [10, 25, 50, 75, 90]).round(2).tolist()
    out.append(f"| nearest defender quantiles | {nq} | {ff['nearest_q']} |")
    gq = np.percentile([s["details"]["gk_distance_to_goal"] for s in op if s["details"]["gk_distance_to_goal"] is not None],
                       [10, 25, 50, 75, 90]).round(2).tolist()
    out.append(f"| goalkeeper distance quantiles | {gq} | {ff['gk_q']} |")
    outcomes = Counter(s["outcome"] for s in op)
    real_out = {"Goal": 0.093}
    ng = cal.OUTCOMES["non_goal_fallback"]
    for k, v in ng.items():
        real_out[k] = v * (1 - 0.093)
    for k in ("Goal", "Off T", "Blocked", "Saved", "Wayward", "Post"):
        out.append(f"| outcome {k} | {100 * outcomes[k] / len(op):.1f}% | {100 * real_out.get(k, 0):.1f}% |")
    pens = [s for s in shots if s["details"]["shot_type"] == "Penalty"]
    if pens:
        out.append(f"| penalty conversion | {100 * sum(s['outcome'] == 'Goal' for s in pens) / len(pens):.0f}% "
                   f"({len(pens)} pens) | {100 * cal.OUTCOMES['penalty_conversion']:.0f}% |")
    out += ["", "## Starting formations", "", "| Formation | Synthetic | Real PL |", "|---|---|---|"]
    ftot = sum(formations.values())
    for f, w in list(cal.FORMATION_WEIGHTS.items())[:8]:
        out.append(f"| {f} | {100 * formations[f] / ftot:.1f}% | {100 * w:.1f}% |")
    return "\n".join(out)


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("n", type=int, nargs="?", default=200)
    ap.add_argument("--md", help="write the report to this markdown file")
    args = ap.parse_args()
    text = report(args.n)
    print(text)
    if args.md:
        Path(args.md).parent.mkdir(parents=True, exist_ok=True)
        Path(args.md).write_text(text + "\n", encoding="utf-8")
