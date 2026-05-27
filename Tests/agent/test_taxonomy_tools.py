import pandas as pd
from Common.contracts.sra_schema import SRAMetadataSchema
from Agents.workspace import Workspace
from Agents.session import Session
from Agents.tools.taxonomy_tools import taxonomy_registry
from Agents.tools.metadata_tools import metadata_registry


def _make_tax_csv(path):
    pd.DataFrame({
        "acc": ["S1", "S1", "S2", "S2"],
        "tax_id": [816, 562, 816, 1280],
        "rank": ["genus", "genus", "genus", "species"],
        "name": ["Bacillus", "Escherichia", "Bacillus", "Staphylococcus"],
        "total_count": [10, 5, 7, 12],
        "self_count": [10, 5, 7, 12],
        "ilevel": [3, 3, 3, 4],
        "ileft": [1, 2, 1, 5],
        "iright": [2, 3, 2, 6],
        "bioproject": ["PRJ1", "PRJ1", "PRJ1", "PRJ1"],
    }).to_csv(path, index=False)


def _make_meta_csv(path):
    columns = list(SRAMetadataSchema.__fields__.keys())
    frame = pd.DataFrame({c: [""] * 2 for c in columns})
    frame["acc"] = ["S1", "S2"]
    frame["mbytes"] = [100, 200]
    frame["avgspotlen"] = [75, 75]
    frame["mbases"] = [1000, 2000]
    frame.to_csv(path, index=False)


def test_load_resolve_build_matrix_cohort_chain(tmp_path):
    root = tmp_path / "ws"; (root / "inputs").mkdir(parents=True)
    tax = root / "inputs" / "taxonomy.csv"; _make_tax_csv(tax)
    meta = root / "inputs" / "metadata.csv"; _make_meta_csv(meta)
    sess = Session.start(Workspace.open(root))

    r = taxonomy_registry.execute(sess, "load_taxonomy", {"path": str(tax)})
    assert not r.is_error
    tax_h = r.summary["handle"]

    r = taxonomy_registry.execute(sess, "resolve_taxonomy", {"taxonomy": tax_h})
    assert not r.is_error
    resolved_h = r.summary["handle"]

    r = taxonomy_registry.execute(
        sess, "build_abundance_matrix",
        {"taxonomy": resolved_h, "rank": "genus"},
    )
    assert not r.is_error
    matrix_h = r.summary["handle"]

    r = metadata_registry.execute(sess, "extract_metadata", {"path": str(meta)})
    md_h = r.summary["handle"]

    r = taxonomy_registry.execute(
        sess, "build_cohort", {"matrix": matrix_h, "metadata": md_h},
    )
    assert not r.is_error
    assert r.summary["type"] == "Cohort"
