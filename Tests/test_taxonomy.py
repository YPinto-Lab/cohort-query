"""ranks must carry ancestor names, not raw taxids -- nothing is ever classified AS
"Bacteria" itself, so a leaf-only name lookup can never resolve it."""
from cohortquery.taxonomy import _feature_row


def test_ranks_holds_ancestor_names_not_taxids():
    lineage = [1, 2, 1224]
    ranks = {2: "domain", 1224: "phylum"}
    names = {1224: "Proteobacteria", 2: "Bacteria", 1236: "Gammaproteobacteria"}

    row = _feature_row(1236, lineage, ranks, names)

    assert row["ranks"] == {"domain": "Bacteria", "phylum": "Proteobacteria"}


def test_ranks_falls_back_to_the_taxid_when_ete3_has_no_name_for_it():
    """Should never happen with a real NCBI dump, but a missing name must not crash."""
    lineage = [2]
    ranks = {2: "domain"}
    names = {}

    row = _feature_row(1236, lineage, ranks, names)

    assert row["ranks"] == {"domain": 2}


def test_lineage_stays_the_raw_taxid_tuple():
    """Other code walks numeric ancestry via `lineage`; only `ranks` gets names."""
    lineage = [1, 2, 1224]

    row = _feature_row(1236, lineage, {2: "domain"}, {2: "Bacteria"})

    assert row["lineage"] == (1, 2, 1224)
