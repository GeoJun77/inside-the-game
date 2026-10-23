"""Sanity tests for the synthetic match engine and the xG pipeline (run: python -m pytest -q)."""
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

import pytest  # noqa: E402

from matchsim import build_league, get_team, simulate_match  # noqa: E402
from matchsim.formations import FORMATIONS  # noqa: E402
from xg import load_default_model  # noqa: E402

LEAGUE = build_league()


@pytest.fixture(scope="module")
def match():
    return simulate_match(get_team(LEAGUE, "HAR"), get_team(LEAGUE, "KES"), seed=11)


def test_league_structure():
    assert len(LEAGUE) == 20
    for team in LEAGUE:
        assert len(team.players) == 25
        assert len({p.short_name for p in team.players}) == 25, "surnames must be unique within a club"
        assert team.formation in FORMATIONS
    names = [p.name for t in LEAGUE for p in t.players]
    assert len(names) == len(set(names))


def test_same_seed_same_match():
    a = simulate_match(LEAGUE[0], LEAGUE[1], seed=3)
    b = simulate_match(LEAGUE[0], LEAGUE[1], seed=3)
    assert a[-1]["details"]["final_score"] == b[-1]["details"]["final_score"]
    assert len(a) == len(b)


def test_match_flow(match):
    types = Counter(e["type"] for e in match)
    assert types["match_start"] == 1 and types["match_end"] == 1 and types["period_start"] == 2
    assert types["shot"] > 0 and types["pass"] > 300
    ids = [e["event_id"] for e in match]
    assert ids == sorted(ids)
    seconds = [e["match_seconds"] for e in match if e["period"] == 2]
    assert seconds == sorted(seconds)
    goals = sum(e["type"] == "goal" for e in match)
    final = match[-1]["details"]["final_score"]
    assert goals == final["home"] + final["away"]


def test_premier_league_substitution_rules(match):
    subs = [e for e in match if e["type"] == "substitution"]
    for team in ("HAR", "KES"):
        team_subs = [e for e in subs if e["team_id"] == team]
        assert len(team_subs) <= 5
        assert max([e["details"]["windows_used"] for e in team_subs] or [0]) <= 3


def test_coordinates_on_pitch(match):
    for e in match:
        for key in ("location", "end_location", "location_abs"):
            if e[key]:
                x, y = e[key]
                assert 0 <= x <= 120 and 0 <= y <= 80, (e["type"], key, e[key])


def test_shots_carry_statsbomb_style_freeze_frames(match):
    shots = [e for e in match if e["type"] == "shot"]
    for s in shots:
        frame = s["details"]["freeze_frame"]
        assert frame and all({"location", "player", "position", "teammate"} <= set(p) for p in frame)
        if s["details"]["shot_type"] != "Penalty":
            assert sum(p["position"]["name"] == "Goalkeeper" and not p["teammate"] for p in frame) == 1
        assert 0 < s["details"]["xg"] < 1


def test_xg_is_reproducible_from_the_event(match):
    model = load_default_model()
    if model is None:
        pytest.skip("models/xg_model.joblib not available")
    for s in (e for e in match if e["type"] == "shot"):
        d = s["details"]
        shot = {"location": s["location"], "freeze_frame": d["freeze_frame"], "body_part": d["body_part"],
                "shot_type": d["shot_type"], "technique": d["technique"], "under_pressure": s["under_pressure"],
                "first_time": d["first_time"], "one_on_one": d["one_on_one"], "aerial_won": d["aerial_won"],
                "assist_type": d["assist_type"]}
        assert abs(model.score_shot(shot, explain=False)[0] - d["xg"]) < 0.0015


def test_ratings_and_player_of_the_match(match):
    end = match[-1]["details"]
    assert end["player_of_the_match"]["player"]
    assert all(3.0 <= r["rating"] <= 10.0 for r in end["player_ratings"])
