import pytest
from Common.contracts.selectors import TaxaSelector, SampleSelector, FilterCriteria


def test_taxa_selector_is_frozen_and_holds_names():
    selector = TaxaSelector(rank="superkingdom", names=("Bacteria",))

    assert selector.rank == "superkingdom"
    assert selector.names == ("Bacteria",)


def test_filter_criteria_defaults_to_none():
    criteria = FilterCriteria()

    assert criteria.taxa is None
    assert criteria.samples is None


def test_selectors_are_immutable():
    selector = SampleSelector(column="Group", values=("treatment",))

    with pytest.raises(Exception):
        selector.column = "other"


def test_filter_criteria_sample_filters_defaults_to_empty_tuple():
    criteria = FilterCriteria()

    assert criteria.sample_filters == ()


def test_filter_criteria_accepts_multiple_sample_filters():
    filters = (
        SampleSelector(column="assay_type", values=("WGS",)),
        SampleSelector(column="Group", values=("treatment",)),
    )

    criteria = FilterCriteria(sample_filters=filters)

    assert criteria.sample_filters == filters


def test_sample_selector_exclude_defaults_to_false():
    selector = SampleSelector(column="Group", values=("control",))

    assert selector.exclude is False


def test_sample_selector_exclude_true_is_accepted():
    selector = SampleSelector(column="Group", values=("control",), exclude=True)

    assert selector.exclude is True
