import pytest
from Common.contracts.selectors import TaxaSelector, SampleSelector, SubsetCriteria


def test_taxa_selector_is_frozen_and_holds_names():
    selector = TaxaSelector(rank="superkingdom", names=("Bacteria",))

    assert selector.rank == "superkingdom"
    assert selector.names == ("Bacteria",)


def test_subset_criteria_defaults_to_none():
    criteria = SubsetCriteria()

    assert criteria.taxa is None
    assert criteria.samples is None


def test_selectors_are_immutable():
    selector = SampleSelector(column="Group", values=("treatment",))

    with pytest.raises(Exception):
        selector.column = "other"
