import pandas as pd
from agent.workspace import Workspace
from agent.session import Session
from agent.llm_client import FakeLLMClient, ToolUse, AssistantText
from agent.loop import run
from agent.tools import default_registry


def _sess(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    return Session.start(Workspace.open(root))


def test_loop_executes_tool_and_returns_final_answer(tmp_path):
    sess = _sess(tmp_path)
    csv = sess.workspace.inputs_dir / "metadata.csv"
    pd.DataFrame({"acc": ["S1"], "g": ["a"]}).to_csv(csv, index=False)

    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="extract_metadata", input={"path": str(csv)})],
        [AssistantText(text="Loaded the metadata.")],
    ])
    events = list(run(sess, fake, default_registry, user_message="load it"))
    types = [e.type for e in events]
    assert types == ["user", "tool_call", "tool_result", "assistant_final"]
    assert events[-1].payload["content"] == "Loaded the metadata."


def test_loop_recovers_from_bad_args(tmp_path):
    sess = _sess(tmp_path)
    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="extract_metadata", input={"path": 123})],     # bad type
        [ToolUse(id="u2", name="extract_metadata", input={"path": "no.csv"})],  # bad file
        [AssistantText(text="Sorry, the file doesn't exist.")],
    ])
    events = list(run(sess, fake, default_registry, user_message="load it"))
    assert events[-1].type == "assistant_final"
    error_results = [e for e in events if e.type == "tool_result" and e.payload["is_error"]]
    assert len(error_results) == 2


def test_loop_step_limit(tmp_path, monkeypatch):
    sess = _sess(tmp_path)
    import agent.loop as loop_mod
    monkeypatch.setattr(loop_mod, "MAX_STEPS", 2)
    fake = FakeLLMClient(responses=[
        [ToolUse(id=f"u{i}", name="list_workspace_inputs", input={})] for i in range(5)
    ])
    events = list(run(sess, fake, default_registry, user_message="loop"))
    assert events[-1].type == "error"


def test_loop_emits_error_event_when_llm_raises(tmp_path):
    sess = _sess(tmp_path)

    class BoomLLM:
        def complete(self, messages, tools, system):
            raise RuntimeError("api down")

    events = list(run(sess, BoomLLM(), default_registry, user_message="hi"))
    assert events[-1].type == "error"
    assert "api down" in events[-1].payload["message"]
