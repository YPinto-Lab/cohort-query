# AbundanceMatrix Simplification + Polymorphic Builder — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rename `AbundanceMatrix` fields for precision, change `relative_abundance` semantics to use a rank-independent `total_reads` denominator, remove the `Unclassified_<rank>` bucket, and replace `AbundanceMatrixBuilder.build(df, rank)` with a polymorphic `@singledispatchmethod` that accepts either `(taxonomy_df)` for a full-detail pivot or `(matrix, rank)` for a lineage-collapse.

**Architecture:** `AbundanceMatrix` is a simple single-source-of-truth value object with five public surfaces (`matrix`, `total_reads`, `relative_abundance`, `taxa_lineage`, `samples`) and one mutator (`filter`). `AbundanceMatrixBuilder` becomes the only producer. `build(taxonomy_df)` pivots `self_count` over every taxonomy row so every observed taxon is a column and `total_reads` equals the row sum (true per-sample total). `build(matrix, rank)` collapses columns by their ancestor at `rank` via `_tax_id_lineage_lookup`, dropping columns whose lineage doesn't reach the rank.

**Tech Stack:** Python 3.11+, pandas, `functools.singledispatchmethod`, pytest.

**Spec reference:** `Docs/superpowers/specs/2026-05-28-abundance-matrix-two-state-design.md`

**Coordination point:** Task 8 updates `Agents/tools/taxonomy_tools.py`, which the in-flight `agent-state-awareness` session is also editing. Whichever branch merges second applies the two-line update.

---

## File Structure

**Modify:**
- `Engines/TaxonomyEngine/abundance_matrix.py` — full rewrite of class
- `Engines/TaxonomyEngine/abundance_matrix_builder.py` — full rewrite
- `Engines/TaxonomyEngine/cohort.py` — propagate renames
- `askslm/taxonomy.py` (facade) — remove `build_abundance_matrix`; export `AbundanceMatrixBuilder`
- `Accessors/matrix_writers/*` — propagate renames (`counts` → `matrix`, `relative` → `relative_abundance`)
- `Agents/tools/taxonomy_tools.py` — call new builder API
- `Tests/unit/taxonomy/test_abundance_matrix.py` — rewrite
- `Tests/unit/taxonomy/test_abundance_matrix_builder.py` — rewrite
- `Tests/unit/taxonomy/test_cohort.py` — propagate renames
- `Tests/unit/taxonomy/test_taxonomy_facade.py` — facade rename
- `Tests/unit/taxonomy/test_public_namespace.py` — facade rename
- `Tests/unit/taxonomy/test_matrix_writers.py` — propagate renames
- `Tests/e2e/test_taxonomy_flow.py` — new builder API
- `Notebooks/new.ipynb` — new builder API

**Reference (read-only):**
- `Engines/TaxonomyEngine/nested_set_lineage_resolver.py` — emits `tax_id` + 7 rank-name columns

---

## Task 1: Rewrite `AbundanceMatrix` tests for new field names + semantics

**Files:**
- Modify: `Tests/unit/taxonomy/test_abundance_matrix.py`

- [ ] **Step 1: Replace the test file in full**

```python
import pandas as pd
import pytest
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix


def _matrix():
    pivot = pd.DataFrame(
        {
            "superkingdom||Bacteria||2": [100, 80],
            "superkingdom||Viruses||10239": [40, 0],
        },
        index=pd.Index(["SRR1", "SRR2"], name="acc"),
    )
    total_reads = pd.Series([140, 80], index=pd.Index(["SRR1", "SRR2"], name="acc"))
    taxon_key_lookup = pd.DataFrame({
        "taxon_key": ["superkingdom||Bacteria||2", "superkingdom||Viruses||10239"],
        "tax_id": [2, 10239],
        "rank": ["superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses"],
    })
    tax_id_lineage_lookup = pd.DataFrame({
        "tax_id": [2, 10239],
        "superkingdom": ["Bacteria", "Viruses"],
    })
    return AbundanceMatrix(
        matrix=pivot,
        total_reads=total_reads,
        taxon_key_lookup=taxon_key_lookup,
        tax_id_lineage_lookup=tax_id_lineage_lookup,
    )


def test_samples_returns_matrix_index_as_list():
    matrix = _matrix()

    samples = matrix.samples

    assert samples == ["SRR1", "SRR2"]


def test_relative_abundance_uses_total_reads_as_denominator():
    matrix = _matrix()

    relative = matrix.relative_abundance

    assert abs(relative.loc["SRR1"].sum() - 1.0) < 1e-9
    assert abs(relative.loc["SRR1", "superkingdom||Bacteria||2"] - 100 / 140) < 1e-9


def test_relative_abundance_handles_zero_total_reads():
    pivot = pd.DataFrame(
        {"superkingdom||Bacteria||2": [0, 5]},
        index=pd.Index(["SRR_empty", "SRR_ok"], name="acc"),
    )
    total_reads = pd.Series([0, 5], index=pd.Index(["SRR_empty", "SRR_ok"], name="acc"))
    taxon_key_lookup = pd.DataFrame({
        "taxon_key": ["superkingdom||Bacteria||2"], "tax_id": [2],
        "rank": ["superkingdom"], "name": ["Bacteria"],
    })
    tax_id_lineage_lookup = pd.DataFrame({"tax_id": [2], "superkingdom": ["Bacteria"]})
    matrix = AbundanceMatrix(
        matrix=pivot, total_reads=total_reads,
        taxon_key_lookup=taxon_key_lookup, tax_id_lineage_lookup=tax_id_lineage_lookup,
    )

    relative = matrix.relative_abundance

    assert relative.loc["SRR_empty"].sum() == 0.0


def test_taxa_lineage_joins_lookup_and_lineage():
    matrix = _matrix()

    taxa_lineage = matrix.taxa_lineage

    bacteria = taxa_lineage[taxa_lineage["taxon_key"] == "superkingdom||Bacteria||2"].iloc[0]
    assert bacteria["superkingdom"] == "Bacteria"


def test_filter_keeps_requested_samples_by_default():
    matrix = _matrix()

    subset = matrix.filter(["SRR1"])

    assert subset.samples == ["SRR1"]
    assert subset.total_reads.loc["SRR1"] == 140


def test_filter_with_exclude_drops_listed_samples():
    matrix = _matrix()

    subset = matrix.filter(["SRR1"], exclude=True)

    assert subset.samples == ["SRR2"]


def test_filter_ignores_unknown_sample_ids():
    matrix = _matrix()

    subset = matrix.filter(["SRR1", "SRR_NOT_THERE"])

    assert subset.samples == ["SRR1"]


def test_filter_preserves_taxa_lineage_columns():
    matrix = _matrix()

    subset = matrix.filter(["SRR1"])

    assert list(subset.taxa_lineage.columns) == list(matrix.taxa_lineage.columns)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest Tests/unit/taxonomy/test_abundance_matrix.py -v`
Expected: All FAIL — `TypeError: __init__() got an unexpected keyword argument 'matrix'` or similar.

- [ ] **Step 3: Commit failing tests**

```bash
git add Tests/unit/taxonomy/test_abundance_matrix.py
git commit -m "test(taxonomy): rewrite AbundanceMatrix tests for new surface"
```

---

## Task 2: Rewrite `AbundanceMatrix` class

**Files:**
- Modify: `Engines/TaxonomyEngine/abundance_matrix.py`

- [ ] **Step 1: Replace the class in full**

```python
from __future__ import annotations

from collections.abc import Iterable
from functools import cached_property
from pathlib import Path

import pandas as pd


class AbundanceMatrix:
    """Samples x taxa counts at one collapsed view of a taxonomy."""

    def __init__(
        self,
        matrix: pd.DataFrame,
        total_reads: pd.Series,
        taxon_key_lookup: pd.DataFrame,
        tax_id_lineage_lookup: pd.DataFrame,
    ):
        self.matrix = matrix
        self.total_reads = total_reads
        self._taxon_key_lookup = taxon_key_lookup
        self._tax_id_lineage_lookup = tax_id_lineage_lookup

    @property
    def samples(self) -> list[str]:
        return list(self.matrix.index)

    @cached_property
    def relative_abundance(self) -> pd.DataFrame:
        denom = self.total_reads.reindex(self.matrix.index).replace(0, float("nan"))
        return self.matrix.div(denom, axis=0).fillna(0.0)

    @cached_property
    def taxa_lineage(self) -> pd.DataFrame:
        lookup = self._taxon_key_lookup.copy()
        lineage = self._tax_id_lineage_lookup.copy()
        lookup["tax_id"] = pd.to_numeric(lookup["tax_id"], errors="coerce")
        lineage["tax_id"] = pd.to_numeric(lineage["tax_id"], errors="coerce")
        return lookup.merge(lineage, on="tax_id", how="left")

    def filter(self, sample_ids: Iterable[str], exclude: bool = False) -> AbundanceMatrix:
        if exclude:
            return self._drop_samples(sample_ids)
        return self._keep_samples(sample_ids)

    def write(self, path: Path, fmt: str = "counts") -> Path:
        from Accessors.matrix_writers.matrix_writer_factory import MatrixWriterFactory

        return MatrixWriterFactory().create(fmt).write(self, Path(path))

    def _keep_samples(self, sample_ids: Iterable[str]) -> AbundanceMatrix:
        present = [s for s in sample_ids if s in self.matrix.index]
        return self._restrict(present)

    def _drop_samples(self, sample_ids: Iterable[str]) -> AbundanceMatrix:
        drop = set(sample_ids)
        kept = [s for s in self.matrix.index if s not in drop]
        return self._restrict(kept)

    def _restrict(self, sample_ids: list[str]) -> AbundanceMatrix:
        return AbundanceMatrix(
            matrix=self.matrix.reindex(sample_ids),
            total_reads=self.total_reads.reindex(sample_ids),
            taxon_key_lookup=self._taxon_key_lookup,
            tax_id_lineage_lookup=self._tax_id_lineage_lookup,
        )
```

- [ ] **Step 2: Run tests to verify they pass**

Run: `pytest Tests/unit/taxonomy/test_abundance_matrix.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 3: Commit**

```bash
git add Engines/TaxonomyEngine/abundance_matrix.py
git commit -m "refactor(taxonomy): rename AbundanceMatrix fields; add total_reads; rebuild filter"
```

---

## Task 3: Update `Cohort` and matrix writers for renames

**Files:**
- Modify: `Engines/TaxonomyEngine/cohort.py`
- Modify: `Accessors/matrix_writers/*` (every writer accessing `counts` or `relative`)
- Modify: `Tests/unit/taxonomy/test_matrix_writers.py`
- Modify: `Tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: List all callers of the old names**

Run: `grep -rn "\.counts\|\.relative\b\|\.taxa\b\|for_samples\|_lookup\b\|_lineage_df\b" Engines/ Accessors/ Tests/ askslm/ Agents/ Notebooks/ 2>&1`

Read the output — you need every hit to update consistently. Skip hits in `Tests/unit/taxonomy/test_abundance_matrix.py` (already done) and in this plan.

- [ ] **Step 2: Update `Cohort._filter_taxa` for new field names**

Edit `Engines/TaxonomyEngine/cohort.py`:
- Replace `matrix.taxa` → `matrix.taxa_lineage`
- Replace `matrix.counts` → `matrix.matrix`
- Replace `matrix._lookup` → `matrix._taxon_key_lookup`
- Replace `matrix._lineage_df` → `matrix._tax_id_lineage_lookup`
- The constructor call inside `_filter_taxa` becomes:

```python
return AbundanceMatrix(
    matrix=new_counts,
    total_reads=matrix.total_reads,
    taxon_key_lookup=matrix._taxon_key_lookup,
    tax_id_lineage_lookup=matrix._tax_id_lineage_lookup,
)
```

Rename `new_counts` to `new_matrix` while you're there.

Also replace `matrix.for_samples(...)` (line 26) → `matrix.filter(...)`.

Update `n_samples` / `n_taxa` to read `self.matrix.matrix.shape[...]`.

- [ ] **Step 3: Update each matrix writer**

For every file in `Accessors/matrix_writers/*.py`:
- `matrix.counts` → `matrix.matrix`
- `matrix.relative` → `matrix.relative_abundance`

- [ ] **Step 4: Update matrix-writer tests**

In `Tests/unit/taxonomy/test_matrix_writers.py`, propagate the same renames in constructor calls and assertions.

- [ ] **Step 5: Update cohort tests**

In `Tests/unit/taxonomy/test_cohort.py`, propagate renames. Anywhere a fixture constructs an `AbundanceMatrix` directly, switch to the new kwargs (`matrix=...`, `total_reads=...`, `taxon_key_lookup=...`, `tax_id_lineage_lookup=...`).

- [ ] **Step 6: Run the touched test files**

Run: `pytest Tests/unit/taxonomy/test_cohort.py Tests/unit/taxonomy/test_matrix_writers.py -v`
Expected: All PASS.

- [ ] **Step 7: Commit**

```bash
git add Engines/TaxonomyEngine/cohort.py Accessors/matrix_writers Tests/unit/taxonomy/test_cohort.py Tests/unit/taxonomy/test_matrix_writers.py
git commit -m "refactor(taxonomy): propagate AbundanceMatrix renames through Cohort and writers"
```

---

## Task 4: Rewrite `AbundanceMatrixBuilder` tests for polymorphic `build`

**Files:**
- Modify: `Tests/unit/taxonomy/test_abundance_matrix_builder.py`

- [ ] **Step 1: Replace the test file in full**

```python
import pandas as pd
import pytest
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder


def _long():
    return pd.DataFrame({
        "acc":         ["SRR1", "SRR1", "SRR2", "SRR2"],
        "tax_id":      [2,      561,    2,      561],
        "rank":        ["superkingdom", "genus", "superkingdom", "genus"],
        "name":        ["Bacteria", "Escherichia", "Bacteria", "Escherichia"],
        "total_count": [100, 60, 80, 70],
        "self_count":  [40,  60, 10, 70],
        "ileft":       [1, 3, 1, 3],
        "iright":      [8, 4, 8, 4],
    })


def test_build_from_df_pivots_every_taxon_row_with_self_count():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert isinstance(matrix, AbundanceMatrix)
    assert set(matrix.matrix.columns) == {
        "superkingdom||Bacteria||2",
        "genus||Escherichia||561",
    }
    assert matrix.matrix.loc["SRR1", "superkingdom||Bacteria||2"] == 40
    assert matrix.matrix.loc["SRR1", "genus||Escherichia||561"] == 60


def test_build_from_df_total_reads_is_row_sum_of_self_counts():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert matrix.total_reads.loc["SRR1"] == 100  # 40 + 60
    assert matrix.total_reads.loc["SRR2"] == 80   # 10 + 70


def test_build_from_df_relative_abundance_rows_sum_to_one():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert abs(matrix.relative_abundance.loc["SRR1"].sum() - 1.0) < 1e-9
    assert abs(matrix.relative_abundance.loc["SRR2"].sum() - 1.0) < 1e-9


def test_build_from_matrix_collapses_to_rank_via_lineage():
    full = AbundanceMatrixBuilder().build(_long())

    genus = AbundanceMatrixBuilder().build(full, "genus")

    assert set(genus.matrix.columns) == {"genus||Escherichia||561"}
    assert genus.matrix.loc["SRR1", "genus||Escherichia||561"] == 60
    assert genus.matrix.loc["SRR2", "genus||Escherichia||561"] == 70


def test_build_from_matrix_drops_columns_without_ancestor_at_rank():
    full = AbundanceMatrixBuilder().build(_long())

    species = AbundanceMatrixBuilder().build(full, "species")

    assert list(species.matrix.columns) == []


def test_build_from_matrix_total_reads_equals_row_sum_of_collapsed_matrix():
    full = AbundanceMatrixBuilder().build(_long())

    superkingdom = AbundanceMatrixBuilder().build(full, "superkingdom")

    assert superkingdom.total_reads.loc["SRR1"] == superkingdom.matrix.loc["SRR1"].sum()


def test_build_from_matrix_at_same_rank_is_idempotent():
    full = AbundanceMatrixBuilder().build(_long())
    genus_once = AbundanceMatrixBuilder().build(full, "genus")

    genus_twice = AbundanceMatrixBuilder().build(genus_once, "genus")

    pd.testing.assert_frame_equal(genus_twice.matrix, genus_once.matrix)


def test_build_rejects_unsupported_source_type():
    with pytest.raises(TypeError):
        AbundanceMatrixBuilder().build(42)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest Tests/unit/taxonomy/test_abundance_matrix_builder.py -v`
Expected: All FAIL.

- [ ] **Step 3: Commit failing tests**

```bash
git add Tests/unit/taxonomy/test_abundance_matrix_builder.py
git commit -m "test(taxonomy): rewrite AbundanceMatrixBuilder tests for polymorphic build"
```

---

## Task 5: Rewrite `AbundanceMatrixBuilder` with polymorphic `build`

**Files:**
- Modify: `Engines/TaxonomyEngine/abundance_matrix_builder.py`

- [ ] **Step 1: Replace the class in full**

Overwrite `Engines/TaxonomyEngine/abundance_matrix_builder.py` with:

```python
from __future__ import annotations

from functools import singledispatchmethod

import pandas as pd

from .abundance_matrix import AbundanceMatrix
from .nested_set_lineage_resolver import NestedSetLineageResolver

TAXON_KEY_SEP = "||"


class AbundanceMatrixBuilder:
    """Builds AbundanceMatrix from a taxonomy DataFrame or collapses an existing matrix to a rank."""

    def __init__(self) -> None:
        self._lineage_resolver = NestedSetLineageResolver()

    @singledispatchmethod
    def build(self, source, *args, **kwargs) -> AbundanceMatrix:
        raise TypeError(f"Cannot build AbundanceMatrix from {type(source).__name__}")

    @build.register
    def _build_from_taxonomy(self, taxonomy_df: pd.DataFrame) -> AbundanceMatrix:
        rows = self._rows_with_taxon_key(taxonomy_df)
        matrix = self._pivot_self_counts(rows)
        total_reads = matrix.sum(axis=1)
        taxon_key_lookup = self._lookup_from_rows(rows)
        tax_id_lineage_lookup = self._lineage_resolver.resolve(taxonomy_df)
        return AbundanceMatrix(matrix, total_reads, taxon_key_lookup, tax_id_lineage_lookup)

    @build.register
    def _build_from_matrix(self, source: AbundanceMatrix, rank: str) -> AbundanceMatrix:
        column_to_ancestor = self._column_to_rank_ancestor(source, rank)
        kept = self._kept_columns(source.matrix, column_to_ancestor)
        grouped = self._collapse_columns(source.matrix, kept, column_to_ancestor)
        new_matrix = self._rekey_to_taxon_keys(grouped, source._taxon_key_lookup, rank)
        total_reads = new_matrix.sum(axis=1)
        new_lookup = self._rank_lookup(source._taxon_key_lookup, rank, new_matrix.columns)
        return AbundanceMatrix(new_matrix, total_reads, new_lookup, source._tax_id_lineage_lookup)

    def _rows_with_taxon_key(self, taxonomy_df: pd.DataFrame) -> pd.DataFrame:
        rows = taxonomy_df.copy()
        rows["taxon_key"] = (
            rows["rank"].astype(str) + TAXON_KEY_SEP
            + rows["name"].astype(str) + TAXON_KEY_SEP
            + rows["tax_id"].astype(str)
        )
        return rows

    def _pivot_self_counts(self, rows: pd.DataFrame) -> pd.DataFrame:
        wide = rows.pivot_table(
            index="acc", columns="taxon_key", values="self_count",
            aggfunc="sum", fill_value=0,
        )
        return wide.astype(int)

    def _lookup_from_rows(self, rows: pd.DataFrame) -> pd.DataFrame:
        return rows[["taxon_key", "tax_id", "rank", "name"]].drop_duplicates(subset=["taxon_key"]).reset_index(drop=True)

    def _column_to_rank_ancestor(self, source: AbundanceMatrix, rank: str) -> dict[str, str | None]:
        lookup = source._taxon_key_lookup.set_index("taxon_key")
        lineage = source._tax_id_lineage_lookup.set_index("tax_id")
        ancestors: dict[str, str | None] = {}
        for taxon_key in source.matrix.columns:
            tax_id = lookup.loc[taxon_key, "tax_id"]
            ancestor_name = lineage.loc[tax_id, rank] if tax_id in lineage.index else None
            ancestors[taxon_key] = ancestor_name if isinstance(ancestor_name, str) else None
        return ancestors

    def _kept_columns(self, matrix: pd.DataFrame, ancestors: dict[str, str | None]) -> list[str]:
        return [c for c in matrix.columns if ancestors.get(c) is not None]

    def _collapse_columns(
        self,
        matrix: pd.DataFrame,
        kept: list[str],
        ancestors: dict[str, str | None],
    ) -> pd.DataFrame:
        if not kept:
            return pd.DataFrame(index=matrix.index)
        ancestor_map = {c: ancestors[c] for c in kept}
        return matrix[kept].rename(columns=ancestor_map).groupby(level=0, axis=1).sum().astype(int)

    def _rekey_to_taxon_keys(
        self,
        grouped: pd.DataFrame,
        full_lookup: pd.DataFrame,
        rank: str,
    ) -> pd.DataFrame:
        rank_rows = full_lookup[full_lookup["rank"] == rank].drop_duplicates(subset=["name"]).set_index("name")
        rename = {name: rank_rows.loc[name, "taxon_key"] for name in grouped.columns if name in rank_rows.index}
        return grouped.rename(columns=rename)

    def _rank_lookup(
        self,
        full_lookup: pd.DataFrame,
        rank: str,
        taxon_keys: pd.Index,
    ) -> pd.DataFrame:
        rank_rows = full_lookup[full_lookup["rank"] == rank]
        return rank_rows[rank_rows["taxon_key"].isin(list(taxon_keys))].reset_index(drop=True)
```

- [ ] **Step 2: Run builder tests**

Run: `pytest Tests/unit/taxonomy/test_abundance_matrix_builder.py -v`
Expected: All 8 tests PASS.

- [ ] **Step 3: Run the full taxonomy test suite**

Run: `pytest Tests/unit/taxonomy/ -v`
Expected: All PASS.

- [ ] **Step 4: Commit**

```bash
git add Engines/TaxonomyEngine/abundance_matrix_builder.py
git commit -m "refactor(taxonomy): polymorphic AbundanceMatrixBuilder.build via singledispatchmethod"
```

---

## Task 6: Remove `taxonomy.build_abundance_matrix` from the public facade

**Files:**
- Modify: `askslm/taxonomy.py`
- Modify: `Tests/unit/taxonomy/test_taxonomy_facade.py`
- Modify: `Tests/unit/taxonomy/test_public_namespace.py`

- [ ] **Step 1: Inspect the current facade**

Run: `cat askslm/taxonomy.py`

Identify the current `build_abundance_matrix` function and what's in `__all__`.

- [ ] **Step 2: Remove the function; export the builder**

Edit `askslm/taxonomy.py`:
- Delete the `build_abundance_matrix` function definition.
- Add `from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder` at the top.
- Add `"AbundanceMatrixBuilder"` to `__all__`.
- Remove `"build_abundance_matrix"` from `__all__`.

- [ ] **Step 3: Update facade tests**

In `Tests/unit/taxonomy/test_taxonomy_facade.py`, find every test referencing `taxonomy.build_abundance_matrix(...)` and replace with `taxonomy.AbundanceMatrixBuilder().build(taxonomy_df)` (or `.build(prev_matrix, rank)` where applicable). Update assertions to match new field names.

In `Tests/unit/taxonomy/test_public_namespace.py`, swap the `build_abundance_matrix` reference for `AbundanceMatrixBuilder`.

- [ ] **Step 4: Run facade tests**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_facade.py Tests/unit/taxonomy/test_public_namespace.py -v`
Expected: All PASS.

- [ ] **Step 5: Commit**

```bash
git add askslm/taxonomy.py Tests/unit/taxonomy/test_taxonomy_facade.py Tests/unit/taxonomy/test_public_namespace.py
git commit -m "refactor(taxonomy): expose AbundanceMatrixBuilder; remove build_abundance_matrix facade"
```

---

## Task 7: Update the E2E flow and the notebook

**Files:**
- Modify: `Tests/e2e/test_taxonomy_flow.py`
- Modify: `Notebooks/new.ipynb`

- [ ] **Step 1: Find calls to the old API**

Run: `grep -n "build_abundance_matrix\|\.counts\|\.relative\b\|for_samples\|\.taxa\b" Tests/e2e/test_taxonomy_flow.py Notebooks/new.ipynb`

- [ ] **Step 2: Update the e2e test**

Replace each `taxonomy.build_abundance_matrix(df, rank="X")` with:

```python
builder = taxonomy.AbundanceMatrixBuilder()
matrix = builder.build(builder.build(df), "X")
```

Replace `.counts` → `.matrix`, `.relative` → `.relative_abundance`, `.taxa` → `.taxa_lineage`, `.for_samples(...)` → `.filter(...)`.

- [ ] **Step 3: Update the notebook**

Open `Notebooks/new.ipynb` in JupyterLab or edit the JSON directly. Apply the same replacements in every cell that uses the old API. Re-run cells from top to bottom to verify they execute cleanly.

- [ ] **Step 4: Run the e2e test**

Run: `pytest Tests/e2e/test_taxonomy_flow.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add Tests/e2e/test_taxonomy_flow.py Notebooks/new.ipynb
git commit -m "refactor(taxonomy): migrate e2e flow and notebook to AbundanceMatrixBuilder"
```

---

## Task 8: Update the agent tool wrapper (coordination point)

**Files:**
- Modify: `Agents/tools/taxonomy_tools.py`

> **Coordination warning:** The in-flight `agent-state-awareness` branch is also editing this file. Before this task runs, fetch / rebase / merge the other branch's changes if they have landed. If merge conflicts exist, resolve them and adapt the two-line update below to whatever final shape the agent-state-awareness work has settled on.

- [ ] **Step 1: Find the current call site**

Run: `grep -n "build_abundance_matrix" Agents/tools/taxonomy_tools.py`

Expected: One call line inside a `build_abundance_matrix` tool wrapper.

- [ ] **Step 2: Update the call**

Replace the call (e.g. `taxonomy.build_abundance_matrix(taxonomy_df, rank=rank)`) with:

```python
builder = taxonomy.AbundanceMatrixBuilder()
matrix = builder.build(builder.build(taxonomy_df), rank)
```

Adjust the import line at the top of the file if needed.

- [ ] **Step 3: Run agent tests**

Run: `pytest Tests/agent/ -v`
Expected: PASS (modulo any pre-existing failures unrelated to this work — note them, do not fix them here).

- [ ] **Step 4: Commit**

```bash
git add Agents/tools/taxonomy_tools.py
git commit -m "refactor(agents): tool wrapper uses AbundanceMatrixBuilder.build"
```

---

## Task 9: Full test sweep

- [ ] **Step 1: Run everything**

Run: `pytest -v`
Expected: PASS across the board. If anything fails, the failure is in a caller you missed in Task 3 — `grep` again for the old names and update.

- [ ] **Step 2: Final commit if any cleanup**

```bash
git status   # should be clean
```

If anything is uncommitted, review and commit with `refactor(taxonomy): post-refactor cleanup`.

---

## Self-Review Checklist (run before declaring done)

- [ ] No occurrences of `AbundanceMatrix.counts` / `.relative` / `.taxa` / `for_samples` anywhere except inside string literals in tests asserting absence: `grep -rn "\.counts\b\|\.relative\b\|\.taxa\b\|for_samples" --include="*.py" .`
- [ ] No occurrences of `_lookup` or `_lineage_df` as attribute access (only `_taxon_key_lookup` / `_tax_id_lineage_lookup`)
- [ ] No `Unclassified_` string anywhere in production code: `grep -rn "Unclassified_" Engines/ askslm/ Agents/ Accessors/`
- [ ] `taxonomy.build_abundance_matrix` is not exported: `grep -n "build_abundance_matrix" askslm/taxonomy.py` returns no hits
- [ ] `pytest` exits 0
