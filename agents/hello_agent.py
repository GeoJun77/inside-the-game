"""Smoke test: create a Foundry agent and ask it a football question."""
import os

from azure.ai.projects import AIProjectClient
from azure.ai.projects.models import PromptAgentDefinition
from azure.identity import DefaultAzureCredential
from dotenv import load_dotenv

load_dotenv()

project = AIProjectClient(
    endpoint=os.environ["FOUNDRY_PROJECT_ENDPOINT"],
    credential=DefaultAzureCredential(),
)

agent = project.agents.create_version(
    agent_name="hello-pundit",
    definition=PromptAgentDefinition(
        model=os.environ["FOUNDRY_MODEL"],
        instructions="You are a sharp, concise Premier League pundit.",
    ),
)
print(f"Agent ready: {agent.name} (version {agent.version})")

openai = project.get_openai_client(agent_name=agent.name)
response = openai.responses.create(
    input="A striker scores from a shot worth 0.04 xG. In two sentences, what does that tell us?",
)
print(response.output_text)