"""Command line interface (run from the repo root).

    python -m matchsim teams                                   # the 20 clubs
    python -m matchsim squad HAR                               # a club's 25-player squad
    python -m matchsim generate --home HAR --away KES --seed 7 --out data/match.jsonl
    python -m matchsim stream --home HAR --away KES --seed 7 --speed 60 --pretty
    python -m matchsim season --out data/season                # full 38-matchday season + awards
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import random
import sys
from collections import defaultdict
from datetime import datetime, timedelta

from .engine import simulate_match
from .ratings import player_match_stats
from .stats import team_stats
from .stream import print_feed
from .teams import LEAGUE_NAME, PLAYER_OF_THE_SEASON_AWARD, IDENTITIES, build_league, get_team


def _write_jsonl(events, path):
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        for e in events:
            f.write(json.dumps(e, ensure_ascii=False) + "\n")


def cmd_teams(args):
    print(LEAGUE_NAME)
    for t in build_league(args.league_seed):
        star = max(t.players, key=lambda p: p.overall)
        print(f"{t.code}  {t.name:<22} {IDENTITIES[t.identity]['label']:<22} {t.formation:<6} "
              f"manager: {t.manager:<22} star: {star.name} ({star.overall})")


def cmd_squad(args):
    t = get_team(build_league(args.league_seed), args.club)
    print(f"{t.name} - {t.manager} - {IDENTITIES[t.identity]['label']} - {t.formation}")
    for p in sorted(t.players, key=lambda p: (p.group != "GK", -p.overall)):
        fs = p.face_stats
        print(f"#{p.number:<3} {p.name:<26} {p.position:<4} {p.overall}  {p.role:<22} {p.nationality:<18} "
              f"{p.age}y {p.height_cm}cm {p.preferred_foot[0]}F WF{p.weak_foot} SM{p.skill_moves}  "
              f"PAC {fs['PAC']} SHO {fs['SHO']} PAS {fs['PAS']} DRI {fs['DRI']} DEF {fs['DEF']} PHY {fs['PHY']}")


def _pick(args):
    league = build_league(args.league_seed)
    rng = random.Random(args.seed)
    home = get_team(league, args.home) if args.home else rng.choice(league)
    away = get_team(league, args.away) if args.away else rng.choice([t for t in league if t is not home])
    return home, away


def cmd_generate(args):
    home, away = _pick(args)
    events = simulate_match(home, away, seed=args.seed)
    _write_jsonl(events, args.out)
    st = team_stats(events)
    end = events[-1]["details"]
    print(f"{home.name} {end['final_score']['home']}-{end['final_score']['away']} {away.name}  "
          f"(xG {end['xg']['home']}-{end['xg']['away']}, {len(events)} events) -> {args.out}")
    for tid in (home.id, away.id):
        s = st[tid]
        print(f"  {tid}: poss {s['possession_pct']:.0f}%  shots {s['shots']:.0f} ({s['shots_on_target']:.0f} on target)  "
              f"passes {s['passes']:.0f} @ {s['pass_accuracy_pct']:.0f}%")
    motm = end["player_of_the_match"]
    print(f"  Player of the match: {motm['player']} ({motm['rating']})")


def cmd_stream(args):
    home, away = _pick(args)
    events = simulate_match(home, away, seed=args.seed)
    try:
        print_feed(events, args.speed, pretty=args.pretty)
    except (BrokenPipeError, KeyboardInterrupt):
        sys.stderr.close()


def _fixtures(n_teams, rng):
    idx = list(range(n_teams))
    rng.shuffle(idx)
    rounds = []
    for r in range(n_teams - 1):
        pairs = [(idx[k], idx[n_teams - 1 - k]) for k in range(n_teams // 2)]
        rounds.append([(a, b) if r % 2 == 0 else (b, a) for a, b in pairs])
        idx = [idx[0]] + [idx[-1]] + idx[1:-1]
    return rounds + [[(b, a) for a, b in rnd] for rnd in rounds]


def cmd_season(args):
    """Full double round-robin season with squad rotation, standings and awards."""
    league = build_league(args.league_seed)
    rng = random.Random(args.seed)
    teams = league[: args.clubs]
    rounds = _fixtures(len(teams), rng)[: args.matchdays]
    os.makedirs(os.path.join(args.out, "matches"), exist_ok=True)

    fitness = {p.id: 100.0 for t in teams for p in t.players}
    table = {t.id: dict(team=t.name, P=0, W=0, D=0, L=0, GF=0, GA=0, GD=0, xGF=0.0, xGA=0.0, Pts=0) for t in teams}
    season = defaultdict(lambda: defaultdict(float))
    rows = []
    date = datetime(2026, 8, 15, 15, 0)
    for md, rnd in enumerate(rounds, 1):
        midweek = md % 6 == 3                      # a few midweek rounds, like the real calendar
        rest_days = 3 if midweek else 7
        for a, b in rnd:
            h, w = teams[a], teams[b]
            seed = rng.getrandbits(32)
            ko = date.strftime("%Y-%m-%dT%H:%M:%SZ")
            ev = simulate_match(h, w, seed=seed, kickoff_utc=ko, matchday=md,
                                match_id=f"AFL26-MD{md:02d}-{h.code}-{w.code}",
                                home_fitness=fitness, away_fitness=fitness)
            _write_jsonl(ev, os.path.join(args.out, "matches", f"{ev[0]['match_id']}.jsonl"))
            end = ev[-1]["details"]
            hs, as_ = end["final_score"]["home"], end["final_score"]["away"]
            rows.append(dict(match_id=ev[0]["match_id"], matchday=md, kickoff_utc=ko, home=h.name, away=w.name,
                             home_goals=hs, away_goals=as_, home_xg=end["xg"]["home"], away_xg=end["xg"]["away"],
                             player_of_the_match=end["player_of_the_match"]["player"], events=len(ev), seed=seed))
            for tid, gf, ga, xf, xa in ((h.id, hs, as_, end["xg"]["home"], end["xg"]["away"]),
                                        (w.id, as_, hs, end["xg"]["away"], end["xg"]["home"])):
                r = table[tid]
                r["P"] += 1; r["GF"] += gf; r["GA"] += ga; r["GD"] = r["GF"] - r["GA"]
                r["xGF"] += xf; r["xGA"] += xa
                if gf > ga:
                    r["W"] += 1; r["Pts"] += 3
                elif gf == ga:
                    r["D"] += 1; r["Pts"] += 1
                else:
                    r["L"] += 1
            for pid, s in player_match_stats(ev).items():
                agg = season[pid]
                agg["team_id"] = s["team_id"]
                agg["player"] = s["player"]
                agg["apps"] += 1
                agg["minutes"] += s["minutes"]
                agg["rating_sum"] += s["rating"]
                for k in ("goals", "assists", "xg", "xa", "shots", "key_passes", "tackles", "interceptions", "saves"):
                    agg[k] += s[k]
                if s["slot"] == "GK" and s["goals_conceded"] == 0 and s["minutes"] >= 60:
                    agg["clean_sheets"] += 1
                agg["motm"] += end["player_of_the_match"]["player_id"] == pid
                fitness[pid] = max(40.0, fitness[pid] - s["minutes"] * 0.26)
        # recovery between matchdays, faster for fit and young players
        for t in teams:
            for p in t.players:
                gain = rest_days * (3.2 + (p.a("stamina") - 70) / 40 - max(0, p.age - 30) * 0.12)
                fitness[p.id] = min(100.0, fitness[p.id] + gain)
        date += timedelta(days=rest_days)
        print(f"matchday {md}/{len(rounds)} done", file=sys.stderr)

    standings = sorted(table.values(), key=lambda r: (-r["Pts"], -r["GD"], -r["GF"]))
    with open(os.path.join(args.out, "matches.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(rows[0])); wr.writeheader(); wr.writerows(rows)
    with open(os.path.join(args.out, "standings.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=["pos"] + list(standings[0])); wr.writeheader()
        for k, r in enumerate(standings, 1):
            wr.writerow({"pos": k, **{kk: round(v, 2) if isinstance(v, float) else v for kk, v in r.items()}})

    players = []
    by_id = {p.id: (p, t) for t in teams for p in t.players}
    for pid, a in season.items():
        p, t = by_id[pid]
        players.append({"player_id": pid, "player": a["player"], "team": t.name, "position": p.position,
                        "apps": int(a["apps"]), "minutes": int(a["minutes"]),
                        "avg_rating": round(a["rating_sum"] / a["apps"], 2), "goals": int(a["goals"]),
                        "assists": int(a["assists"]), "xg": round(a["xg"], 1), "xa": round(a["xa"], 1),
                        "key_passes": int(a["key_passes"]), "tackles": int(a["tackles"]),
                        "interceptions": int(a["interceptions"]), "saves": int(a["saves"]),
                        "clean_sheets": int(a["clean_sheets"]), "player_of_the_match": int(a["motm"])})
    with open(os.path.join(args.out, "players.csv"), "w", newline="", encoding="utf-8") as f:
        wr = csv.DictWriter(f, fieldnames=list(players[0])); wr.writeheader(); wr.writerows(players)

    regulars = [p for p in players if p["apps"] >= 0.6 * len(rounds)]
    best = max(regulars, key=lambda p: p["avg_rating"] + 0.01 * p["player_of_the_match"])
    awards = {
        "season": f"{LEAGUE_NAME} 2026/27",
        "champion": standings[0]["team"],
        PLAYER_OF_THE_SEASON_AWARD: {k: best[k] for k in ("player", "team", "position", "avg_rating", "goals", "assists")},
        "golden_boot": max(players, key=lambda p: (p["goals"], -p["minutes"])),
        "playmaker": max(players, key=lambda p: (p["assists"], p["key_passes"])),
        "golden_glove": max([p for p in players if p["position"] == "GK"], key=lambda p: (p["clean_sheets"], p["saves"])),
        "team_of_the_season": _team_of_the_season(regulars, by_id),
    }
    with open(os.path.join(args.out, "awards.json"), "w", encoding="utf-8") as f:
        json.dump(awards, f, ensure_ascii=False, indent=1)
    with open(os.path.join(args.out, "league.json"), "w", encoding="utf-8") as f:
        json.dump([t.to_dict() for t in league], f, ensure_ascii=False, indent=1)
    print(f"{len(rows)} matches -> {args.out}")
    print(f"Champion: {awards['champion']} | {PLAYER_OF_THE_SEASON_AWARD}: {best['player']} ({best['team']}, "
          f"avg {best['avg_rating']}) | Golden Boot: {awards['golden_boot']['player']} ({awards['golden_boot']['goals']})")


def _team_of_the_season(regulars, by_id):
    """Best XI in a 4-3-3 by average rating (GK, RB, 2 CB, LB, 3 midfielders, RW, ST, LW)."""
    slots = [("GK", {"GK"}), ("RB", {"RB", "RWB"}), ("CB", {"CB"}), ("CB", {"CB"}), ("LB", {"LB", "LWB"}),
             ("DM", {"CDM", "CM"}), ("CM", {"CM", "CDM", "CAM"}), ("AM", {"CAM", "CM"}),
             ("RW", {"RW", "LW"}), ("ST", {"ST"}), ("LW", {"LW", "RW"})]
    pool = sorted(regulars, key=lambda r: -r["avg_rating"])
    xi, used = [], set()
    for label, positions in slots:
        best = next((p for p in pool if p["position"] in positions and p["player_id"] not in used), None)
        if best:
            used.add(best["player_id"])
            xi.append({"slot": label, "player": best["player"], "team": best["team"], "position": best["position"],
                       "avg_rating": best["avg_rating"]})
    return xi


def main(argv=None):
    ap = argparse.ArgumentParser(prog="matchsim", description="Synthetic Premier League-calibrated match generator")
    ap.add_argument("--league-seed", type=int, default=2026)
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("teams").set_defaults(fn=cmd_teams)
    sp = sub.add_parser("squad"); sp.add_argument("club"); sp.set_defaults(fn=cmd_squad)
    for name, fn in (("generate", cmd_generate), ("stream", cmd_stream)):
        sp = sub.add_parser(name)
        sp.add_argument("--home"); sp.add_argument("--away")
        sp.add_argument("--seed", type=int, default=7)
        if name == "generate":
            sp.add_argument("--out", default="data/match.jsonl")
        else:
            sp.add_argument("--speed", type=float, default=60.0, help="60 = 90 minutes in 90 seconds; 0 = instant")
            sp.add_argument("--pretty", action="store_true")
        sp.set_defaults(fn=fn)
    sp = sub.add_parser("season")
    sp.add_argument("--out", default="data/season")
    sp.add_argument("--clubs", type=int, default=20)
    sp.add_argument("--matchdays", type=int, default=38)
    sp.add_argument("--seed", type=int, default=2026)
    sp.set_defaults(fn=cmd_season)
    args = ap.parse_args(argv)
    args.fn(args)


if __name__ == "__main__":
    main()
