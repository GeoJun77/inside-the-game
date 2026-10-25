"""Producer: the director of the show, personalising the broadcast for each viewer.

The other agents speak; the Producer decides WHAT each viewer sees and when:
    - a headline for this viewer,
    - a personalised highlight reel (moments chosen from the match, in order),
    - the overlays to put on screen (score bug, xG timeline, player card...),
    - the questions to hand to the Stats Agent or the Tactical Analyst,
    - an alert when something matters to this viewer (their player, their club).

It is called at key points of the show: when a viewer joins late ("catch me up"),
at half-time, at full time, or when the viewer asks for their highlights.

Its plan is structured JSON, checked in Python: a highlight that points to a moment
that does not exist is dropped, so the reel can never show an invented moment.

Run from the repository root:
    python -m agents.producer_agent
"""
from __future__ import annotations

import json
from dataclasses import dataclass

from agents import stats_agent, tactical_agent
from agents.match_tools import MatchContext
from agents.producer_tools import TOOL_SCHEMAS, ProducerTools
from agents.runtime import Agent, connect
from matchsim import build_league, get_team, simulate_match

NAME = "producer"

MAX_HIGHLIGHTS = 8

OVERLAYS = ["match_stats", "score_bug", "xg_timeline", "momentum_bar", "shot_map",
            "player_card", "stat_comparison", "tactical_card", "lineups"]

INSTRUCTIONS = f"""You are the Producer of a live football broadcast: the director who decides
what each viewer sees. You do not commentate; you build a plan for one viewer at one moment.

Each request gives the MOMENT (CATCH_UP, HALF_TIME, FULL_TIME or HIGHLIGHTS) and the VIEWER:
language, audience (fan or analyst), favourite club (or none) and followed player (or none).

Method:
1. Call get_match_state. Then call get_key_moments: once for everything important
   (min_importance 0.4), and, if the viewer has a favourite club or a followed player,
   once filtered on them (min_importance 0) to find what matters to this viewer.
2. Call get_match_stats for the team statistics. If the viewer follows a player, call
   get_player_stats for that player.
3. Build the plan.

The plan:
- headline: one sentence for this viewer, in their language. Results and facts are the same
  for everyone; only the angle changes (a Harbourne fan hears about Harbourne first).
- highlights: 3 to 6 moments, in match order, using moment_id values returned by
  get_key_moments only. Always include the goals that decided the result, even when they
  hurt the viewer's club: honesty first, then personal relevance. The opener, any
  equaliser and any go-ahead goal are always in the reel. At FULL_TIME and HIGHLIGHTS every
  goal of the match is in the reel (up to 8 highlights): a goal matters to both sides.
  For each highlight:
    * title: a short, natural TV caption of 3 to 7 words ("Thibault opens the scoring",
      "Ashworth's header hits the post"), not a copy of the tool's description.
    * why_for_you: one sentence on why this viewer should watch it.
  Facts come only from the moment's description and roles: a header stays a header, a
  shot "saved onto the post" stays that (never "hit the bar"). Do not add how a goal was
  made ("brilliant individual effort", "smashed", "composed finish", "curled"): the data
  does not describe it. Never claim or guess an effect the tools do not show, not even with
  "may have" or "watch how it changed": no "it altered their shape", "it shaped their
  aggression", "it changed their passing".
- overlays: 2 to 4 on-screen graphics, chosen ONLY from: {", ".join(OVERLAYS)}. Each with a
  title and a one-line "content" built from tool results (real numbers, real names).
  "match_stats" is the full Premier League stats panel (possession, shots, shots on target,
  fouls, cards, tackles...): always include it at HALF_TIME and FULL_TIME, first. Its numbers
  are filled in by the app, so its "content" is just the one stat that tells the story
  (e.g. "Kestrel Vale: 12 shots on target to 6").
- agent_requests: 0 to 2 questions to hand to the other agents, when their expertise adds
  something this viewer would want. Ask only what their tools can answer:
    "stats": the score and goals, the xG of a shot and why, a period's box score, one
             player's statistics and rating.
    "tactical": each team's plan and in-game changes, territory and pressing (field tilt,
             PPDA), when the match turned, how a team attacks, the defensive shape on a shot.
  Never ask for what nobody measures: off-the-ball movement, minute-by-minute timelines,
  shot-by-shot lists, player positions. One short, precise question each, asked openly:
  never put the answer in the question ("When did the match turn?", not "After the goal at
  48', when did Kestrel take control?"), so the specialist finds what really happened. When a question
  is about a specific moment, give its minute AND its moment_id (for a shot it is the shot's
  event id), e.g. "Why was Ashworth's shot at 29' (event 512) worth 0.43 xG?".
- Scores: always home team first, exactly as in the descriptions ("Cardoso makes it 0-2"
  when the away side scores), never flipped to the scoring side. Minutes are written "at 11'"
  or "in the 11th minute", never "in the 11'".
- alert: one sentence if something specifically matters to this viewer (their player
  scored, was booked or came off; their club conceded or took the lead), else null.

Reading xG: for one shot, xG is the chance of scoring: above 0.30 is a high-quality chance,
0.10-0.30 a decent one, below 0.10 a low-probability effort (so 0.85 is a huge chance, not a
low-probability finish). Scoring from a low xG is a great finish; missing a high xG is a miss.
You are not the tactical analyst: do not describe pressing, transitions or shape yourself;
ask the tactical agent if the viewer needs it.

Rules: never invent a moment, a number, a player or a name: the stadium is the "venue" of
get_match_state, never a nickname. For a shot, "roles" says who shot, who assisted (null = no
assist) and which goalkeeper faced it; the goalkeeper is never an assister. Real player names, never nationalities.
Audience fan: simple, emotional wording. Audience analyst: precise, with xG.
No markdown in any field.
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {
        "headline": {"type": "string"},
        "highlights": {"type": "array", "items": {
            "type": "object",
            "properties": {"moment_id": {"type": "integer"}, "title": {"type": "string"},
                           "why_for_you": {"type": "string"}},
            "required": ["moment_id", "title", "why_for_you"], "additionalProperties": False}},
        "overlays": {"type": "array", "items": {
            "type": "object",
            "properties": {"kind": {"type": "string", "enum": OVERLAYS}, "title": {"type": "string"},
                           "content": {"type": "string"}},
            "required": ["kind", "title", "content"], "additionalProperties": False}},
        "agent_requests": {"type": "array", "items": {
            "type": "object",
            "properties": {"agent": {"type": "string", "enum": ["stats", "tactical"]},
                           "question": {"type": "string"}},
            "required": ["agent", "question"], "additionalProperties": False}},
        "alert": {"type": ["string", "null"]},
    },
    "required": ["headline", "highlights", "overlays", "agent_requests", "alert"],
    "additionalProperties": False,
}


@dataclass(frozen=True)
class ViewerProfile:
    name: str = "viewer"
    language: str = "English"
    audience: str = "fan"
    favourite_team: str | None = None
    followed_player: str | None = None

    def describe(self) -> str:
        return (f"language={self.language}; audience={self.audience}; "
                f"favourite_club={self.favourite_team or 'none'}; "
                f"followed_player={self.followed_player or 'none'}")


class Producer:
    def __init__(self, project, ctx: MatchContext, verbose: bool = True):
        self.ctx = ctx
        self.tools = ProducerTools(ctx)
        self.agent = Agent(project, NAME, INSTRUCTIONS, toolbox=self.tools, schemas=TOOL_SCHEMAS,
                           verbose=verbose, output_schema=OUTPUT_SCHEMA)

    def plan(self, moment: str, viewer: ViewerProfile, notes: list[str] | None = None) -> dict:
        """The show plan for one viewer at one moment, checked against the real match.
        notes: what the other agents already said on air (handed over by the orchestrator)."""
        studio = ("\nSTUDIO NOTES (already said on air by the other agents; do not ask them again): "
                  + " | ".join(notes)) if notes else ""
        raw = self.agent.ask(f"MOMENT: {moment}\nVIEWER: {viewer.describe()}{studio}")
        try:
            plan = json.loads(raw)
        except json.JSONDecodeError:
            return {"headline": raw.strip(), "highlights": [], "overlays": [],
                    "agent_requests": [], "alert": None, "dropped_highlights": []}
        # Guardrail: keep only highlights that point to a real moment, in match order.
        real = {m["moment_id"]: m for m in self.tools._moments()}
        kept = [h | {"minute": real[h["moment_id"]]["minute"], "type": real[h["moment_id"]]["type"]}
                for h in plan["highlights"] if h["moment_id"] in real]
        plan["dropped_highlights"] = [h["moment_id"] for h in plan["highlights"] if h["moment_id"] not in real]
        # Guardrail: the goals that changed the course of the match are always shown.
        # At full time every goal is in the reel.
        picked = {h["moment_id"] for h in kept}
        every_goal = moment in ("FULL_TIME", "HIGHLIGHTS")
        for m in real.values():
            decisive = m["type"] == "goal" and (every_goal or any(
                w in m["description"] for w in ("opener", "equaliser", "go-ahead goal")))
            if decisive and m["moment_id"] not in picked:
                kept.append({"moment_id": m["moment_id"], "title": m["description"].split(" (")[0],
                             "why_for_you": ("A goal that changed the course of the match." if not every_goal
                                             else "Every goal of the match is in your reel."),
                             "minute": m["minute"], "type": m["type"], "added_by_guardrail": True})
        # Keep the reel watchable: goals first, then the other moments, 8 at most.
        if len(kept) > MAX_HIGHLIGHTS:
            goals = [h for h in kept if h["type"] == "goal"]
            others = [h for h in kept if h["type"] != "goal"]
            kept = goals[:MAX_HIGHLIGHTS] + others[:max(0, MAX_HIGHLIGHTS - len(goals))]
        plan["highlights"] = sorted(kept, key=lambda h: h["moment_id"])
        plan["agent_requests"] = plan["agent_requests"][:2]
        # The stats panel is filled by Python from the events, never by the model.
        for overlay in plan["overlays"]:
            if overlay["kind"] == "match_stats":
                overlay["data"] = self.tools.match_stats_panel()
        return plan


def print_plan(viewer: ViewerProfile, moment: str, plan: dict, show_panel: bool = True) -> None:
    print(f"\n=== {moment} for {viewer.name} ({viewer.describe()}) ===")
    print(f"Headline: {plan['headline']}")
    if plan.get("alert"):
        print(f"ALERT: {plan['alert']}")
    print("Highlights:")
    for h in plan["highlights"]:
        added = " (added by guardrail)" if h.get("added_by_guardrail") else ""
        print(f"  {h['minute']}' [{h['type']}] {h['title']} - {h['why_for_you']}{added}")
    if plan.get("dropped_highlights"):
        print(f"  (dropped invented moment ids: {plan['dropped_highlights']})")
    print("Overlays:")
    for o in plan["overlays"]:
        print(f"  [{o['kind']}] {o['title']}: {o['content']}")
        if o.get("data") and show_panel:
            print_stats_panel(o["data"])


def print_stats_panel(panel: dict) -> None:
    """The stats panel as it will look on screen: home value | stat | away value."""
    print(f"      {panel['home']:>22} {panel['score']['home']}-{panel['score']['away']} {panel['away']}"
          f"   ({panel['minute']}')")
    for row in panel["rows"]:
        print(f"      {str(row['home']):>22}  {row['label']:^22}  {row['away']}")


def main():
    project = connect()
    league = build_league()
    ctx = MatchContext(simulate_match(get_team(league, "HAR"), get_team(league, "KES"), seed=7))
    producer = Producer(project, ctx)
    # The specialists the Producer can hand questions to (a preview of the orchestrator).
    specialists = {"stats": stats_agent.build(project, ctx, verbose=False),
                   "tactical": tactical_agent.build(project, ctx, verbose=False)}
    print(f"Agents ready: {producer.agent.label}, "
          + ", ".join(a.label for a in specialists.values()))

    viewers = [
        ViewerProfile("Harbourne fan following Ashworth", favourite_team="Harbourne Rovers",
                      followed_player="Jordan Ashworth"),
        ViewerProfile("Neutral analyst", audience="analyst"),
    ]
    for moment, minute in (("HALF_TIME", 45), ("FULL_TIME", 99)):
        ctx.advance_to(minute)
        for i, viewer in enumerate(viewers):
            plan = producer.plan(moment, viewer)
            # the stats panel is the same for every viewer: print it once per moment
            print_plan(viewer, moment, plan, show_panel=(i == 0))
            for req in plan["agent_requests"]:
                answer = specialists[req["agent"]].ask_from("producer", req["question"])
                print(f"  -> asks the {req['agent']} agent: {req['question']}\n     {answer}")


if __name__ == "__main__":
    main()
