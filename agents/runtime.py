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
from azure.ai.projects.models import FunctionTool, PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv


def connect() -> AIProjectClient:
    """Open a client on the Foundry project defined in .env."""
    load_dotenv()
    return AIProjectClient(endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
                           credential=DefaultAzureCredential())


def create_agent(project: AIProjectClient, name: str, instructions: str, schemas: list[dict]):
    """Create the agent in Foundry, or add a new version if it already exists."""
    tools = [FunctionTool(name=s["name"], description=s["description"],
                          parameters=s["parameters"], strict=True)
             for s in schemas]
    return project.agents.create_version(
        agent_name=name,
        definition=PromptAgentDefinition(model=os.environ["FOUNDRY_MODEL"],
                                         instructions=instructions, tools=tools),
    )


class Agent:
    """A Foundry agent plus the Python toolbox that answers its tool calls."""

    def __init__(self, project: AIProjectClient, name: str, instructions: str,
                 toolbox, schemas: list[dict], verbose: bool = True):
        self.definition = create_agent(project, name, instructions, schemas)
        self.openai = project.get_openai_client(agent_name=self.definition.name)
        self.toolbox = toolbox
        self.allowed = {s["name"] for s in schemas}
        self.verbose = verbose
        self.trace: list[dict] = []   # tool calls of the last question, for the UI

    @property
    def label(self) -> str:
        return f"{self.definition.name} (version {self.definition.version})"

    def run_tool(self, name: str, arguments: str) -> dict:
        """Execute the Python method the model asked for (only whitelisted tools)."""
        if name not in self.allowed:
            return {"error": f"Unknown tool {name}."}
        try:
            return getattr(self.toolbox, name)(**json.loads(arguments or "{}"))
        except Exception as exc:  # the model must get an answer, not a crash
            return {"error": f"{type(exc).__name__}: {exc}"}

    def ask(self, question: str, max_rounds: int = 8) -> str:
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
        return "Sorry, I could not finish the analysis."
