"""Tests of what Python guarantees around the agents (no Foundry call needed).

    python -m pytest -q tests
"""
import json

import pytest

from agents import lint
from agents.match_tools import MatchContext, formation_label
from agents.voice import say_formations
from app.live import segments_of
from matchsim import build_league, get_team, simulate_match


@pytest.fixture(scope="module")
def match():
    league = build_league()
    return simulate_match(get_team(league, "HAR"), get_team(league, "KES"), seed=7)


def ctx_at(events, minute):
    ctx = MatchContext(events)
    ctx.advance_to(minute)
    return ctx


def line(text):
    return json.dumps({"text": text, "speech": text, "excitement": 2, "subtitle": text})


def test_halves_add_up_to_the_match(match):
    ctx = MatchContext(match)
    ctx.seen = list(match)
    halves = [ctx.summarize_period(1, 45)["teams"], ctx.summarize_period(46, 90)["teams"]]
    total = ctx.get_match_state()["xg"]
    for side, name in (("home", ctx.home["name"]), ("away", ctx.away["name"])):
        assert round(halves[0][name]["xg"] + halves[1][name]["xg"], 2) == pytest.approx(total[side], abs=0.011)


def test_player_of_the_match_is_computed(match):
    ctx = MatchContext(match)
    ctx.seen = list(match)
    top = ctx.get_top_players(3)
    potm = top["player_of_the_match"]
    assert potm["player"] == top["ranking"][0]["player"]            # the best rating, computed in Python
    assert potm["ahead_of_next_by"] >= 0 and potm["facts"]


def first_minute_with_a_lead(events):
    for e in events:
        if e["type"] == "goal" and e["score"]["home"] != e["score"]["away"]:
            return e["minute"] + 1, e["score"]
    raise AssertionError("no goal in the test match")


def test_lint_catches_slips(match):
    minute, score = first_minute_with_a_lead(match)
    ctx = ctx_at(match, minute)
    flipped = f"{score['away']}-{score['home']}"
    assert lint.narrator(line("The booking could make him cautious."), ctx)
    assert lint.narrator(line("Thibault slams it home."), ctx)
    assert lint.narrator(line(f"They are still leading {flipped}."), ctx)
    assert lint.analyst("Thibault should be the player of the match.", ctx)
    assert lint.analyst("The half-time tweak produced two goals.", ctx)


def test_lint_lets_good_lines_through(match):
    minute, score = first_minute_with_a_lead(match)
    ctx = ctx_at(match, minute)
    good = f"He heads in from 3 m: Harbourne Rovers {score['home']}-{score['away']} Kestrel Vale."
    assert not lint.narrator(line(good), ctx)
    end = ctx_at(match, 95)
    final = end.seen[-1]["score"]
    winner, loser = ("Harbourne Rovers", "Kestrel Vale") if final["home"] >= final["away"] else ("Kestrel Vale", "Harbourne Rovers")
    hi, lo = max(final.values()), min(final.values())
    assert not lint.narrator(line(f"{winner} beat {loser} {hi}-{lo}. They could not find the net early on."), end)


def test_formations_are_written_and_said_properly():
    assert formation_label("4231") == "4-2-3-1"
    assert say_formations("a 4-2-3-1 against a 3-5-2, score 2-1") == \
        "a four-two-three-one against a three-five-two, score 2-1"


def test_segments_cut_on_goals_and_cover_the_match(match):
    segments = list(segments_of(match))
    assert sum(len(b) for _, b in segments) == len(match)
    for _, batch in segments:
        goals = [i for i, e in enumerate(batch) if e["type"] == "goal"]
        assert not goals or goals == [len(batch) - 1]   # a goal always ends its segment


def test_highlights_fit_the_chosen_pace_and_keep_the_key_moments(match):
    from app.highlights import condensed, screen_seconds, target_seconds
    assert condensed(match, 1.0) == set()                     # pace 1: the whole match
    for speed in (2.0, 3.0):
        hidden = condensed(match, speed)
        assert screen_seconds(match, hidden) <= target_seconds(speed) + 1
        assert not any(i in hidden for i, e in enumerate(match) if e["type"] in ("shot", "goal", "foul", "card", "kick_off"))
