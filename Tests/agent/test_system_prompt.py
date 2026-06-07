from agent.workspace import Workspace
from agent.session import Session
from agent.loop import build_system_prompt, IDENTITY_PREAMBLE


def test_build_system_prompt_has_all_three_layers(tmp_path):
    root = tmp_path / "ABC_study"
    (root / "1_build").mkdir(parents=True)
    (root / "1_build" / "build.md").write_text("assemble the table")
    sess = Session.start(Workspace.open(root))

    prompt = build_system_prompt(sess)

    assert IDENTITY_PREAMBLE in prompt      # identity preamble (layer 1)
    assert "self_count" in prompt           # operating manual
    assert "ABC_study" in prompt            # workspace snapshot
    assert "assemble the table" in prompt   # intent .md inlined by the snapshot
