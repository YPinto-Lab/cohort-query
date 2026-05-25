from askslm import taxonomy
from askslm.contracts import SubsetCriteria, TaxaSelector, SampleSelector


def test_taxonomy_exposes_core_callables():
    for name in ("load", "resolve", "build_abundance_matrix", "get_profile_subset"):
        assert callable(getattr(taxonomy, name))


def test_contracts_reexports_selectors():
    assert SubsetCriteria().taxa is None
    assert TaxaSelector("superkingdom", ("Bacteria",)).rank == "superkingdom"
    assert SampleSelector("Group", ("a",)).column == "Group"
