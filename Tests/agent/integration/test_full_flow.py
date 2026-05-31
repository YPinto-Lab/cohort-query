import pandas as pd
import pytest
from Agents.agent import Agent
from Agents.workspace import Workspace
from Agents.llm_client import FakeLLMClient, ToolUse, AssistantText


def test_full_pipeline_with_scripted_llm(tmp_path):
    root = tmp_path / "ABX"; (root / "inputs").mkdir(parents=True)
    pd.DataFrame({"acc": ["S1","S2"], "g": ["a","b"]}).to_csv(root / "inputs" / "metadata.csv", index=False)
    pd.DataFrame({
        "acc": ["S1","S1","S2","S2"],
        "tax_id": [816, 562, 816, 1280],
        "total_count": [10, 5, 7, 12],
    }).to_csv(root / "inputs" / "taxonomy.csv", index=False)

    ws = Workspace.open(root)
    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="extract_metadata", input={"path": str(root / "inputs" / "metadata.csv")})],
        [ToolUse(id="u2", name="load_taxonomy",     input={"path": str(root / "inputs" / "taxonomy.csv")})],
        [ToolUse(id="u3", name="resolve_taxonomy",  input={"taxonomy": "tax_1"})],
        [ToolUse(id="u4", name="build_abundance_matrix", input={"taxonomy": "resolved_tax_1", "rank": "genus"})],
        [ToolUse(id="u5", name="build_cohort", input={"matrix": "matrix_1", "metadata": "meta_1"})],
        [AssistantText(text="Cohort built.")],
    ])
    agent = Agent(workspace=ws, llm=fake)
    events = list(agent.chat("build a genus cohort"))
    assert events[-1].type == "assistant_final"
    assert "cohort_1" in agent.session.variables.list_handles()


def test_run_python_produces_handle_for_skbio_distance(tmp_path):
    try:
        import skbio  # noqa: F401
    except ImportError:
        pytest.skip("scikit-bio not installed")

    root = tmp_path / "ABX"; (root / "inputs").mkdir(parents=True)
    pd.DataFrame({"acc": ["S1","S2"], "g": ["a","b"]}).to_csv(root / "inputs" / "metadata.csv", index=False)
    pd.DataFrame({
        "acc": ["S1","S1","S2","S2"],
        "tax_id": [816, 562, 816, 1280],
        "total_count": [10, 5, 7, 12],
    }).to_csv(root / "inputs" / "taxonomy.csv", index=False)
    ws = Workspace.open(root)

    code = (
        "from skbio.diversity import beta_diversity\n"
        "df = matrix_1.matrix\n"
        "bray = beta_diversity('braycurtis', df.values, ids=list(df.index))\n"
        "bray_df = pandas.DataFrame(bray.data, index=bray.ids, columns=bray.ids)\n"
    )
    fake = FakeLLMClient(responses=[
        [ToolUse(id="u1", name="load_taxonomy",            input={"path": str(root / "inputs" / "taxonomy.csv")})],
        [ToolUse(id="u2", name="resolve_taxonomy",         input={"taxonomy": "tax_1"})],
        [ToolUse(id="u3", name="build_abundance_matrix",   input={"taxonomy": "resolved_tax_1", "rank": "genus"})],
        [ToolUse(id="u4", name="run_python",               input={"code": code})],
        [AssistantText(text="Computed Bray-Curtis.")],
    ])
    agent = Agent(workspace=ws, llm=fake)
    events = list(agent.chat("compute bray-curtis"))
    assert events[-1].type == "assistant_final"
    handles = agent.session.variables.list_handles()
    assert any(h.startswith("bray_df") for h in handles)
