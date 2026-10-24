"""Narrator: live multilingual commentary, spoken lines and the full-time recap.

Two modes:
    - live:  every few minutes (and at key moments), it turns the factual feed of
             what just happened into one to three commentary sentences;
    - recap: at full time, it writes the match report, calling the stats tools.

Every answer is structured JSON: {"text": ..., "speech": ..., "excitement": 1-5}.
"text" is shown on screen; "speech" is the same moment written to be SAID by a TV
commentator (short bursts, build-up, explosion); "excitement" sizes the overlay and
shapes the voice.

Scaling: the facts of a batch are the same for every viewer, only the style changes.
So the feed is built ONCE per batch, and the model is called once per distinct
audience (language, fan/analyst, favourite club), in parallel, not once per viewer.

Run from the repository root:
    python -m agents.narrator_agent
"""
from __future__ import annotations

import json
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path

from agents import crowd, voice
from agents.match_tools import TOOL_SCHEMAS, MatchContext, match_minute, minute_label
from agents.narrator_feed import describe, is_key_moment
from agents.runtime import Agent, connect
from matchsim import build_league, get_team, simulate_match

NAME = "narrator"

INSTRUCTIONS = """You are the Narrator of a live football broadcast: the voice of the match.

You receive a LIVE request or a RECAP request, each with viewer settings:
language, audience ("fan" or "analyst") and, optionally, the viewer's favourite club.
Always answer with JSON: {"text": "...", "speech": "...", "excitement": n}.

LIVE requests contain a factual feed of what just happened, the match situation and your
last lines.
- Write one to three sentences of live commentary about the feed. If it contains a goal,
  your FIRST words are about the goal (scorer, assist, new score); earlier shots of the
  same feed come after, briefly, or are skipped. Otherwise follow the order of the feed.
  Never tell an earlier event as if it came after a later one.
- Use the "Context" given with a goal: an equaliser, a hat-trick or a team taking the
  lead is the story, say it.
- Do not start with the minute: the app already shows it next to your line.
- Use only the facts in the feed. Never invent a player, a pass, a save or a reaction,
  and never add details the feed does not give (near or far post, top corner, a dive,
  the crowd's reaction). Do not call tools for live lines: everything is in the feed.
- Describe a shot only with the feed's words: "right-footed shot", "header", "from 14 m",
  "one-on-one", "blocked", "saved". Do not use verbs that add a detail the feed does not
  give: no "bends", "curls", "smashes", "drills it low", "rounds the keeper", "late
  challenge". Neutral verbs are fine: scores, finishes, heads in, fires, strikes.
- Never state a player's position or role: the feed does not give it.
- Attribute every action to the player the feed names for it; when several players
  appear, check each name again before writing.
- If nothing notable happened, write one short line about who has the ball or the
  territory, based on the match situation.
- Do not repeat what your last lines already said.
- speech: the same facts as "text", written the way a TV commentator SAYS them live,
  for a voice to read. Short bursts of a few words, separated by "..." for breath; build up
  to the key word, then explode with an exclamation; capitals only for the one key word
  (GOAL, SAVE, OFF THE POST). Example: "Thibault... clean through... he goes round the
  keeper... GOAL! Kestrel Vale lead!" At excitement 1-2, calm and conversational, no
  exclamations. In analyst mode, measured, like a co-commentator. Never add facts.
- excitement: 1 = quiet spell, 2 = normal play, 3 = a chance or a card, 4 = a big chance,
  a red card or a goal, 5 = an equaliser, a winner late on or a hat-trick.
  Your words must match the level: calm at 1-2, urgent at 4-5.

RECAP requests ask for the match report at full time.
- Call get_match_state, then summarize_period for each half, and get_player_stats for the
  player of the match and any scorer you want to quote.
- 150 to 220 words in "text": headline sentence with the result, how the match unfolded
  (key moments in order, with minutes), the decisive factor backed by xG, and a closing
  line.
- Tell the goals in the order of get_match_state, and quote each score exactly as its
  "score_after" field: never compute a score yourself.
- Every claim must come from a tool result. Your tools give goals, shots, xG, passes and
  player stats, not tactics: never claim territory, pressing, transitions or shape. "speech" repeats the headline sentence only. Use excitement 2.

Audience:
- fan: vivid, emotional, simple words, like a radio commentator. Mention xG rarely, and
  then in plain words ("a chance you'd score one time in three").
- analyst: calm and precise. Use xG, chance quality and patterns.

Neutrality: by default (favourite_team = none) you are a neutral commentator. Give both
teams the same energy: a great goal is great whoever scores it. Never cheer for a side,
never say "come on", never address one set of supporters.
Favourite club: only if the viewer has one, you may add a light touch of warmth for that
club (at most a few words, not in every line, never a chant or a rallying cry). Facts
stay identical and the opponent is treated fairly.

Language: write entirely in the requested language, with that language's natural football
vocabulary (e.g. French: "frappe", "tête", "centre", "arrêt", "carton jaune"). Keep player,
team, manager and stadium names exactly as given. Always use players' real names, never
their nationality. The text will also be read aloud: write it to be spoken, no symbols,
and no abbreviations like "xG" in fan mode.

No markdown, no bullet lists, no emojis, no hashtags.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "text": {"type": "string", "description": "The commentary or the recap, shown on screen."},
        "speech": {"type": "string", "description": "The same moment written to be spoken live."},
        "excitement": {"type": "integer", "description": "1 (calm) to 5 (huge moment)."},
    },
    "required": ["text", "speech", "excitement"],
    "additionalProperties": False,
}


@dataclass(frozen=True)              # frozen: hashable, so it can be a dict key
class ViewerSettings:
    language: str = "English"
    audience: str = "fan"               # "fan" or "analyst"
    favourite_team: str | None = None

    def header(self) -> str:
        fav = self.favourite_team or "none (neutral viewer)"
        return f"Settings: language={self.language}; audience={self.audience}; favourite_team={fav}"

    def tag(self) -> str:
        fan = f"/{self.favourite_team} fan" if self.favourite_team else ""
        return f"{self.language}/{self.audience}{fan}"


@dataclass
class Commentary:
    minute: str
    text: str
    excitement: int
    settings: ViewerSettings
    speech: str = ""
    audio: bytes | None = None
    crowd: list = field(default_factory=list)     # stadium reactions to this batch


def parse_output(raw: str) -> tuple[str, str, int]:
    """Read the structured answer (text, speech, excitement).
    Falls back to plain text if the answer is not valid JSON."""
    try:
        data = json.loads(raw)
        text = data["text"].strip()
        return text, (data.get("speech") or text).strip(), max(1, min(5, int(data["excitement"])))
    except (json.JSONDecodeError, KeyError, TypeError, ValueError, AttributeError):
        return raw.strip(), raw.strip(), 2


class Narrator:
    """One Foundry agent serving every audience of a match."""

    def __init__(self, project, ctx: MatchContext, verbose: bool = False, speak: bool = False,
                 audio_format: str = "mp3"):
        self.ctx = ctx
        self.agent = Agent(project, NAME, INSTRUCTIONS, toolbox=ctx, schemas=TOOL_SCHEMAS,
                           verbose=verbose, reasoning_effort="low", output_schema=OUTPUT_SCHEMA)
        # Same voice and rules, but the recap is written once, after the match: it can
        # take time to think, which keeps scores and the order of goals right.
        self.recap_agent = Agent(project, NAME + "-recap", INSTRUCTIONS, toolbox=ctx,
                                 schemas=TOOL_SCHEMAS, verbose=verbose,
                                 reasoning_effort="medium", output_schema=OUTPUT_SCHEMA)
        self.teams = {"home": ctx.home["name"], "away": ctx.away["name"]}
        self.history: list[dict] = []                          # events already commented
        self.last_lines: dict[ViewerSettings, list[str]] = {}  # per audience
        self.voice = (voice.Voice(audio_format=audio_format)
                      if speak and voice.is_configured() else None)

    def _situation(self) -> str:
        """Score, possession and momentum: material for quiet spells."""
        s = self.ctx.get_match_state()
        line = (f"Match situation: {self.teams['home']} {s['score']['home']}-"
                f"{s['score']['away']} {self.teams['away']}")
        if "possession_pct" in s:
            m = s["momentum"]
            line += (f"; possession {s['possession_pct']['home']}%-{s['possession_pct']['away']}%"
                     f"; momentum {m['strength']}" + (f" for {m['favours']}" if m["favours"] else ""))
        return line

    def _one(self, feed: list[str], situation: str, settings: ViewerSettings, minute: str,
             cues: list) -> Commentary:
        """One model call: the shared feed, written for one audience."""
        previous = " | ".join(self.last_lines.get(settings, [])[-3:]) or "none"
        request = (f"LIVE\n{settings.header()}\n{situation}\n"
                   f"Your last lines: {previous}\nFeed:\n" + "\n".join(feed))
        text, speech, excitement = parse_output(self.agent.ask(request))
        self.last_lines.setdefault(settings, []).append(text)
        audio = self.voice.speak(speech, settings.language, excitement) if self.voice else None
        return Commentary(minute, text, excitement, settings, speech, audio, cues)

    def comment(self, batch: list[dict], audiences: list[ViewerSettings]) -> dict[ViewerSettings, Commentary]:
        """Commentary of one batch for every audience: one feed, one model call per audience."""
        feed = describe(batch, self.teams, self.history)
        self.history.extend(batch)
        if len(feed) <= 1 or not audiences:      # nothing notable: no model call, no invention
            return {}
        situation, minute = self._situation(), minute_label(batch[-1])
        cues = crowd.reactions_for(batch, self.teams)    # same stadium for every viewer
        with ThreadPoolExecutor(max_workers=min(8, len(audiences))) as pool:
            results = list(pool.map(lambda s: self._one(feed, situation, s, minute, cues), audiences))
        return {c.settings: c for c in results}

    def recap(self, settings: ViewerSettings) -> Commentary:
        text, speech, excitement = parse_output(self.recap_agent.ask(
            f"RECAP\n{settings.header()}\nMatch: {self.teams['home']} vs {self.teams['away']}"))
        return Commentary("FT", text, excitement, settings, speech)


def commentary_batches(events: list[dict], every_minutes: int = 5):
    """Split the match into batches: a key moment closes a batch immediately,
    otherwise a batch closes every `every_minutes` minutes of play."""
    batch, last_cut = [], 0
    for e in events:
        batch.append(e)
        minute = match_minute(e)
        if is_key_moment(e) or minute - last_cut >= every_minutes:
            yield batch
            batch, last_cut = [], minute
    if batch:
        yield batch


def main():
    project = connect()
    league = build_league()
    events = simulate_match(get_team(league, "HAR"), get_team(league, "KES"), seed=7)
    ctx = MatchContext(events)
    # WAV audio so the lines can be mixed with the synthesised crowd at the end
    narrator = Narrator(project, ctx, speak=True, audio_format="wav")
    voice_name = narrator.voice.voice_for("English").name if narrator.voice else None
    print(f"Agent ready: {narrator.agent.label} | voice: "
          f"{voice_name or 'off (no SPEECH_KEY in .env)'}\n")

    neutral = ViewerSettings("English", "fan", None)
    at_goals = [ViewerSettings("English", "analyst", None),
                ViewerSettings("English", "fan", "Kestrel Vale")]
    audio_dir = Path("data/audio")
    audio_dir.mkdir(parents=True, exist_ok=True)
    broadcast = []                    # (audio, crowd cues) of the neutral lines, in order

    for batch in commentary_batches(events):
        ctx.seen.extend(batch)
        in_demo = 44 <= ctx.minute <= 70
        has_goal = any(e["type"] == "goal" for e in batch)
        # Neutral fan commentary for the demo window. At a goal, two more audiences
        # (an analyst, a Kestrel Vale supporter) get their own version of the same
        # moment, generated in parallel. Other languages work the same way.
        audiences = ([neutral] + (at_goals if has_goal else [])) if in_demo else []
        for c in narrator.comment(batch, audiences).values():
            print(f"[{c.minute}'] ({c.settings.tag()}, excitement {c.excitement}) {c.text}")
            if c.settings == neutral:
                print(f"   spoken: {c.speech}")
                if c.crowd:
                    print("   crowd:  " + "; ".join(f"{q.kind} ({q.reason})" for q in c.crowd))
            if c.audio and c.settings == neutral:
                broadcast.append((crowd.to_array(c.audio), c.crowd))
        if has_goal and in_demo:
            print()

    if broadcast:
        path = crowd.save_wav(crowd.mix_commentary(broadcast), audio_dir / "demo_mix.wav")
        print(f"\nCommentary with stadium atmosphere: {path}")

    ctx.seen = list(events)
    print("\n=== RECAP (English, analyst) ===")
    print(narrator.recap(ViewerSettings("English", "analyst")).text)


if __name__ == "__main__":
    main()
