"""Stats Agent: answers questions about a live match using matchsim tools.

Run from the repository root:
    python -m agents.stats_agent
"""
from __future__ import annotations

import json
import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

from agents.match_tools import TOOL_SCHEMAS, MatchContext
from matchsim import build_league, get_team, simulate_match

AGENT_NAME = "stats-agent"

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
- Compare goals with xG: more goals than xG means clinical (or lucky), fewer means wasteful
  (or a goalkeeper in form). Only call a team clinical if goals clearly exceed xG.
- Only explain WHY something happened if a tool says so. Do not invent causes
  (e.g. do not claim pressing created chances unless the data shows it).
- Momentum is given in words (which team it favours, and how strongly): report it that way.
- Be concise: three to five sentences unless asked for more. No bullet lists, no markdown.
- If a tool returns an error, use what it suggests (e.g. the candidate names) or say
  that the information is not available.
"""


def build_agent(project: AIProjectClient):
    """Create (or add a new version of) the Stats Agent in Foundry."""
    tools = [FunctionTool(name=t["name"], description=t["description"],
                          parameters=t["parameters"], strict=True)
             for t in TOOL_SCHEMAS]
    return project.agents.create_version(
        agent_name=AGENT_NAME,
        definition=PromptAgentDefinition(
            model=os.environ["FOUNDRY_MODEL"],
            instructions=INSTRUCTIONS,
            tools=tools,
        ),
    )


def run_tool(ctx: MatchContext, name: str, arguments: str) -> dict:
    """Execute the Python function that the model asked for."""
    args = json.loads(arguments or "{}")
    tool = getattr(ctx, name, None)
    if name not in {t["name"] for t in TOOL_SCHEMAS} or tool is None:
        return {"error": f"Unknown tool {name}."}
    try:
        return tool(**args)
    except Exception as exc:  # the model must get an answer, not a crash
        return {"error": f"{type(exc).__name__}: {exc}"}


def ask(openai, ctx: MatchContext, question: str, max_rounds: int = 6, verbose: bool = True) -> str:
    """Send a question and answer the model's tool calls until it gives a final text."""
    response = openai.responses.create(input=question)
    for _ in range(max_rounds):
        calls = [item for item in response.output if item.type == "function_call"]
        if not calls:
            return response.output_text
        outputs = []
        for call in calls:
            result = run_tool(ctx, call.name, call.arguments)
            if verbose:
                print(f"  [tool] {call.name}({call.arguments})")
            outputs.append({"type": "function_call_output", "call_id": call.call_id,
                            "output": json.dumps(result, ensure_ascii=False)})
        response = openai.responses.create(input=outputs, previous_response_id=response.id)
    return "Sorry, I could not finish the analysis."


def main():
    load_dotenv()
    project = AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                              credential=DefaultAzureCredential())
    agent = build_agent(project)
    print(f"Agent ready: {agent.name} (version {agent.version})\n")
    openai = project.get_openai_client(agent_name=agent.name)

    league = build_league()
    events = simulate_match(get_team(league, "HAR"), get_team(league, "KES"), seed=7)
    ctx = MatchContext(events)
    ctx.advance_to(60)
    print(f"Live: {ctx.home['name']} {ctx.score['home']}-{ctx.score['away']} "
          f"{ctx.away['name']} ({ctx.minute}')\n")

    questions = [
        "What's the story of the match so far?",
        "Was the last goal a good chance? Explain the xG.",
        "How is Théo Thibault playing?",
        "Who has been the better team since half-time?",
    ]
    for q in questions:
        print(f"Q: {q}")
        print(f"A: {ask(openai, ctx, q)}\n")


if __name__ == "__main__":
    main()
