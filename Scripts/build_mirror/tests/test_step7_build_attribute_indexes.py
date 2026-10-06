"""is_bookkeeping_key/select_keys: pure functions, no DuckDB connection needed.

Replaces the sampling-based key classifier removed 2026-10-06: sampling ~200K
rows out of ~39M made a low-occurrence key's classification a coin flip --
fecalcalprotectin_run (134 real rows) was excluded from search entirely, twice,
before this was traced to the sample simply never containing any of its rows.
The fix drops per-key value sampling: the only exclusion left is by KEY NAME
(ID_NAME_RE/ADMIN_KEY_RE), computed once against the full census, never against
a sample -- so it cannot miss a real key regardless of how rare it is."""
import sys
from pathlib import Path

import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "steps"))
from step7_build_attribute_indexes import is_bookkeeping_key, select_keys


def test_is_bookkeeping_key_true_for_admin_pattern():
    assert is_bookkeeping_key("collecting_institution") is True


def test_is_bookkeeping_key_true_for_id_name_pattern():
    assert is_bookkeeping_key("sample_accession") is True


def test_is_bookkeeping_key_false_for_biological_field():
    assert is_bookkeeping_key("host_disease_sam") is False


def test_is_bookkeeping_key_false_for_a_low_occurrence_numeric_field():
    """The actual bug: a rare, purely-numeric field like fecalcalprotectin_run
    must not be excluded just because its values look numeric -- this function
    never looks at values at all."""
    assert is_bookkeeping_key("fecalcalprotectin_run") is False


def _census(rows):
    return pd.DataFrame(rows, columns=["k", "occurrences"])


def test_select_keys_excludes_only_bookkeeping_names():
    census = _census([
        ("fecalcalprotectin_run", 134),
        ("host_disease_sam", 5000),
        ("collector_name", 9000),
    ])

    search_keys = select_keys(census)

    assert "fecalcalprotectin_run" in search_keys
    assert "host_disease_sam" in search_keys
    assert "collector_name" not in search_keys


def test_select_keys_never_drops_a_key_for_low_occurrence_alone():
    """A key with exactly 1 occurrence is still a real key -- occurrence count
    plays no role in eligibility, only the name pattern does."""
    census = _census([("rare_but_real_sam", 1)])

    assert select_keys(census) == ["rare_but_real_sam"]


def test_select_keys_sorts_by_occurrence_descending():
    census = _census([
        ("rare_sam", 10),
        ("common_sam", 9000),
    ])

    assert select_keys(census) == ["common_sam", "rare_sam"]
