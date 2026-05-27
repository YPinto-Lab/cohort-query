import os
import pandas as pd
import pytest

from Agents.agent import Agent
from Agents.workspace import Workspace
from Agents.llm_client import AnthropicClient

pytestmark = pytest.mark.llm


@pytest.fixture
def workspace(tmp_path):
    root = tmp_path / "ABX"; (root / "inputs").mkdir(parents=True)
    pd.DataFrame({"acc":["S1","S2"],"group":["a","b"]}).to_csv(root/"inputs"/"metadata.csv", index=False)
    return Workspace.open(root)


def _trajectory(events) -> list[str]:
    return [e.payload["tool"] for e in events if e.type == "tool_call"]


def test_metadata_summarization_calls_extract_and_overview(workspace):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    agent = Agent(workspace=workspace, llm=AnthropicClient())
    events = list(agent.chat("Summarize the metadata in this workspace."))
    traj = _trajectory(events)
    assert "extract_metadata" in traj
    assert "metadata_overview" in traj
    assert events[-1].type == "assistant_final"


def test_lists_workspace_inputs_when_asked(workspace):
    if not os.environ.get("ANTHROPIC_API_KEY"):
        pytest.skip("ANTHROPIC_API_KEY not set")
    agent = Agent(workspace=workspace, llm=AnthropicClient())
    events = list(agent.chat("What files are in this workspace?"))
    traj = _trajectory(events)
    assert "list_workspace_inputs" in traj
