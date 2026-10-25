"""Shared plumbing for every agent: Foundry connection, agent creation and the tool-call loop.

Each agent is defined by three things:
    - a name and instructions (its role and rules),
    - a "toolbox": a Python object whose methods are the tools,
    - the JSON schemas that describe those methods to the model.
"""
from __future__ import annotations

import json
import os
import threading
import time

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (FunctionTool, PromptAgentDefinition,
                                      PromptAgentDefinitionTextOptions, Reasoning,
                                      TextResponseFormatJsonSchema)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv


class CachedCredential:
    """One sign-in token shared by every agent and every thread.

    DefaultAzureCredential gets its token from the Azure CLI (az). When several agents
    start at the same moment (three show plans in parallel at half-time), each one would
    launch `az` at once, and on Windows those parallel launches fail. Here the token is
    fetched once, under a lock, and reused until five minutes before it expires.
    """

    def __init__(self, inner):
        self.inner = inner
        self.lock = threading.Lock()
        self.cache = {}            # (method, scopes) -> token

    def _cached(self, method: str, scopes: tuple, fetch):
        with self.lock:
            token = self.cache.get((method, scopes))
            if token is None or token.expires_on - time.time() < 300:
                token = fetch()
                self.cache[(method, scopes)] = token
            return token

    def get_token(self, *scopes, **kwargs):
        return self._cached("token", scopes, lambda: self.inner.get_token(*scopes, **kwargs))

    def get_token_info(self, *scopes, options=None):
        return self._cached("info", scopes, lambda: self.inner.get_token_info(*scopes, options=options))

    def close(self):
        self.inner.close()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()


def connect() -> AIProjectClient:
    """Open a client on the Foundry project defined in .env."""
    load_dotenv()
    return AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                           credential=CachedCredential(DefaultAzureCredential()))


def create_agent(project: AIProjectClient, name: str, instructions: str, schemas: list[dict],
                 reasoning_effort: str | None = None, output_schema: dict | None = None):
    """Create the agent in Foundry, or add a new version if it already exists.

    reasoning_effort ("minimal", "low", "medium", "high") trades depth for speed:
    live commentary needs fast answers, analysis can think longer.
    output_schema: a JSON schema the answer must follow (structured output), so the
    app can read fields such as {"text": ..., "excitement": ...} reliably.
    """
    text = None
    if output_schema:
        text = PromptAgentDefinitionTextOptions(format=TextResponseFormatJsonSchema(
            name=f"{name.replace('-', '_')}_output", schema=output_schema, strict=True))
    tools = [FunctionTool(name=s["name"], description=s["description"],
                          parameters=s["parameters"], strict=True)
             for s in schemas]
    return project.agents.create_version(
        agent_name=name,
        definition=PromptAgentDefinition(
            model=os.environ["FOUNDRY_MODEL"], instructions=instructions, tools=tools,
            reasoning=Reasoning(effort=reasoning_effort) if reasoning_effort else None,
            text=text),
    )


REQUEST_HEADER = ("REQUEST FROM THE {sender} AGENT. Answer it fully and directly in at most five "
                  "sentences, for a broadcast audience. Never ask a question back and never offer "
                  "to do more: there is no conversation, only this answer.\n")


class Agent:
    """A Foundry agent plus the Python toolbox that answers its tool calls."""

    def __init__(self, project: AIProjectClient, name: str, instructions: str,
                 toolbox, schemas: list[dict], verbose: bool = True,
                 reasoning_effort: str | None = None, output_schema: dict | None = None,
                 checker=None):
        self.definition = create_agent(project, name, instructions, schemas,
                                       reasoning_effort, output_schema)
        # checker(answer) -> list of broken rules (see agents/lint.py). When it finds any,
        # the agent gets its answer back and writes it once more.
        self.checker = checker
        self.rewrites = 0
        self.openai = project.get_openai_client(agent_name=self.definition.name)
        self.toolbox = toolbox
        self.allowed = {s["name"] for s in schemas}
        self.verbose = verbose
        self.trace: list[dict] = []   # tool calls of the last question, for the UI

    @property
    def label(self) -> str:
        return f"{self.definition.name} (version {self.definition.version})"

    def ask_from(self, sender: str, question: str) -> str:
        """A question handed over by another agent (agent-to-agent delegation)."""
        return self.ask(REQUEST_HEADER.format(sender=sender.upper()) + question)

    def run_tool(self, name: str, arguments: str) -> dict:
        """Execute the Python method the model asked for (only whitelisted tools)."""
        if name not in self.allowed:
            return {"error": f"Unknown tool {name}."}
        try:
            return getattr(self.toolbox, name)(**json.loads(arguments or "{}"))
        except Exception as exc:  # the model must get an answer, not a crash
            return {"error": f"{type(exc).__name__}: {exc}"}

    def ask(self, question: str, max_rounds: int = 10) -> str:
        """Ask, then check the answer against the rules Python can verify; if it breaks
        some, send it back once with the list of problems."""
        answer = self._ask_once(question, max_rounds)
        if not self.checker:
            return answer
        problems = self.checker(answer)
        if not problems:
            return answer
        self.rewrites += 1
        if self.verbose:
            print(f"  [check] {self.definition.name}: " + " | ".join(problems))
        retry = (f"{question}\n\nYOUR DRAFT ANSWER:\n{answer}\n\nThe draft breaks these rules:\n- "
                 + "\n- ".join(problems)
                 + "\nWrite the answer again in the same format, fixing only these points. "
                   "Keep every fact that was right.")
        second = self._ask_once(retry, max_rounds)
        # keep the rewrite only if it is not worse than the draft
        return second if len(self.checker(second)) <= len(problems) else answer

    def _ask_once(self, question: str, max_rounds: int = 10) -> str:
        """Send a question and answer the tool calls until the model returns text."""
        self.trace = []
        response = self.openai.responses.create(input=question)
        for _ in range(max_rounds):
            calls = [item for item in response.output if item.type == "function_call"]
            if not calls:
                return response.output_text
            outputs = []
            for call in calls:
                result = self.run_tool(call.name, call.arguments)
                self.trace.append({"tool": call.name, "arguments": call.arguments})
                if self.verbose:
                    print(f"  [tool] {call.name}({call.arguments})")
                outputs.append({"type": "function_call_output", "call_id": call.call_id,
                                "output": json.dumps(result, ensure_ascii=False)})
            response = self.openai.responses.create(input=outputs,
                                                    previous_response_id=response.id)
        # Too many tool calls: ask for the answer with what has been gathered so far.
        calls = [item for item in response.output if item.type == "function_call"]
        final_input = [{"type": "function_call_output", "call_id": c.call_id,
                        "output": json.dumps({"error": "Tool budget used up."})} for c in calls]
        final_input.append({"role": "user", "content": "Stop calling tools. Answer now with the "
                                                       "data you already have."})
        response = self.openai.responses.create(input=final_input, previous_response_id=response.id)
        return response.output_text or "Sorry, I could not finish the analysis."
