from askslm import taxonomy
from askslm.contracts import FilterCriteria, TaxaSelector, SampleSelector


def test_taxonomy_exposes_core_callables():
    for name in ("load", "resolve", "build_abundance_matrix", "build_cohort"):
        assert callable(getattr(taxonomy, name))


def test_contracts_reexports_selectors():
    assert FilterCriteria().taxa is None
    assert TaxaSelector("superkingdom", ("Bacteria",)).rank == "superkingdom"
    assert SampleSelector("Group", ("a",)).column == "Group"
