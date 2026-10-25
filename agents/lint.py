"""Rule checks run by Python on every agent answer before it goes on air.

Prompts tell the agents what not to do, but a model under time pressure still slips:
"the booking could make him cautious", "he slams it home", "Kestrel lead 2-1" when the
score is 1-2. These checks catch the slips the prompt could not prevent. When one fires,
the agent gets its answer back with the broken rules and writes it once more
(see Agent.ask in runtime.py). They never rewrite the text themselves.
"""
from __future__ import annotations

import json
import re

# Guesses about the future or about intentions: the data only says what happened.
SPECULATION = re.compile(
    r"\b(could(?!\s+not|n't)|may|might|will|likely|looks? set|set to|designed to|expects?|expected to|"
    r"hoping|will want|aims? to|in order to|bound to|surely)\b", re.I)

# Verbs and details that describe something the feed never gives.
INVENTED = re.compile(
    r"\b(slams?|slammed|lash(es|ed)?|smash(es|ed)?|curls?|curled|bends?|bent it|drills?|drilled|"
    r"rifles?|rifled|thunders?|thundered|rockets?|rocketed|brandish\w*|cuts? in(side)?|"
    r"races? clear|skips? past|bursts?|burst forward|ghosts? in|top corner|far post|near post|"
    r"dives?|diving)\b", re.I)

# A tactical change described as the cause of a goal (timing is not causation).
CAUSAL = re.compile(
    r"\b(change|tweak|switch|substitution|recalibration|adjustment|improvement|instruction|reduction)\b"
    r"[^.;]{0,60}?\b(produced|led to|caused|resulted in|delivered|improved)\b", re.I)

# Counter-attacks are only told when the data marks a shot as one.
COUNTER = re.compile(r"\b(on the break|on the counter|counter-?attack\w*|in transition|broke away|breaks? away)\b", re.I)

# Over-precise numbers ("xG 0.288"): agents round to two decimals.
OVER_PRECISE = re.compile(r"\b\d+\.\d{3,}\b")

# "Kestrel Vale beat Harbourne Rovers 5-2": a result is naturally told winner first.
RESULT_PHRASE = re.compile(r"\b(beat|beats|won|win|wins|winners|victory|ran out|romp)\b[^.;]{0,45}$", re.I)

# Internal names that must never reach the viewer.
INTERNALS = re.compile(r"\b(get_\w+|summarize_period|list_shots|period summary|tool(s)?|function)\b", re.I)

SCORE = re.compile(r"\b(\d{1,2})\s?[-–]\s?(\d{1,2})\b")


def _text_of(raw: str) -> str:
    """The text a viewer will read: the "text" field of a JSON answer, or the answer itself."""
    try:
        data = json.loads(raw)
        if isinstance(data, dict) and isinstance(data.get("text"), str):
            return data["text"] + " " + str(data.get("speech", ""))
    except (json.JSONDecodeError, TypeError):
        pass
    return raw


def _hits(pattern: re.Pattern, text: str) -> list[str]:
    found = []
    for m in pattern.finditer(text):
        word = m.group(0).strip()
        if word.lower() not in (w.lower() for w in found):
            found.append(word)
    return found


def flipped_scores(text: str, ctx) -> list[str]:
    """Scores written the wrong way round: the reverse of the current score that the match
    never had ("Kestrel lead 2-1" when it is Harbourne Rovers 1-2 Kestrel Vale)."""
    seen_scores = {(0, 0)}
    for e in ctx.seen:
        s = e.get("score")
        if s:
            seen_scores.add((s["home"], s["away"]))
    current = ctx.seen[-1]["score"] if ctx.seen else {"home": 0, "away": 0}
    h, a = current["home"], current["away"]
    if h == a:
        return []
    wrong = []
    for m in SCORE.finditer(text):
        pair = (int(m.group(1)), int(m.group(2)))
        if pair == (a, h) and pair not in seen_scores and not RESULT_PHRASE.search(text[:m.start()]):
            if m.group(0) not in wrong:
                wrong.append(m.group(0))
    return wrong


def narrator(raw: str, ctx) -> list[str]:
    text = _text_of(raw)
    problems = []
    if words := _hits(SPECULATION, text):
        problems.append(f"No guesses about the future or intentions: remove {', '.join(words)}. "
                        "Say only what happened.")
    if words := _hits(INVENTED, text):
        problems.append(f"These words add details the feed does not give: {', '.join(words)}. "
                        "Use neutral verbs (scores, finishes, heads in, fires, strikes).")
    if words := _hits(COUNTER, text):
        recent = ctx.seen[-120:]
        if not any(e["type"] == "shot" and (e.get("details") or {}).get("counter_attack") for e in recent):
            problems.append(f"No counter-attack in the feed: remove {', '.join(words)}.")
    if words := _hits(OVER_PRECISE, text):
        problems.append(f"Round these numbers to two decimals: {', '.join(words)}.")
    if wrong := flipped_scores(text, ctx):
        s = ctx.seen[-1]["score"]
        problems.append(f"Score written the wrong way round ({', '.join(wrong)}). Write it home team "
                        f"first: {ctx.home['name']} {s['home']}-{s['away']} {ctx.away['name']}.")
    return problems


def analyst(raw: str, ctx) -> list[str]:
    """Tactical Analyst and Stats Agent answers."""
    text = _text_of(raw)
    problems = []
    if m := CAUSAL.search(text):
        problems.append(f'"{m.group(0)}": a change never produces or causes goals in your answer. '
                        "Give the numbers before and after it and say they coincided.")
    if words := _hits(OVER_PRECISE, text):
        problems.append(f"Round these numbers to two decimals: {', '.join(words)}.")
    if words := _hits(INTERNALS, text):
        problems.append(f"Never mention your tools or data sources to the viewer ({', '.join(words)}).")
    if wrong := flipped_scores(text, ctx):
        problems.append(f"Score written the wrong way round ({', '.join(wrong)}): home team first.")
    return problems
