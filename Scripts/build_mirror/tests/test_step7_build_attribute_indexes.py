"""classify_key/select_keys: pure functions, no DuckDB connection needed.

Found live 2026-10-06 via the translation-accuracy benchmark: a purely-numeric
jattr key (fecalcalprotectin_run) was excluded from BOTH indexes, when only the
values index exclusion was ever justified -- a numeric key's NAME is still a
valid presence-search target."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steps"))
from step7_build_attribute_indexes import classify_key, select_keys


def test_classify_key_numeric_values():
    assert classify_key("fecalcalprotectin_run", ["172.5", "158", "259"]) == "numeric"


def test_classify_key_administrative():
    assert classify_key("collecting_institution", ["University of X"]) == "administrative_metadata"


def test_classify_key_useful_text():
    assert classify_key("host_disease_sam", ["Crohn's disease", "ulcerative colitis"]) == "useful_text"


def _census(rows):
    return pd.DataFrame(rows, columns=["k", "occurrences", "klass"])


def test_select_keys_numeric_key_goes_to_presence_only():
    """The actual bug: fecalcalprotectin_run must reach attribute_keys_index
    (presence search) even though its values are too numeric to mean anything
    in attribute_values_index (content search)."""
    census = _census([
        ("fecalcalprotectin_run", 134, "numeric"),
        ("host_disease_sam", 5000, "useful_text"),
        ("collector_name", 9000, "administrative_metadata"),
    ])

    presence_keys, value_keys = select_keys(census)

    assert "fecalcalprotectin_run" in presence_keys
    assert "fecalcalprotectin_run" not in value_keys
    assert "host_disease_sam" in presence_keys
    assert "host_disease_sam" in value_keys
    assert "collector_name" not in presence_keys
    assert "collector_name" not in value_keys


def test_select_keys_sorts_by_occurrence_descending():
    census = _census([
        ("rare_sam", 10, "useful_text"),
        ("common_sam", 9000, "useful_text"),
    ])

    presence_keys, value_keys = select_keys(census)

    assert presence_keys == ["common_sam", "rare_sam"]
    assert value_keys == ["common_sam", "rare_sam"]
