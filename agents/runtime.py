"""Shared plumbing for every agent: Foundry connection, agent creation and the tool-call loop.

Each agent is defined by three things:
    - a name and instructions (its role and rules),
    - a "toolbox": a Python object whose methods are the tools,
    - the JSON schemas that describe those methods to the model.
"""
from __future__ import annotations

import json
import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import (FunctionTool, PromptAgentDefinition,
                                      PromptAgentDefinitionTextOptions, Reasoning,
                                      TextResponseFormatJsonSchema)
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv


def connect() -> AIProjectClient:
    """Open a client on the Foundry project defined in .env."""
    load_dotenv()
    return AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                           credential=DefaultAzureCredential())


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
                 reasoning_effort: str | None = None, output_schema: dict | None = None):
        self.definition = create_agent(project, name, instructions, schemas,
                                       reasoning_effort, output_schema)
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
