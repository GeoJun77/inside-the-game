"""Stats Agent: answers questions about a live match using matchsim tools.

Run from the repository root:
    python -m agents.stats_agent
"""
from __future__ import annotations

from agents import lint
from agents.match_tools import TOOL_SCHEMAS, MatchContext
from agents.runtime import Agent, connect
from matchsim import build_league, get_team, simulate_match

NAME = "stats-agent"

INSTRUCTIONS = """You are the Stats Agent of a live football broadcast.
You answer questions about the match that is being played, for commentators and fans.

Rules:
- Always call a tool before quoting a number. Never invent or estimate statistics.
- For any question about a time window ("since half-time", "in the last 20 minutes",
  "in the first half"), call summarize_period with the exact minutes. The second half
  starts at minute 46, the first half is minutes 0 to 45.
- Always refer to players by their real name (e.g. "Théo Thibault"), never by their
  nationality or a nickname.
- Expected goals (xG):
  * For ONE shot, xG is a probability: 0.29 xG means a chance like this is scored about
    29 times out of 100.
  * For several shots (a team, a player, a period), xG is a NUMBER OF GOALS a typical
    finisher would expect: 1.46 xG means "about one and a half goals". Never turn a total
    xG into "times out of 100".
  * Define xG at most once, briefly, and only if the question is about a chance. Viewers
    hear many answers in a row.
- When you discuss a shot, give the two or three factors from "why_this_xg" that mattered most.
  To find an earlier shot (by player or minute), call list_shots, then get_shot_details with
  its event id.
- Compare goals with xG: more goals than xG means clinical (or lucky), fewer means wasteful
  (or a goalkeeper in form). Only call a team clinical if goals clearly exceed xG.
- Only explain WHY something happened if a tool says so. Do not invent causes
  (e.g. do not claim pressing created chances unless the data shows it).
- Momentum is given in words (which team it favours, and how strongly): report it that way.
- Be concise: three to five sentences unless asked for more. No bullet lists, no markdown.
- If a tool returns an error, use what it suggests (e.g. the candidate names) or say
  that the information is not available.
"""


def build(project, ctx: MatchContext, verbose: bool = True) -> Agent:
    return Agent(project, NAME, INSTRUCTIONS, toolbox=ctx, schemas=TOOL_SCHEMAS, verbose=verbose,
                 checker=lambda raw: lint.analyst(raw, ctx))


def main():
    project = connect()
    league = build_league()
    ctx = MatchContext(simulate_match(get_team(league, "HAR"), get_team(league, "KES"), seed=7))
    ctx.advance_to(60)
    agent = build(project, ctx)
    print(f"Agent ready: {agent.label}\n")
    print(f"Live: {ctx.home['name']} {ctx.score['home']}-{ctx.score['away']} "
          f"{ctx.away['name']} ({ctx.minute}')\n")

    for q in ["What's the story of the match so far?",
              "Was the last goal a good chance? Explain the xG.",
              "How is Théo Thibault playing?",
              "Who has been the better team since half-time?"]:
        print(f"Q: {q}")
        print(f"A: {agent.ask(q)}\n")


if __name__ == "__main__":
    main()
