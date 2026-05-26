import pandas as pd
from Common.contracts.sra_schema import SRAMetadataSchema
from Agents.workspace import Workspace
from Agents.session import Session
from Agents.tools.metadata_tools import metadata_registry


def _write_valid_metadata_csv(path, acc_list, extras=None):
    """Write a valid SRA metadata CSV with all required fields."""
    columns = list(SRAMetadataSchema.__fields__.keys())
    frame = pd.DataFrame({c: [""] * len(acc_list) for c in columns})
    frame["acc"] = acc_list
    frame["mbytes"] = [100] * len(acc_list)
    frame["avgspotlen"] = [75] * len(acc_list)
    frame["mbases"] = [1000] * len(acc_list)
    if extras:
        for col, values in extras.items():
            frame[col] = values
    frame.to_csv(path, index=False)
    return path


def test_extract_metadata_returns_handle(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    csv = root / "inputs" / "metadata.csv"
    _write_valid_metadata_csv(csv, ["S1", "S2"], {"group": ["a", "b"]})
    sess = Session.start(Workspace.open(root))

    res = metadata_registry.execute(sess, "extract_metadata", {"path": str(csv)})
    assert not res.is_error, res.error
    h = res.summary["handle"]
    md = sess.variables.get(h)
    assert "acc" in md.df.columns


def test_metadata_overview_takes_handle(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    csv = root / "inputs" / "metadata.csv"
    _write_valid_metadata_csv(csv, ["S1"], {"group": ["a"]})
    sess = Session.start(Workspace.open(root))

    r1 = metadata_registry.execute(sess, "extract_metadata", {"path": str(csv)})
    md_handle = r1.summary["handle"]
    r2 = metadata_registry.execute(sess, "metadata_overview", {"metadata": md_handle})
    assert not r2.is_error, r2.error
    assert r2.summary["type"] == "MetadataOverview"
