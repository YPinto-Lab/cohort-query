# Refactor `Cohort.enrich` and `Cohort.split_by` for clean-code compliance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rework `enrich` and `split_by` in `Engines/TaxonomyEngine/cohort.py` to satisfy the clean-code bar: each function ≤ 10 lines, single responsibility, domain-meaningful names, no `else`, no private-attribute reach into `AbundanceMatrix`. Behavior must not regress — the existing test suite is the contract.

**Architecture decisions (already approved):**

1. Add a public `AbundanceMatrix.for_samples(sample_ids)` so `Cohort` no longer touches `matrix._lookup` / `matrix._lineage_df`. The smell also exists in `Cohort._reindex_matrix_rows`; both consumers collapse to one-liners after the new method exists. (`_filter_taxa` has the same pattern for columns; flagged as follow-up, out of scope here.)
2. Rename `enrich`'s `df` parameter to `extras`. Domain-meaningful and short.
3. `split_by` returns keys of the column's native dtype — drop the `str(label)` cast. Tests that assert string keys must update.
4. Extract `Cohort._require_column(column)` — shared validator used by `unique`, `enrich`, `split_by`.

**Tech Stack:** Python 3.11, pandas, pytest.

---

## File map

| File | Change |
|---|---|
| `Engines/TaxonomyEngine/abundance_matrix.py` | Add `for_samples(sample_ids) -> AbundanceMatrix` |
| `Engines/TaxonomyEngine/cohort.py` | Add `_require_column`; rewrite `enrich`, `split_by`; simplify `_reindex_matrix_rows`; rename param `df` → `extras` |
| `Tests/unit/taxonomy/test_abundance_matrix.py` (or nearest existing) | New tests for `for_samples` |
| `Tests/unit/taxonomy/test_cohort.py` | Update key-type assertion on `split_by`; update param-name reference if any test uses kwarg `df=` (none currently); add regression test for `enrich` with int-keyed `extras` |
| `Notebooks/new.ipynb` | Update call site if param name is positional (it is, no change needed) |

No new contracts. No new files. No public-API renames beyond `df` → `extras`.

---

## Task 1: `AbundanceMatrix.for_samples`

**Files:**
- Modify: `Engines/TaxonomyEngine/abundance_matrix.py`
- Test: `Tests/unit/taxonomy/test_abundance_matrix.py` (create test if file missing — check first)

- [ ] **Step 1: Write failing tests**

```python
def test_for_samples_keeps_only_requested_rows():
    arrange
    matrix = AbundanceMatrixBuilder().build(_long_df(), rank="superkingdom")

    act
    subset = matrix.for_samples(["SRR1", "SRR3"])

    assert list(subset.counts.index) == ["SRR1", "SRR3"]


def test_for_samples_ignores_unknown_ids():
    matrix = AbundanceMatrixBuilder().build(_long_df(), rank="superkingdom")

    subset = matrix.for_samples(["SRR1", "SRR_NOT_THERE"])

    assert list(subset.counts.index) == ["SRR1"]


def test_for_samples_preserves_taxa_lookup():
    matrix = AbundanceMatrixBuilder().build(_long_df(), rank="superkingdom")

    subset = matrix.for_samples(["SRR1"])

    assert list(subset.taxa.columns) == list(matrix.taxa.columns)
```

Verify they fail with `AttributeError: 'AbundanceMatrix' object has no attribute 'for_samples'`.

- [ ] **Step 2: Implement**

In `abundance_matrix.py`:

```python
from collections.abc import Iterable

def for_samples(self, sample_ids: Iterable[str]) -> "AbundanceMatrix":
    present = [s for s in sample_ids if s in self.counts.index]
    new_counts = self.counts.reindex(present)
    return AbundanceMatrix(counts=new_counts, lookup=self._lookup, lineage_df=self._lineage_df)
```

- [ ] **Step 3: Run tests — green**

- [ ] **Step 4: Commit**

```
feat(taxonomy): AbundanceMatrix.for_samples(sample_ids) row-subset helper
```

---

## Task 2: Refactor `Cohort.split_by` to use `for_samples`, preserve key dtype

**Files:**
- Modify: `Engines/TaxonomyEngine/cohort.py`
- Test: `Tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: Update the existing `split_by` test that asserts dict-key type**

Currently: `assert set(parts.keys()) == {"treatment", "control"}` — passes because `str(label)` casts. Native column values are already strings here, so the assertion stays valid. Add a new test that exercises int-typed keys:

```python
def test_split_by_preserves_native_key_dtype():
    md = Metadata(df=pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "cluster_id": [1, 2, 1],
        "assay_type": ["WGS", "WGS", "WGS"],
    }))
    cohort = Cohort(matrix=_matrix(), metadata=md)

    parts = cohort.split_by("cluster_id")

    assert set(parts.keys()) == {1, 2}
```

Verify it fails on current `str(label)` cast.

- [ ] **Step 2: Rewrite `split_by`**

```python
def split_by(self, column: str) -> dict:
    self._require_column(column)
    return {
        value: self._cohort_for_group(group_df)
        for value, group_df in self.metadata.df.dropna(subset=[column]).groupby(column)
    }

def _cohort_for_group(self, group_df: pd.DataFrame) -> "Cohort":
    sub_metadata = Metadata(df=group_df.reset_index(drop=True))
    sub_matrix = self.matrix.for_samples(group_df["acc"])
    return Cohort(matrix=sub_matrix, metadata=sub_metadata)
```

Return type narrows from `dict[str, Cohort]` to `dict` (key dtype follows the column).

- [ ] **Step 3: Run full cohort tests — all green**

- [ ] **Step 4: Commit**

```
refactor(cohort): split_by uses AbundanceMatrix.for_samples; preserves native key dtype
```

---

## Task 3: Extract `Cohort._require_column` and refactor `enrich`

**Files:**
- Modify: `Engines/TaxonomyEngine/cohort.py`
- Test: `Tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: No new behavior tests required — existing `enrich` and `unique` tests cover validation paths**

But check that the `enrich` test for `left_on not in metadata` still passes with the new shared validator (the error message changes from `"Column '{x}' not found in cohort metadata"` to whatever `_require_column` raises — pick wording compatible with current `pytest.raises(ValueError, match="missing_col")` assertions, which match on the column name only).

- [ ] **Step 2: Add `_require_column`**

```python
def _require_column(self, column: str) -> None:
    if column in self.metadata.df.columns:
        return
    raise ValueError(f"Column '{column}' not found in cohort metadata")
```

Uses guard clause, no `else`. 3 lines.

- [ ] **Step 3: Rewrite `enrich` and update `unique`**

```python
def enrich(self, extras: pd.DataFrame, *, left_on: str, right_on: str) -> Cohort:
    self._require_column(left_on)
    self._require_extras_column(extras, right_on)
    return Cohort(matrix=self.matrix, metadata=self._merged_metadata(extras, left_on, right_on))

def _require_extras_column(self, extras: pd.DataFrame, column: str) -> None:
    if column in extras.columns:
        return
    raise ValueError(f"Column '{column}' not found in extras")

def _merged_metadata(self, extras: pd.DataFrame, left_on: str, right_on: str) -> Metadata:
    deduped = extras.drop_duplicates(subset=[right_on])
    joined = self.metadata.df.merge(deduped, left_on=left_on, right_on=right_on, how="left")
    if right_on == left_on:
        return Metadata(df=joined)
    return Metadata(df=joined.drop(columns=[right_on]))
```

- `enrich`: 4 lines.
- `_merged_metadata`: 6 lines, no `else`, guard clause for the same-key case.
- Param name `df` → `extras` everywhere in the file (signature + any internal reference).

Update `unique` to use `_require_column`:

```python
def unique(self, column: str) -> list[str]:
    self._require_column(column)
    return sorted(self.metadata.df[column].dropna().unique().tolist())
```

- [ ] **Step 4: Run full cohort tests — green**

- [ ] **Step 5: Commit**

```
refactor(cohort): extract _require_column; enrich uses _merged_metadata; param df→extras
```

---

## Task 4: Simplify `Cohort._reindex_matrix_rows`

Now that `AbundanceMatrix.for_samples` exists, this helper is a one-liner. Inline it.

- [ ] **Step 1: Inline at the single call site in `filter`**

Before:
```python
new_matrix = self._reindex_matrix_rows(new_matrix, list(new_metadata.df["acc"]))
```

After:
```python
new_matrix = new_matrix.for_samples(new_metadata.df["acc"])
```

Delete the `_reindex_matrix_rows` staticmethod.

- [ ] **Step 2: Run full taxonomy test suite — green**

```bash
python -m pytest Tests/unit/taxonomy/ -v
```

- [ ] **Step 3: Commit**

```
refactor(cohort): inline _reindex_matrix_rows via AbundanceMatrix.for_samples
```

---

## Out of scope (follow-up candidates)

- `_filter_taxa` reaches into `matrix._lookup` / `_lineage_df` for column subsets — same encapsulation smell. Fix by adding `AbundanceMatrix.for_taxa(taxon_keys)` in a separate refactor.
- `Metadata` direct construction (`Metadata(df=...)`) at every callsite — could add `Metadata.from_df(...)` or a domain method, but adds API surface beyond this plan.

## Definition of done

- All clean-code rules satisfied for `enrich` and `split_by`: ≤ 10 lines, ≤ 3 params, no `else`, no banned vague names (`df`, `new_*`, `result`, `present`, `group_df`, `group_md`, `label`).
- No private-attribute access to `AbundanceMatrix._lookup` / `_lineage_df` from `cohort.py`.
- All existing `Tests/unit/taxonomy/test_cohort.py` tests still pass.
- New tests added: `AbundanceMatrix.for_samples` (3 cases), `split_by` native-dtype key (1 case).
- `Notebooks/new.ipynb` runs unchanged.
