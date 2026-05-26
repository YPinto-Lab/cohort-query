# Cohort enrichment and splitting — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add four new methods/properties to `Cohort` — `enrich`, `split_by`, `n_samples`/`n_taxa`, and `unique` — so an agent can manipulate cohorts without writing pandas code.

**Architecture:** All additions live in `Engines/TaxonomyEngine/cohort.py`. No new files. No new contracts. Tests go in the existing `tests/unit/taxonomy/test_cohort.py`.

**Tech Stack:** Python 3.11, pandas, pytest

---

## File map

| File | Change |
|---|---|
| `Engines/TaxonomyEngine/cohort.py` | Add `enrich`, `split_by`, `n_samples`, `n_taxa`, `unique` |
| `tests/unit/taxonomy/test_cohort.py` | Append tests for all additions |

---

## Fixtures (shared across tasks)

All tasks reuse the `_matrix()` and `_metadata_full()` helpers already defined in `tests/unit/taxonomy/test_cohort.py`:

```python
def _matrix():
    long_df = pd.DataFrame({
        "acc": ["SRR1", "SRR1", "SRR2", "SRR3"],
        "tax_id": [2, 10239, 2, 2],
        "rank": ["superkingdom", "superkingdom", "superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses", "Bacteria", "Bacteria"],
        "total_count": [100, 40, 80, 60],
        "self_count": [100, 40, 80, 60],
        "ileft": [1, 3, 1, 1],
        "iright": [2, 4, 2, 2],
    })
    return AbundanceMatrixBuilder().build(long_df, rank="superkingdom")

def _metadata_full():
    return Metadata(df=pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3", "SRR4"],
        "Group": ["treatment", "control", "treatment", "control"],
        "assay_type": ["WGS", "WGS", "AMPLICON", "WGS"],
    }))
```

The matrix covers samples `SRR1`, `SRR2`, `SRR3`. `_metadata_full()` includes `SRR4` (dropped on construction — not in matrix). The constructed cohort has 3 samples.

---

## Task 1: `n_samples` and `n_taxa` properties

**Files:**
- Modify: `Engines/TaxonomyEngine/cohort.py`
- Test: `tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/taxonomy/test_cohort.py`:

```python
def test_n_samples_returns_row_count():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    assert cohort.n_samples == 3


def test_n_taxa_returns_column_count():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    assert cohort.n_taxa == 2
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd /Users/yarintamam/Code/Ask-SLM
python -m pytest tests/unit/taxonomy/test_cohort.py::test_n_samples_returns_row_count tests/unit/taxonomy/test_cohort.py::test_n_taxa_returns_column_count -v
```

Expected: `FAILED` — `AttributeError: 'Cohort' object has no attribute 'n_samples'`

- [ ] **Step 3: Add properties to `Cohort`**

In `Engines/TaxonomyEngine/cohort.py`, add after the `write` method and before `_filter_taxa`:

```python
    @property
    def n_samples(self) -> int:
        return self.matrix.counts.shape[0]

    @property
    def n_taxa(self) -> int:
        return self.matrix.counts.shape[1]
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/taxonomy/test_cohort.py::test_n_samples_returns_row_count tests/unit/taxonomy/test_cohort.py::test_n_taxa_returns_column_count -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/cohort.py tests/unit/taxonomy/test_cohort.py
git commit -m "feat(cohort): add n_samples and n_taxa properties"
```

---

## Task 2: `unique(column)` method

**Files:**
- Modify: `Engines/TaxonomyEngine/cohort.py`
- Test: `tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/taxonomy/test_cohort.py`:

```python
def test_unique_returns_sorted_list_of_column_values():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    # cohort has SRR1 (WGS/treatment), SRR2 (WGS/control), SRR3 (AMPLICON/treatment)
    assert cohort.unique("assay_type") == ["AMPLICON", "WGS"]


def test_unique_raises_for_unknown_column():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    with pytest.raises(ValueError, match="not_a_col"):
        cohort.unique("not_a_col")
```

Add `import pytest` at the top of the test file if not already present.

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/taxonomy/test_cohort.py::test_unique_returns_sorted_list_of_column_values tests/unit/taxonomy/test_cohort.py::test_unique_raises_for_unknown_column -v
```

Expected: `FAILED` — `AttributeError: 'Cohort' object has no attribute 'unique'`

- [ ] **Step 3: Add `unique` to `Cohort`**

In `Engines/TaxonomyEngine/cohort.py`, add after the `n_taxa` property:

```python
    def unique(self, column: str) -> list[str]:
        if column not in self.metadata.df.columns:
            raise ValueError(f"Column '{column}' not found in metadata")
        return sorted(self.metadata.df[column].dropna().unique().tolist())
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/taxonomy/test_cohort.py::test_unique_returns_sorted_list_of_column_values tests/unit/taxonomy/test_cohort.py::test_unique_raises_for_unknown_column -v
```

Expected: `PASSED`

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/cohort.py tests/unit/taxonomy/test_cohort.py
git commit -m "feat(cohort): add unique(column) method"
```

---

## Task 3: `enrich(df, *, left_on, right_on)` method

**Files:**
- Modify: `Engines/TaxonomyEngine/cohort.py`
- Test: `tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/taxonomy/test_cohort.py`:

```python
def test_enrich_adds_columns_from_df_to_metadata():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    # cohort has SRR1 (Group=treatment), SRR2 (Group=control), SRR3 (Group=treatment)
    extra = pd.DataFrame({
        "Group": ["treatment", "control"],
        "Score": [1.0, 2.0],
    })

    enriched = cohort.enrich(extra, left_on="Group", right_on="Group")

    assert "Score" in enriched.metadata.df.columns
    assert enriched.metadata.df.set_index("acc").loc["SRR1", "Score"] == 1.0
    assert enriched.metadata.df.set_index("acc").loc["SRR2", "Score"] == 2.0


def test_enrich_broadcasts_subject_level_data_to_samples():
    # Subject-level df (one row per subject) joins to sample-level metadata
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    # Treat "Group" as a subject-like column with one label per value
    extra = pd.DataFrame({
        "SubjectID": ["treatment", "control"],
        "Cluster": ["A", "B"],
    })

    enriched = cohort.enrich(extra, left_on="Group", right_on="SubjectID")

    srr1_cluster = enriched.metadata.df.set_index("acc").loc["SRR1", "Cluster"]
    srr3_cluster = enriched.metadata.df.set_index("acc").loc["SRR3", "Cluster"]
    assert srr1_cluster == "A"
    assert srr3_cluster == "A"  # SRR1 and SRR3 are both "treatment"


def test_enrich_unmatched_samples_get_nan():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({
        "Group": ["treatment"],   # "control" is missing
        "Score": [99.0],
    })

    enriched = cohort.enrich(extra, left_on="Group", right_on="Group")

    srr2_score = enriched.metadata.df.set_index("acc").loc["SRR2", "Score"]
    import math
    assert math.isnan(srr2_score)


def test_enrich_preserves_matrix_unchanged():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({"Group": ["treatment", "control"], "Score": [1.0, 2.0]})

    enriched = cohort.enrich(extra, left_on="Group", right_on="Group")

    assert enriched.matrix is cohort.matrix


def test_enrich_raises_if_left_on_not_in_metadata():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({"Subject": ["x"], "Score": [1.0]})

    with pytest.raises(ValueError, match="missing_col"):
        cohort.enrich(extra, left_on="missing_col", right_on="Subject")


def test_enrich_raises_if_right_on_not_in_df():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    extra = pd.DataFrame({"Subject": ["x"], "Score": [1.0]})

    with pytest.raises(ValueError, match="missing_col"):
        cohort.enrich(extra, left_on="Group", right_on="missing_col")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/taxonomy/test_cohort.py -k "enrich" -v
```

Expected: `FAILED` — `AttributeError: 'Cohort' object has no attribute 'enrich'`

- [ ] **Step 3: Add `enrich` to `Cohort`**

In `Engines/TaxonomyEngine/cohort.py`, add `import pandas as pd` at the top if not already present, then add after the `unique` method:

```python
    def enrich(self, df: pd.DataFrame, *, left_on: str, right_on: str) -> Cohort:
        if left_on not in self.metadata.df.columns:
            raise ValueError(f"Column '{left_on}' not found in cohort metadata")
        if right_on not in df.columns:
            raise ValueError(f"Column '{right_on}' not found in provided DataFrame")
        new_df = self.metadata.df.merge(
            df.drop_duplicates(subset=[right_on]),
            left_on=left_on,
            right_on=right_on,
            how="left",
        )
        if right_on != left_on:
            new_df = new_df.drop(columns=[right_on])
        return Cohort(matrix=self.matrix, metadata=Metadata(df=new_df))
```

Note: `drop_duplicates(subset=[right_on])` prevents fan-out when multiple `df` rows share the same join key.

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/taxonomy/test_cohort.py -k "enrich" -v
```

Expected: all `PASSED`

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/cohort.py tests/unit/taxonomy/test_cohort.py
git commit -m "feat(cohort): add enrich(df, left_on, right_on) method"
```

---

## Task 4: `split_by(column)` method

**Files:**
- Modify: `Engines/TaxonomyEngine/cohort.py`
- Test: `tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/unit/taxonomy/test_cohort.py`:

```python
def test_split_by_returns_one_cohort_per_unique_value():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())
    # Group has "treatment" (SRR1, SRR3) and "control" (SRR2)

    parts = cohort.split_by("Group")

    assert set(parts.keys()) == {"treatment", "control"}


def test_split_by_samples_are_correct_per_group():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    parts = cohort.split_by("Group")

    assert list(parts["treatment"].metadata.df["acc"]) == ["SRR1", "SRR3"]
    assert list(parts["control"].metadata.df["acc"]) == ["SRR2"]


def test_split_by_matrix_rows_match_metadata_per_group():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    parts = cohort.split_by("Group")

    for label, sub in parts.items():
        assert list(sub.matrix.counts.index) == list(sub.metadata.df["acc"])


def test_split_by_nan_rows_are_excluded():
    import math
    md = Metadata(df=pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "Group": ["treatment", None, "treatment"],
        "assay_type": ["WGS", "WGS", "WGS"],
    }))
    cohort = Cohort(matrix=_matrix(), metadata=md)

    parts = cohort.split_by("Group")

    assert set(parts.keys()) == {"treatment"}
    assert list(parts["treatment"].metadata.df["acc"]) == ["SRR1", "SRR3"]


def test_split_by_raises_for_unknown_column():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    with pytest.raises(ValueError, match="no_such_col"):
        cohort.split_by("no_such_col")
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
python -m pytest tests/unit/taxonomy/test_cohort.py -k "split_by" -v
```

Expected: `FAILED` — `AttributeError: 'Cohort' object has no attribute 'split_by'`

- [ ] **Step 3: Add `split_by` to `Cohort`**

In `Engines/TaxonomyEngine/cohort.py`, add after the `enrich` method:

```python
    def split_by(self, column: str) -> dict[str, Cohort]:
        if column not in self.metadata.df.columns:
            raise ValueError(f"Column '{column}' not found in metadata")
        result = {}
        for label, group_df in self.metadata.df.dropna(subset=[column]).groupby(column):
            group_md = Metadata(df=group_df.reset_index(drop=True))
            sample_ids = list(group_df["acc"])
            present = [acc for acc in sample_ids if acc in self.matrix.counts.index]
            new_counts = self.matrix.counts.reindex(present)
            new_matrix = AbundanceMatrix(
                counts=new_counts,
                lookup=self.matrix._lookup,
                lineage_df=self.matrix._lineage_df,
            )
            result[str(label)] = Cohort(matrix=new_matrix, metadata=group_md)
        return result
```

- [ ] **Step 4: Run tests to verify they pass**

```bash
python -m pytest tests/unit/taxonomy/test_cohort.py -k "split_by" -v
```

Expected: all `PASSED`

- [ ] **Step 5: Run full cohort test suite**

```bash
python -m pytest tests/unit/taxonomy/test_cohort.py -v
```

Expected: all existing tests plus new tests `PASSED`. No regressions.

- [ ] **Step 6: Commit**

```bash
git add Engines/TaxonomyEngine/cohort.py tests/unit/taxonomy/test_cohort.py
git commit -m "feat(cohort): add split_by(column) method"
```
