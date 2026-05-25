# Taxonomy Lean Core — Implementation Plan (Plan 1 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the clean, tested taxonomy core — `load`, `resolve`, `build_abundance_matrix`, `get_profile_subset` — plus the shared contracts/facade they need, per `Docs/superpowers/specs/2026-05-25-askslm-lean-core-api-design.md`.

**Architecture:** Public facade `askslm.taxonomy` delegates to one-class-per-file engines in `Engines/TaxonomyEngine/`, which use thin accessors in `Accessors/`. Value objects (`AbundanceMatrix`, `ProfileSubset`, `ResolvedTaxonomy`) hold results; lineage is computed in-memory from nested-set columns (no persisted DB). Old modules stay untouched until Plan 3 deletes them, so this plan never breaks the existing tree.

**Tech Stack:** Python 3.11+, pandas, pandera, pytest, biom-format, numpy.

**Scope note:** This is Plan 1 of 3. Plan 2 = metadata core (`extract`, `overview`). Plan 3 = deletions of superseded modules, full `askslm` facade wiring, end-to-end docs/README.

**Clean-code rules (binding for every task):** one class per file; methods ≤10 lines doing one thing; ≤3 params (group into frozen dataclasses); no `else` (guard clauses / polymorphism); type hints; `pathlib.Path`; `logging` not `print`; banned words avoided (`data`, `info`, `manager`, `handler`, `util`, `helper`, `temp`, `obj`); tests follow Arrange/Act/Assert with blank lines.

---

## File Structure

**Create**
- `Common/contracts/selectors.py` — `TaxaSelector`, `SampleSelector`, `SubsetCriteria`
- `Common/contracts/taxonomy_results.py` — `ResolutionSummary`, `ResolvedTaxonomy`
- `Engines/TaxonomyEngine/__init__.py` — facade functions
- `Engines/TaxonomyEngine/taxonomy_resolver.py` — `TaxonomyResolver` (relocated)
- `Engines/TaxonomyEngine/nested_set_lineage_resolver.py` — `NestedSetLineageResolver`
- `Engines/TaxonomyEngine/abundance_matrix.py` — `AbundanceMatrix` value object
- `Engines/TaxonomyEngine/abundance_matrix_builder.py` — `AbundanceMatrixBuilder`
- `Engines/TaxonomyEngine/profile_subset.py` — `ProfileSubset` value object
- `Engines/TaxonomyEngine/profile_subset_builder.py` — `ProfileSubsetBuilder`
- `Accessors/TaxonomyAccessor/taxonomy_file_accessor.py` — `TaxonomyFileAccessor` (read taxonomy.csv)
- `Accessors/MergedDumpAccessor/__init__.py`, `merged_dump_accessor.py` — `MergedDumpAccessor` (read merged.dmp)
- `Accessors/matrix_writers/__init__.py`, `matrix_format_writer.py`, `matrix_writer_factory.py`, `counts_writer.py`, `relative_writer.py`, `maaslin_writer.py`, `biom_writer.py`
- `askslm/__init__.py`, `askslm/contracts.py` — public facade + contract re-exports
- `Tests/unit/taxonomy/` test modules; `Tests/e2e/test_taxonomy_flow.py`
- `Tests/fixtures/taxonomy_tiny.csv`, `Tests/fixtures/merged_tiny.dmp`

**Reuse unchanged:** `Common/contracts/sra_schema.py` (`SRATaxonomySchema`).

---

## Task 1: Selectors (frozen dataclasses)

**Files:**
- Create: `Common/contracts/selectors.py`
- Test: `Tests/unit/taxonomy/test_selectors.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_selectors.py
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_selectors.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'Common.contracts.selectors'`

- [ ] **Step 3: Write minimal implementation**

```python
# Common/contracts/selectors.py
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaxaSelector:
    rank: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class SampleSelector:
    column: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class SubsetCriteria:
    taxa: TaxaSelector | None = None
    samples: SampleSelector | None = None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_selectors.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Commit**

```bash
git add Common/contracts/selectors.py Tests/unit/taxonomy/test_selectors.py
git commit -m "feat(contracts): add taxa/sample subset selectors"
```

---

## Task 2: Resolution result DTOs

**Files:**
- Create: `Common/contracts/taxonomy_results.py`
- Test: `Tests/unit/taxonomy/test_taxonomy_results.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_taxonomy_results.py
import pandas as pd
from Common.contracts.taxonomy_results import ResolutionSummary, ResolvedTaxonomy


def test_resolution_summary_holds_counters():
    summary = ResolutionSummary(input_rows=10, rows_updated=2, unique_old_tax_ids_updated=1)

    assert summary.rows_updated == 2


def test_resolved_taxonomy_bundles_frames_and_summary():
    df = pd.DataFrame({"acc": ["a"], "tax_id": ["1"], "total_count": [5]})
    summary = ResolutionSummary(input_rows=1, rows_updated=0, unique_old_tax_ids_updated=0)

    result = ResolvedTaxonomy(df=df, changes_df=pd.DataFrame(), summary=summary)

    assert result.df.loc[0, "tax_id"] == "1"
    assert result.summary.input_rows == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_results.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# Common/contracts/taxonomy_results.py
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ResolutionSummary:
    input_rows: int
    rows_updated: int
    unique_old_tax_ids_updated: int


@dataclass(frozen=True)
class ResolvedTaxonomy:
    df: pd.DataFrame
    changes_df: pd.DataFrame
    summary: ResolutionSummary
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_results.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add Common/contracts/taxonomy_results.py Tests/unit/taxonomy/test_taxonomy_results.py
git commit -m "feat(contracts): add taxonomy resolution result DTOs"
```

---

## Task 3: TaxonomyFileAccessor (read taxonomy.csv)

**Files:**
- Create: `Accessors/TaxonomyAccessor/taxonomy_file_accessor.py`
- Test: `Tests/unit/taxonomy/test_taxonomy_file_accessor.py`
- Create fixture: `Tests/fixtures/taxonomy_tiny.csv`

- [ ] **Step 1: Create the fixture file**

```csv
# Tests/fixtures/taxonomy_tiny.csv
acc,tax_id,rank,name,total_count,self_count,ilevel,ileft,iright,bioproject
SRR1,2,superkingdom,Bacteria,100,0,1,1,8,PRJ1
SRR1,1224,phylum,Proteobacteria,60,0,2,2,5,PRJ1
SRR1,561,genus,Escherichia,60,60,3,3,4,PRJ1
SRR1,10239,superkingdom,Viruses,40,40,1,9,10,PRJ1
SRR2,2,superkingdom,Bacteria,80,0,1,1,4,PRJ1
SRR2,561,genus,Escherichia,80,80,3,2,3,PRJ1
```

- [ ] **Step 2: Write the failing test**

```python
# Tests/unit/taxonomy/test_taxonomy_file_accessor.py
from pathlib import Path
from Accessors.TaxonomyAccessor.taxonomy_file_accessor import TaxonomyFileAccessor

FIXTURE = Path("Tests/fixtures/taxonomy_tiny.csv")


def test_read_returns_validated_long_table():
    accessor = TaxonomyFileAccessor()

    df = accessor.read(FIXTURE)

    assert set(["acc", "tax_id", "rank", "name", "total_count", "ileft", "iright"]).issubset(df.columns)
    assert len(df) == 6
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_file_accessor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write minimal implementation**

```python
# Accessors/TaxonomyAccessor/taxonomy_file_accessor.py
from __future__ import annotations

from pathlib import Path

import pandas as pd

from Common.contracts.sra_schema import SRATaxonomySchema


class TaxonomyFileAccessor:
    """Reads taxonomy.csv and validates it against SRATaxonomySchema."""

    def read(self, path: Path) -> pd.DataFrame:
        frame = pd.read_csv(Path(path))
        return SRATaxonomySchema.validate(frame)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_file_accessor.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add Accessors/TaxonomyAccessor/taxonomy_file_accessor.py Tests/unit/taxonomy/test_taxonomy_file_accessor.py Tests/fixtures/taxonomy_tiny.csv
git commit -m "feat(taxonomy): add taxonomy.csv file accessor"
```

---

## Task 4: MergedDumpAccessor (read merged.dmp)

**Files:**
- Create: `Accessors/MergedDumpAccessor/__init__.py`, `Accessors/MergedDumpAccessor/merged_dump_accessor.py`
- Test: `Tests/unit/taxonomy/test_merged_dump_accessor.py`
- Create fixture: `Tests/fixtures/merged_tiny.dmp`

- [ ] **Step 1: Create the fixture file** (tab-pipe NCBI format: `old\t|\tnew\t|`)

```text
# Tests/fixtures/merged_tiny.dmp
999	|	561	|
888	|	2	|
```

- [ ] **Step 2: Write the failing test**

```python
# Tests/unit/taxonomy/test_merged_dump_accessor.py
from pathlib import Path
from Accessors.MergedDumpAccessor.merged_dump_accessor import MergedDumpAccessor

FIXTURE = Path("Tests/fixtures/merged_tiny.dmp")


def test_load_parses_old_to_new_map():
    accessor = MergedDumpAccessor()

    mapping = accessor.load(FIXTURE)

    assert mapping == {999: 561, 888: 2}
```

- [ ] **Step 3: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_merged_dump_accessor.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 4: Write minimal implementation** (relocated from `Accessors/TaxonomyAccessor/taxonomy_dump_accessor.py`, instance method, guard clauses)

```python
# Accessors/MergedDumpAccessor/__init__.py
from .merged_dump_accessor import MergedDumpAccessor

__all__ = ["MergedDumpAccessor"]
```

```python
# Accessors/MergedDumpAccessor/merged_dump_accessor.py
from __future__ import annotations

from pathlib import Path


class MergedDumpAccessor:
    """Parses NCBI merged.dmp into an old_taxid -> new_taxid map."""

    def load(self, path: Path) -> dict[int, int]:
        mapping: dict[int, int] = {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            self._add_line(line, mapping)
        return mapping

    def _add_line(self, line: str, mapping: dict[int, int]) -> None:
        parts = line.strip().split("\t|\t")
        if len(parts) < 2:
            return
        self._add_pair(parts[0], parts[1], mapping)

    def _add_pair(self, old_raw: str, new_raw: str, mapping: dict[int, int]) -> None:
        old_clean = old_raw.strip()
        new_clean = new_raw.replace("\t|", "").strip()
        if not old_clean.isdigit() or not new_clean.isdigit():
            return
        mapping[int(old_clean)] = int(new_clean)
```

- [ ] **Step 5: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_merged_dump_accessor.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add Accessors/MergedDumpAccessor/ Tests/unit/taxonomy/test_merged_dump_accessor.py Tests/fixtures/merged_tiny.dmp
git commit -m "feat(taxonomy): add merged.dmp accessor"
```

---

## Task 5: TaxonomyResolver (relocate, keep pure logic)

The existing `Engines/DatasetAssemblyEngine/TaxonomyResolver.py` is already pure and correct. Relocate it verbatim into `Engines/TaxonomyEngine/` and cover it with a focused test. (Plan 3 deletes the old copy.)

**Files:**
- Create: `Engines/TaxonomyEngine/taxonomy_resolver.py` (copy of existing `TaxonomyResolver`)
- Test: `Tests/unit/taxonomy/test_taxonomy_resolver.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_taxonomy_resolver.py
import pandas as pd
from Engines.TaxonomyEngine.taxonomy_resolver import TaxonomyResolver


def test_resolve_remaps_deprecated_id_and_aggregates():
    taxonomy_df = pd.DataFrame({
        "acc": ["SRR1", "SRR1"],
        "tax_id": ["999", "561"],
        "total_count": [10, 5],
    })

    resolved = TaxonomyResolver({999: 561}).resolve(taxonomy_df)

    row = resolved[resolved["tax_id"] == "561"]
    assert int(row["total_count"].iloc[0]) == 15


def test_summarize_reports_updated_rows():
    taxonomy_df = pd.DataFrame({
        "acc": ["SRR1"],
        "tax_id": ["999"],
        "total_count": [10],
    })

    summary, changes_df = TaxonomyResolver({999: 561}).summarize_resolution(taxonomy_df)

    assert summary["rows_updated"] == 1
    assert changes_df.iloc[0]["resolved_tax_id"] == "561"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Copy the implementation**

Copy the full contents of `Engines/DatasetAssemblyEngine/TaxonomyResolver.py` into `Engines/TaxonomyEngine/taxonomy_resolver.py` unchanged (class `TaxonomyResolver`, methods `resolve`, `summarize_resolution`, `_validate_required_columns`, `_reorder_existing_columns`).

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_resolver.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/taxonomy_resolver.py Tests/unit/taxonomy/test_taxonomy_resolver.py
git commit -m "feat(taxonomy): relocate TaxonomyResolver into TaxonomyEngine"
```

---

## Task 6: NestedSetLineageResolver (lineage without a DB)

Builds, per taxon, its ancestor name at each standard rank, using nested-set containment within each accession's tree (`ancestor.ileft <= node.ileft AND ancestor.iright >= node.iright`).

**Files:**
- Create: `Engines/TaxonomyEngine/nested_set_lineage_resolver.py`
- Test: `Tests/unit/taxonomy/test_nested_set_lineage_resolver.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_nested_set_lineage_resolver.py
import pandas as pd
from Engines.TaxonomyEngine.nested_set_lineage_resolver import NestedSetLineageResolver


def _tree():
    return pd.DataFrame({
        "acc": ["S", "S", "S"],
        "tax_id": [2, 1224, 561],
        "rank": ["superkingdom", "phylum", "genus"],
        "name": ["Bacteria", "Proteobacteria", "Escherichia"],
        "ileft": [1, 2, 3],
        "iright": [6, 5, 4],
    })


def test_genus_node_maps_to_bacteria_superkingdom():
    lineage_df = NestedSetLineageResolver().resolve(_tree())

    escherichia = lineage_df[lineage_df["tax_id"] == 561].iloc[0]
    assert escherichia["superkingdom"] == "Bacteria"
    assert escherichia["genus"] == "Escherichia"


def test_each_tax_id_appears_once():
    lineage_df = NestedSetLineageResolver().resolve(_tree())

    assert lineage_df["tax_id"].is_unique
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_nested_set_lineage_resolver.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# Engines/TaxonomyEngine/nested_set_lineage_resolver.py
from __future__ import annotations

import pandas as pd

STANDARD_RANKS = ("superkingdom", "phylum", "class", "order", "family", "genus", "species")


class NestedSetLineageResolver:
    """Maps each tax_id to its ancestor name at every standard rank."""

    def resolve(self, taxonomy_df: pd.DataFrame) -> pd.DataFrame:
        records: dict[int, dict[str, str]] = {}
        for _, group in taxonomy_df.groupby("acc"):
            self._resolve_group(group, records)
        return self._to_frame(records)

    def _resolve_group(self, group: pd.DataFrame, records: dict[int, dict[str, str]]) -> None:
        nodes = group.to_dict("records")
        for node in nodes:
            self._resolve_node(node, nodes, records)

    def _resolve_node(self, node: dict, nodes: list[dict], records: dict[int, dict[str, str]]) -> None:
        tax_id = int(node["tax_id"])
        if tax_id in records:
            return
        records[tax_id] = self._ancestor_ranks(node, nodes)

    def _ancestor_ranks(self, node: dict, nodes: list[dict]) -> dict[str, str]:
        ancestors = [c for c in nodes if c["ileft"] <= node["ileft"] and c["iright"] >= node["iright"]]
        return {a["rank"]: a["name"] for a in ancestors if a["rank"] in STANDARD_RANKS}

    def _to_frame(self, records: dict[int, dict[str, str]]) -> pd.DataFrame:
        rows = [{"tax_id": tax_id, **ranks} for tax_id, ranks in records.items()]
        return pd.DataFrame(rows, columns=["tax_id", *STANDARD_RANKS])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_nested_set_lineage_resolver.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/nested_set_lineage_resolver.py Tests/unit/taxonomy/test_nested_set_lineage_resolver.py
git commit -m "feat(taxonomy): add nested-set lineage resolver"
```

---

## Task 7: AbundanceMatrix value object

Holds `counts` (samples × taxon_key) and a taxon lookup `_lookup` (taxon_key, tax_id, rank, name). Computes `.relative` and lineage-bearing `.taxa` lazily. `.write` delegates to a writer factory (Task 11).

**Files:**
- Create: `Engines/TaxonomyEngine/abundance_matrix.py`
- Test: `Tests/unit/taxonomy/test_abundance_matrix.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_abundance_matrix.py
import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix


def _matrix():
    counts = pd.DataFrame(
        {"superkingdom||Bacteria||2": [100, 80], "superkingdom||Viruses||10239": [40, 0]},
        index=pd.Index(["SRR1", "SRR2"], name="acc"),
    )
    lookup = pd.DataFrame({
        "taxon_key": ["superkingdom||Bacteria||2", "superkingdom||Viruses||10239"],
        "tax_id": [2, 10239],
        "rank": ["superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses"],
    })
    lineage = pd.DataFrame({"tax_id": [2, 10239], "superkingdom": ["Bacteria", "Viruses"]})
    return AbundanceMatrix(counts=counts, lookup=lookup, lineage_df=lineage)


def test_relative_rows_sum_to_one():
    matrix = _matrix()

    relative = matrix.relative

    assert abs(relative.loc["SRR1"].sum() - 1.0) < 1e-9


def test_taxa_join_carries_superkingdom():
    matrix = _matrix()

    taxa = matrix.taxa

    bacteria = taxa[taxa["taxon_key"] == "superkingdom||Bacteria||2"].iloc[0]
    assert bacteria["superkingdom"] == "Bacteria"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_abundance_matrix.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# Engines/TaxonomyEngine/abundance_matrix.py
from __future__ import annotations

from functools import cached_property
from pathlib import Path

import pandas as pd


class AbundanceMatrix:
    """Samples x taxa counts with lazy relative values and lineage-bearing taxa lookup."""

    def __init__(self, counts: pd.DataFrame, lookup: pd.DataFrame, lineage_df: pd.DataFrame):
        self.counts = counts
        self._lookup = lookup
        self._lineage_df = lineage_df

    @cached_property
    def relative(self) -> pd.DataFrame:
        row_totals = self.counts.sum(axis=1).replace(0, pd.NA)
        return self.counts.div(row_totals, axis=0).fillna(0.0)

    @cached_property
    def taxa(self) -> pd.DataFrame:
        return self._lookup.merge(self._lineage_df, on="tax_id", how="left")

    def write(self, path: Path, fmt: str = "counts") -> Path:
        from Accessors.matrix_writers.matrix_writer_factory import MatrixWriterFactory

        return MatrixWriterFactory().create(fmt).write(self, Path(path))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_abundance_matrix.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/abundance_matrix.py Tests/unit/taxonomy/test_abundance_matrix.py
git commit -m "feat(taxonomy): add AbundanceMatrix value object"
```

---

## Task 8: AbundanceMatrixBuilder

Wraps the existing pivot logic and attaches the lineage table. Builds `counts`, `lookup`, and the lineage DataFrame, then returns an `AbundanceMatrix`.

**Files:**
- Create: `Engines/TaxonomyEngine/abundance_matrix_builder.py`
- Test: `Tests/unit/taxonomy/test_abundance_matrix_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_abundance_matrix_builder.py
import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder


def _long():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR1", "SRR2"],
        "tax_id": [2, 561, 2],
        "rank": ["superkingdom", "genus", "superkingdom"],
        "name": ["Bacteria", "Escherichia", "Bacteria"],
        "total_count": [100, 60, 80],
        "ileft": [1, 3, 1],
        "iright": [8, 4, 4],
    })


def test_build_returns_samples_by_taxa_counts():
    matrix = AbundanceMatrixBuilder().build(_long())

    assert matrix.counts.shape[0] == 2
    assert matrix.counts.index.name == "acc"


def test_build_attaches_lineage_to_taxa():
    matrix = AbundanceMatrixBuilder().build(_long())

    genus_row = matrix.taxa[matrix.taxa["tax_id"] == 561].iloc[0]
    assert genus_row["superkingdom"] == "Bacteria"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_abundance_matrix_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# Engines/TaxonomyEngine/abundance_matrix_builder.py
from __future__ import annotations

import pandas as pd

from .abundance_matrix import AbundanceMatrix
from .nested_set_lineage_resolver import NestedSetLineageResolver

TAXON_KEY_SEP = "||"


class AbundanceMatrixBuilder:
    """Pivots a long taxonomy table into an AbundanceMatrix with lineage."""

    def __init__(self) -> None:
        self._lineage_resolver = NestedSetLineageResolver()

    def build(self, taxonomy_df: pd.DataFrame) -> AbundanceMatrix:
        keyed = self._with_taxon_key(taxonomy_df)
        counts = self._pivot_counts(keyed)
        lookup = self._build_lookup(keyed)
        lineage_df = self._lineage_resolver.resolve(taxonomy_df)
        return AbundanceMatrix(counts=counts, lookup=lookup, lineage_df=lineage_df)

    def _with_taxon_key(self, taxonomy_df: pd.DataFrame) -> pd.DataFrame:
        keyed = taxonomy_df.copy()
        keyed["taxon_key"] = (
            keyed["rank"].astype(str) + TAXON_KEY_SEP
            + keyed["name"].astype(str) + TAXON_KEY_SEP
            + keyed["tax_id"].astype(str)
        )
        return keyed

    def _pivot_counts(self, keyed: pd.DataFrame) -> pd.DataFrame:
        grouped = keyed.groupby(["acc", "taxon_key"], as_index=False)["total_count"].sum()
        wide = grouped.pivot(index="acc", columns="taxon_key", values="total_count").fillna(0)
        return wide.astype(int)

    def _build_lookup(self, keyed: pd.DataFrame) -> pd.DataFrame:
        columns = ["taxon_key", "tax_id", "rank", "name"]
        return keyed[columns].drop_duplicates(subset=["taxon_key"]).reset_index(drop=True)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_abundance_matrix_builder.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/abundance_matrix_builder.py Tests/unit/taxonomy/test_abundance_matrix_builder.py
git commit -m "feat(taxonomy): add AbundanceMatrixBuilder with lineage attach"
```

---

## Task 9: ProfileSubset value object

Holds `profile_df` (already filtered) plus a reference to the full metadata for lazy aligned access.

**Files:**
- Create: `Engines/TaxonomyEngine/profile_subset.py`
- Test: `Tests/unit/taxonomy/test_profile_subset.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_profile_subset.py
import pandas as pd
from Engines.TaxonomyEngine.profile_subset import ProfileSubset


def test_metadata_df_aligns_to_profile_index():
    profile = pd.DataFrame({"t1": [1, 2]}, index=pd.Index(["SRR1", "SRR2"], name="acc"))
    metadata = pd.DataFrame({"acc": ["SRR1", "SRR2", "SRR3"], "Group": ["a", "b", "c"]})

    subset = ProfileSubset(profile_df=profile, full_metadata_df=metadata)

    assert list(subset.metadata_df["acc"]) == ["SRR1", "SRR2"]


def test_metadata_df_preserves_profile_order():
    profile = pd.DataFrame({"t1": [1, 2]}, index=pd.Index(["SRR2", "SRR1"], name="acc"))
    metadata = pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["a", "b"]})

    subset = ProfileSubset(profile_df=profile, full_metadata_df=metadata)

    assert list(subset.metadata_df["acc"]) == ["SRR2", "SRR1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_profile_subset.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# Engines/TaxonomyEngine/profile_subset.py
from __future__ import annotations

from functools import cached_property
from pathlib import Path

import pandas as pd


class ProfileSubset:
    """Filtered profile plus lazily aligned metadata, kept as two DataFrames."""

    def __init__(self, profile_df: pd.DataFrame, full_metadata_df: pd.DataFrame):
        self.profile_df = profile_df
        self._full_metadata_df = full_metadata_df

    @cached_property
    def metadata_df(self) -> pd.DataFrame:
        order = list(self.profile_df.index)
        indexed = self._full_metadata_df.set_index("acc")
        return indexed.reindex(order).dropna(how="all").reset_index()

    def write(self, out_dir: Path) -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return [self._write(out_dir, "profile.csv", self.profile_df, True),
                self._write(out_dir, "metadata.csv", self.metadata_df, False)]

    def _write(self, out_dir: Path, name: str, frame: pd.DataFrame, index: bool) -> Path:
        path = out_dir / name
        frame.to_csv(path, index=index)
        return path
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_profile_subset.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/profile_subset.py Tests/unit/taxonomy/test_profile_subset.py
git commit -m "feat(taxonomy): add ProfileSubset value object"
```

---

## Task 10: ProfileSubsetBuilder

Applies the taxa filter (via `matrix.taxa`) and the sample filter (via metadata), returning a `ProfileSubset`. No `else` — absent selectors short-circuit to "keep all" through small guard methods.

**Files:**
- Create: `Engines/TaxonomyEngine/profile_subset_builder.py`
- Test: `Tests/unit/taxonomy/test_profile_subset_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_profile_subset_builder.py
import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder
from Engines.TaxonomyEngine.profile_subset_builder import ProfileSubsetBuilder
from Common.contracts.selectors import SubsetCriteria, TaxaSelector, SampleSelector


def _matrix():
    long_df = pd.DataFrame({
        "acc": ["SRR1", "SRR1", "SRR2"],
        "tax_id": [2, 10239, 2],
        "rank": ["superkingdom", "superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses", "Bacteria"],
        "total_count": [100, 40, 80],
        "ileft": [1, 3, 1],
        "iright": [2, 4, 2],
    })
    return AbundanceMatrixBuilder().build(long_df)


def _metadata():
    return pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["treatment", "control"]})


def test_taxa_filter_keeps_only_bacteria_columns():
    criteria = SubsetCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)))

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert all("Bacteria" in col for col in subset.profile_df.columns)


def test_sample_filter_keeps_only_treatment_rows():
    criteria = SubsetCriteria(samples=SampleSelector(column="Group", values=("treatment",)))

    subset = ProfileSubsetBuilder().build(_matrix(), _metadata(), criteria)

    assert list(subset.profile_df.index) == ["SRR1"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_profile_subset_builder.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write minimal implementation**

```python
# Engines/TaxonomyEngine/profile_subset_builder.py
from __future__ import annotations

import pandas as pd

from Common.contracts.selectors import SampleSelector, SubsetCriteria, TaxaSelector
from .abundance_matrix import AbundanceMatrix
from .profile_subset import ProfileSubset


class ProfileSubsetBuilder:
    """Slices an AbundanceMatrix by clade and/or sample into a ProfileSubset."""

    def build(self, matrix: AbundanceMatrix, metadata_df: pd.DataFrame, criteria: SubsetCriteria) -> ProfileSubset:
        by_taxa = self._filter_taxa(matrix, criteria.taxa)
        profile_df = self._filter_samples(by_taxa, metadata_df, criteria.samples)
        return ProfileSubset(profile_df=profile_df, full_metadata_df=metadata_df)

    def _filter_taxa(self, matrix: AbundanceMatrix, selector: TaxaSelector | None) -> pd.DataFrame:
        if selector is None:
            return matrix.counts
        keys = self._clade_keys(matrix, selector)
        return matrix.counts[[c for c in matrix.counts.columns if c in keys]]

    def _clade_keys(self, matrix: AbundanceMatrix, selector: TaxaSelector) -> set[str]:
        taxa = matrix.taxa
        hits = taxa[taxa[selector.rank].isin(selector.names)]
        return set(hits["taxon_key"])

    def _filter_samples(self, profile_df: pd.DataFrame, metadata_df: pd.DataFrame, selector: SampleSelector | None) -> pd.DataFrame:
        if selector is None:
            return profile_df
        kept = metadata_df.loc[metadata_df[selector.column].isin(selector.values), "acc"]
        return profile_df[profile_df.index.isin(set(kept))]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_profile_subset_builder.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/profile_subset_builder.py Tests/unit/taxonomy/test_profile_subset_builder.py
git commit -m "feat(taxonomy): add ProfileSubsetBuilder"
```

---

## Task 11: Matrix format writers (strategy + factory)

Four writers behind a `MatrixFormatWriter` protocol, selected by a factory dict (no if/elif ladder). Counts/relative/maaslin first; BIOM last (adds `biom-format`).

**Files:**
- Create: `Accessors/matrix_writers/__init__.py`, `matrix_format_writer.py`, `counts_writer.py`, `relative_writer.py`, `maaslin_writer.py`, `biom_writer.py`, `matrix_writer_factory.py`
- Test: `Tests/unit/taxonomy/test_matrix_writers.py`
- Modify: `Docs/requirements.txt` (add `biom-format`)

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_matrix_writers.py
import pandas as pd
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix
from Accessors.matrix_writers.matrix_writer_factory import MatrixWriterFactory


def _matrix():
    counts = pd.DataFrame({"superkingdom||Bacteria||2": [2, 2]},
                          index=pd.Index(["SRR1", "SRR2"], name="acc"))
    lookup = pd.DataFrame({"taxon_key": ["superkingdom||Bacteria||2"], "tax_id": [2],
                           "rank": ["superkingdom"], "name": ["Bacteria"]})
    lineage = pd.DataFrame({"tax_id": [2], "superkingdom": ["Bacteria"]})
    return AbundanceMatrix(counts=counts, lookup=lookup, lineage_df=lineage)


def test_counts_writer_creates_csv(tmp_path):
    path = MatrixWriterFactory().create("counts").write(_matrix(), tmp_path / "counts.csv")

    assert path.exists()
    assert "superkingdom||Bacteria||2" in path.read_text()


def test_relative_writer_normalizes(tmp_path):
    path = MatrixWriterFactory().create("relative").write(_matrix(), tmp_path / "rel.csv")

    written = pd.read_csv(path, index_col=0)
    assert abs(written.loc["SRR1"].sum() - 1.0) < 1e-9


def test_maaslin_writer_is_tab_separated(tmp_path):
    path = MatrixWriterFactory().create("maaslin").write(_matrix(), tmp_path / "m.tsv")

    assert "\t" in path.read_text()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_matrix_writers.py -v`
Expected: FAIL with `ModuleNotFoundError`

- [ ] **Step 3: Write the protocol and writers**

```python
# Accessors/matrix_writers/__init__.py
```

```python
# Accessors/matrix_writers/matrix_format_writer.py
from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix


class MatrixFormatWriter(Protocol):
    def write(self, matrix: "AbundanceMatrix", path: Path) -> Path: ...
```

```python
# Accessors/matrix_writers/counts_writer.py
from __future__ import annotations

from pathlib import Path


class CountsWriter:
    def write(self, matrix, path: Path) -> Path:
        matrix.counts.to_csv(path)
        return path
```

```python
# Accessors/matrix_writers/relative_writer.py
from __future__ import annotations

from pathlib import Path


class RelativeWriter:
    def write(self, matrix, path: Path) -> Path:
        matrix.relative.to_csv(path)
        return path
```

```python
# Accessors/matrix_writers/maaslin_writer.py
from __future__ import annotations

from pathlib import Path


class MaaslinWriter:
    def write(self, matrix, path: Path) -> Path:
        long_df = matrix.counts.reset_index().melt(
            id_vars=[matrix.counts.index.name], var_name="taxon_key", value_name="value"
        )
        long_df.to_csv(path, sep="\t", index=False)
        return path
```

```python
# Accessors/matrix_writers/biom_writer.py
from __future__ import annotations

from pathlib import Path

from biom import Table


class BiomWriter:
    def write(self, matrix, path: Path) -> Path:
        observations = list(matrix.counts.columns)
        samples = list(matrix.counts.index)
        table = Table(matrix.counts.to_numpy().T, observations, samples)
        Path(path).write_text(table.to_json(generated_by="ask-slm"))
        return path
```

```python
# Accessors/matrix_writers/matrix_writer_factory.py
from __future__ import annotations

from .matrix_format_writer import MatrixFormatWriter
from .counts_writer import CountsWriter
from .relative_writer import RelativeWriter
from .maaslin_writer import MaaslinWriter
from .biom_writer import BiomWriter


class MatrixWriterFactory:
    """Returns the MatrixFormatWriter for a requested format."""

    _WRITERS = {
        "counts": CountsWriter,
        "relative": RelativeWriter,
        "maaslin": MaaslinWriter,
        "biom": BiomWriter,
    }

    def create(self, fmt: str) -> MatrixFormatWriter:
        writer_type = self._WRITERS.get(fmt)
        if writer_type is None:
            raise ValueError(f"Unknown matrix format: {fmt}")
        return writer_type()
```

- [ ] **Step 4: Add the dependency**

Append to `Docs/requirements.txt`:

```text
biom-format
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pip install biom-format && pytest Tests/unit/taxonomy/test_matrix_writers.py -v`
Expected: PASS (3 passed) — BIOM round-trip is exercised in the e2e task.

- [ ] **Step 6: Commit**

```bash
git add Accessors/matrix_writers/ Tests/unit/taxonomy/test_matrix_writers.py Docs/requirements.txt
git commit -m "feat(taxonomy): add matrix format writers with factory"
```

---

## Task 12: TaxonomyEngine facade functions

The public callables that wire accessors + engines. `DEFAULT_MERGED_DMP` points at the existing dump file.

**Files:**
- Create: `Engines/TaxonomyEngine/__init__.py`
- Test: `Tests/unit/taxonomy/test_taxonomy_facade.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_taxonomy_facade.py
from pathlib import Path
import Engines.TaxonomyEngine as taxonomy
from Common.contracts.selectors import SubsetCriteria, TaxaSelector

TAX = Path("Tests/fixtures/taxonomy_tiny.csv")
DMP = Path("Tests/fixtures/merged_tiny.dmp")


def test_load_then_build_then_subset():
    taxonomy_df = taxonomy.load(TAX)
    resolved = taxonomy.resolve(taxonomy_df, merged_dmp=DMP)
    matrix = taxonomy.build_abundance_matrix(resolved.df)

    subset = taxonomy.get_profile_subset(
        matrix,
        taxonomy_df[["acc"]].drop_duplicates().assign(Group="treatment"),
        SubsetCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",))),
    )

    assert all("Bacteria" in c for c in subset.profile_df.columns)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_facade.py -v`
Expected: FAIL with `ModuleNotFoundError` / missing attribute

- [ ] **Step 3: Write minimal implementation**

```python
# Engines/TaxonomyEngine/__init__.py
from __future__ import annotations

from pathlib import Path

import pandas as pd

from Accessors.TaxonomyAccessor.taxonomy_file_accessor import TaxonomyFileAccessor
from Accessors.MergedDumpAccessor.merged_dump_accessor import MergedDumpAccessor
from Common.contracts.selectors import SubsetCriteria
from Common.contracts.taxonomy_results import ResolutionSummary, ResolvedTaxonomy
from .abundance_matrix import AbundanceMatrix
from .abundance_matrix_builder import AbundanceMatrixBuilder
from .profile_subset import ProfileSubset
from .profile_subset_builder import ProfileSubsetBuilder
from .taxonomy_resolver import TaxonomyResolver

DEFAULT_MERGED_DMP = Path("Accessors/TaxonomyAccessor/merged.dmp")


def load(source: Path) -> pd.DataFrame:
    return TaxonomyFileAccessor().read(Path(source))


def resolve(taxonomy_df: pd.DataFrame, merged_dmp: Path = DEFAULT_MERGED_DMP) -> ResolvedTaxonomy:
    mapping = MergedDumpAccessor().load(Path(merged_dmp))
    resolver = TaxonomyResolver(mapping)
    summary_dict, changes_df = resolver.summarize_resolution(taxonomy_df)
    return ResolvedTaxonomy(
        df=resolver.resolve(taxonomy_df),
        changes_df=changes_df,
        summary=_to_summary(summary_dict),
    )


def build_abundance_matrix(taxonomy_df: pd.DataFrame) -> AbundanceMatrix:
    return AbundanceMatrixBuilder().build(taxonomy_df)


def get_profile_subset(matrix: AbundanceMatrix, metadata_df: pd.DataFrame, criteria: SubsetCriteria) -> ProfileSubset:
    return ProfileSubsetBuilder().build(matrix, metadata_df, criteria)


def _to_summary(summary_dict: dict) -> ResolutionSummary:
    return ResolutionSummary(
        input_rows=summary_dict["input_rows"],
        rows_updated=summary_dict["rows_updated"],
        unique_old_tax_ids_updated=summary_dict["unique_old_tax_ids_updated"],
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_facade.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/__init__.py Tests/unit/taxonomy/test_taxonomy_facade.py
git commit -m "feat(taxonomy): wire TaxonomyEngine facade functions"
```

---

## Task 13: Public `askslm.taxonomy` namespace

**Files:**
- Create: `askslm/__init__.py`, `askslm/contracts.py`
- Test: `Tests/unit/taxonomy/test_public_namespace.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/taxonomy/test_public_namespace.py
from askslm import taxonomy
from askslm.contracts import SubsetCriteria, TaxaSelector, SampleSelector


def test_taxonomy_exposes_core_callables():
    for name in ("load", "resolve", "build_abundance_matrix", "get_profile_subset"):
        assert callable(getattr(taxonomy, name))


def test_contracts_reexports_selectors():
    assert SubsetCriteria().taxa is None
    assert TaxaSelector("superkingdom", ("Bacteria",)).rank == "superkingdom"
    assert SampleSelector("Group", ("a",)).column == "Group"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest Tests/unit/taxonomy/test_public_namespace.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'askslm'`

- [ ] **Step 3: Write minimal implementation**

```python
# askslm/__init__.py
from Engines import TaxonomyEngine as taxonomy

__all__ = ["taxonomy"]
```

```python
# askslm/contracts.py
from Common.contracts.selectors import SampleSelector, SubsetCriteria, TaxaSelector
from Common.contracts.taxonomy_results import ResolutionSummary, ResolvedTaxonomy

__all__ = [
    "SampleSelector",
    "SubsetCriteria",
    "TaxaSelector",
    "ResolutionSummary",
    "ResolvedTaxonomy",
]
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest Tests/unit/taxonomy/test_public_namespace.py -v`
Expected: PASS (2 passed)

- [ ] **Step 5: Commit**

```bash
git add askslm/__init__.py askslm/contracts.py Tests/unit/taxonomy/test_public_namespace.py
git commit -m "feat(askslm): expose public taxonomy namespace and contracts"
```

---

## Task 14: End-to-end taxonomy flow (incl. BIOM round-trip)

**Files:**
- Test: `Tests/e2e/test_taxonomy_flow.py`

- [ ] **Step 1: Write the end-to-end test**

```python
# Tests/e2e/test_taxonomy_flow.py
from pathlib import Path
import pandas as pd
from askslm import taxonomy
from askslm.contracts import SubsetCriteria, TaxaSelector, SampleSelector

TAX = Path("Tests/fixtures/taxonomy_tiny.csv")
DMP = Path("Tests/fixtures/merged_tiny.dmp")


def test_full_flow_subset_and_formats(tmp_path):
    taxonomy_df = taxonomy.load(TAX)
    resolved = taxonomy.resolve(taxonomy_df, merged_dmp=DMP)
    matrix = taxonomy.build_abundance_matrix(resolved.df)
    metadata = pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["treatment", "control"]})

    subset = taxonomy.get_profile_subset(
        matrix, metadata,
        SubsetCriteria(
            taxa=TaxaSelector("superkingdom", ("Bacteria",)),
            samples=SampleSelector("Group", ("treatment",)),
        ),
    )

    assert list(subset.profile_df.index) == ["SRR1"]
    assert list(subset.metadata_df["acc"]) == ["SRR1"]
    for fmt, name in [("counts", "c.csv"), ("relative", "r.csv"), ("maaslin", "m.tsv"), ("biom", "t.biom")]:
        assert matrix.write(tmp_path / name, fmt=fmt).exists()
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest Tests/e2e/test_taxonomy_flow.py -v`
Expected: PASS

- [ ] **Step 3: Run the whole taxonomy suite**

Run: `pytest Tests/unit/taxonomy Tests/e2e/test_taxonomy_flow.py -v`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git add Tests/e2e/test_taxonomy_flow.py
git commit -m "test(taxonomy): end-to-end load/resolve/build/subset flow"
```

---

## Self-Review (completed by plan author)

**Spec coverage:** taxonomy `load` (T3,T12), `resolve` (T5,T12), `build_abundance_matrix` + 4 formats (T7,T8,T11,T12), `get_profile_subset` matrix-driven with typed selectors (T1,T9,T10,T12), lineage-without-DB (T6), two-DataFrame rule in subset (T9), public facade + contracts re-export (T13), tests for every capability (T1–T14). Metadata core and deletions are explicitly deferred to Plans 2 and 3.

**Placeholder scan:** none — every code/test step contains full content.

**Type/name consistency:** `AbundanceMatrix(counts, lookup, lineage_df)`, `.counts/.relative/.taxa/.write`; `ProfileSubset(profile_df, full_metadata_df)`, `.metadata_df`; `ResolvedTaxonomy(df, changes_df, summary)`; selectors `TaxaSelector(rank, names)`, `SampleSelector(column, values)`, `SubsetCriteria(taxa, samples)`; facade `load/resolve/build_abundance_matrix/get_profile_subset` — all consistent across tasks.
