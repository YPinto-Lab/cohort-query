# Cohort replaces ProfileSubset — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace `ProfileSubset` / `ProfileSubsetBuilder` with a first-class `Cohort` value object that pairs `AbundanceMatrix` and a new typed `Metadata`, and rename `SubsetCriteria` → `FilterCriteria`.

**Architecture:** `Cohort(matrix, metadata)` is the unit of meaning — both the unfiltered whole and any filtered slice are instances of `Cohort`. Construction eagerly aligns metadata to the matrix's sample index; `cohort.filter(FilterCriteria)` returns a new `Cohort` with both halves filtered in lockstep. `Metadata` is a small dataclass wrapping the sample-metadata DataFrame with `reindex_to`, `filter`, and `write` methods. Cohort accesses `AbundanceMatrix`'s lookup/lineage references directly via their existing `_lookup` / `_lineage_df` attributes (Python single-underscore convention — same package).

**Tech Stack:** Python 3.11+, pandas, pytest, frozen `@dataclass` value objects.

---

## File Structure

**Create:**
- `Engines/MetadataEngine/metadata.py` — `Metadata` value object
- `Engines/TaxonomyEngine/cohort.py` — `Cohort` value object
- `Tests/unit/metadata/__init__.py` — package marker (if not present)
- `Tests/unit/metadata/test_metadata.py` — Metadata tests
- `Tests/unit/taxonomy/test_cohort.py` — Cohort tests (replaces two old test files)

**Modify:**
- `Common/contracts/selectors.py` — rename `SubsetCriteria` → `FilterCriteria`
- `askslm/contracts.py` — re-export rename
- `Engines/TaxonomyEngine/__init__.py` — drop `ProfileSubset*` exports; add `Cohort`; rename `get_profile_subset` → `build_cohort` (returns a `Cohort`, no criteria arg — callers chain `.filter`)
- `Tests/unit/taxonomy/test_selectors.py` — rename references
- `Tests/unit/taxonomy/test_taxonomy_facade.py` — use new facade name + Cohort assertions
- `Tests/unit/taxonomy/test_public_namespace.py` — new facade name + contracts rename
- `Tests/e2e/test_taxonomy_flow.py` — same as above
- `Notebooks/new.ipynb` — replace any `ProfileSubset*` / `SubsetCriteria` / `get_profile_subset` references; output filenames update to `abundance_matrix.csv` + `metadata.csv`

**Delete:**
- `Engines/TaxonomyEngine/profile_subset.py`
- `Engines/TaxonomyEngine/profile_subset_builder.py`
- `Tests/unit/taxonomy/test_profile_subset.py`
- `Tests/unit/taxonomy/test_profile_subset_builder.py`

---

## Task 1: Rename `SubsetCriteria` → `FilterCriteria`

**Files:**
- Modify: `Common/contracts/selectors.py`
- Modify: `askslm/contracts.py`
- Modify: `Tests/unit/taxonomy/test_selectors.py`

- [ ] **Step 1: Update the test to use `FilterCriteria`**

Replace the full contents of `Tests/unit/taxonomy/test_selectors.py`:

```python
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest Tests/unit/taxonomy/test_selectors.py -v`
Expected: ImportError — `cannot import name 'FilterCriteria' from 'Common.contracts.selectors'`.

- [ ] **Step 3: Rename in `Common/contracts/selectors.py`**

Replace the full contents:

```python
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
class FilterCriteria:
    taxa: TaxaSelector | None = None
    samples: SampleSelector | None = None
    sample_filters: tuple[SampleSelector, ...] = ()
```

- [ ] **Step 4: Update the public re-export**

Replace the full contents of `askslm/contracts.py`:

```python
from Common.contracts.metadata_results import MetadataOverview
from Common.contracts.selectors import FilterCriteria, SampleSelector, TaxaSelector
from Common.contracts.taxonomy_results import ResolutionSummary, ResolvedTaxonomy

__all__ = [
    "MetadataOverview",
    "SampleSelector",
    "FilterCriteria",
    "TaxaSelector",
    "ResolutionSummary",
    "ResolvedTaxonomy",
]
```

- [ ] **Step 5: Run the selectors tests to verify they pass**

Run: `pytest Tests/unit/taxonomy/test_selectors.py -v`
Expected: 5 passed.

- [ ] **Step 6: Commit**

```bash
git add Common/contracts/selectors.py askslm/contracts.py Tests/unit/taxonomy/test_selectors.py
git commit -m "refactor(contracts): rename SubsetCriteria to FilterCriteria"
```

Note: other tests/files still reference `SubsetCriteria` and will break at this point. They are fixed in Task 6 and Task 7. Run only the selectors test in Step 5.

---

## Task 2: Create `Metadata` value object

**Files:**
- Create: `Engines/MetadataEngine/metadata.py`
- Create: `Tests/unit/metadata/__init__.py`
- Create: `Tests/unit/metadata/test_metadata.py`

- [ ] **Step 1: Create the test package marker**

Create `Tests/unit/metadata/__init__.py` as an empty file.

- [ ] **Step 2: Write the failing tests for `Metadata`**

Create `Tests/unit/metadata/test_metadata.py`:

```python
import pandas as pd
import pytest

from Common.contracts.selectors import SampleSelector
from Engines.MetadataEngine.metadata import Metadata


def _df():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "Group": ["treatment", "control", "treatment"],
        "assay_type": ["WGS", "WGS", "AMPLICON"],
    })


def test_construction_validates_acc_column_present():
    bad = pd.DataFrame({"sample_id": ["SRR1"], "Group": ["a"]})

    with pytest.raises(ValueError, match="acc"):
        Metadata(df=bad)


def test_construction_rejects_duplicate_acc():
    dup = pd.DataFrame({"acc": ["SRR1", "SRR1"], "Group": ["a", "b"]})

    with pytest.raises(ValueError, match="duplicate"):
        Metadata(df=dup)


def test_reindex_to_orders_rows_and_drops_missing():
    md = Metadata(df=_df())

    reindexed = md.reindex_to(["SRR3", "SRR1"])

    assert list(reindexed.df["acc"]) == ["SRR3", "SRR1"]


def test_reindex_to_drops_sample_ids_absent_from_metadata():
    md = Metadata(df=_df())

    reindexed = md.reindex_to(["SRR1", "SRR9"])

    assert list(reindexed.df["acc"]) == ["SRR1"]


def test_filter_keeps_matching_rows():
    md = Metadata(df=_df())

    filtered = md.filter(SampleSelector(column="Group", values=("treatment",)))

    assert list(filtered.df["acc"]) == ["SRR1", "SRR3"]


def test_write_produces_csv_without_index(tmp_path):
    md = Metadata(df=_df())

    path = md.write(tmp_path / "metadata.csv")

    written = pd.read_csv(path)
    assert list(written.columns) == ["acc", "Group", "assay_type"]
    assert list(written["acc"]) == ["SRR1", "SRR2", "SRR3"]
```

- [ ] **Step 3: Run tests to verify they fail**

Run: `pytest Tests/unit/metadata/test_metadata.py -v`
Expected: ImportError — `Engines.MetadataEngine.metadata` does not exist.

- [ ] **Step 4: Implement `Metadata`**

Create `Engines/MetadataEngine/metadata.py`:

```python
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from Common.contracts.selectors import SampleSelector


@dataclass(frozen=True, eq=False)
class Metadata:
    df: pd.DataFrame

    def __post_init__(self) -> None:
        if "acc" not in self.df.columns:
            raise ValueError("Metadata df must contain an 'acc' column")
        if self.df["acc"].duplicated().any():
            raise ValueError("Metadata df has duplicate 'acc' values")

    def reindex_to(self, sample_ids: Iterable[str]) -> Metadata:
        wanted = list(sample_ids)
        indexed = self.df.set_index("acc")
        present = [acc for acc in wanted if acc in indexed.index]
        reordered = indexed.reindex(present).reset_index()
        return Metadata(df=reordered)

    def filter(self, selector: SampleSelector) -> Metadata:
        kept = self.df[self.df[selector.column].isin(selector.values)].reset_index(drop=True)
        return Metadata(df=kept)

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(path, index=False)
        return path
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `pytest Tests/unit/metadata/test_metadata.py -v`
Expected: 6 passed.

- [ ] **Step 6: Commit**

```bash
git add Engines/MetadataEngine/metadata.py Tests/unit/metadata/__init__.py Tests/unit/metadata/test_metadata.py
git commit -m "feat(metadata): add Metadata value object with reindex/filter/write"
```

---

## Task 3: Create `Cohort` — construction + alignment invariant

**Files:**
- Create: `Engines/TaxonomyEngine/cohort.py`
- Create: `Tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: Write failing tests for Cohort construction**

Create `Tests/unit/taxonomy/test_cohort.py`:

```python
import pandas as pd

from Engines.MetadataEngine.metadata import Metadata
from Engines.TaxonomyEngine.abundance_matrix_builder import AbundanceMatrixBuilder
from Engines.TaxonomyEngine.cohort import Cohort


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


def test_construction_aligns_metadata_to_matrix_sample_index():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    # SRR4 is in metadata but not the matrix -> dropped; order matches matrix
    assert list(cohort.metadata.df["acc"]) == list(cohort.matrix.counts.index)


def test_construction_preserves_matrix_sample_order_in_metadata():
    matrix = _matrix()
    shuffled_md = Metadata(df=pd.DataFrame({
        "acc": ["SRR3", "SRR1", "SRR2"],
        "Group": ["t", "t", "c"],
    }))

    cohort = Cohort(matrix=matrix, metadata=shuffled_md)

    assert list(cohort.metadata.df["acc"]) == list(matrix.counts.index)
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest Tests/unit/taxonomy/test_cohort.py -v`
Expected: ImportError — `Engines.TaxonomyEngine.cohort` does not exist.

- [ ] **Step 3: Implement minimal `Cohort` (construction only)**

Create `Engines/TaxonomyEngine/cohort.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

from Engines.MetadataEngine.metadata import Metadata
from .abundance_matrix import AbundanceMatrix


@dataclass(frozen=True, eq=False)
class Cohort:
    matrix: AbundanceMatrix
    metadata: Metadata

    def __post_init__(self) -> None:
        aligned = self.metadata.reindex_to(self.matrix.counts.index)
        object.__setattr__(self, "metadata", aligned)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest Tests/unit/taxonomy/test_cohort.py -v`
Expected: 2 passed.

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/cohort.py Tests/unit/taxonomy/test_cohort.py
git commit -m "feat(taxonomy): add Cohort value object with eager metadata alignment"
```

---

## Task 4: Add `Cohort.filter`

**Files:**
- Modify: `Engines/TaxonomyEngine/cohort.py`
- Modify: `Tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: Append filter tests**

Append to `Tests/unit/taxonomy/test_cohort.py`:

```python
from Common.contracts.selectors import FilterCriteria, SampleSelector, TaxaSelector


def test_filter_by_taxa_keeps_only_matching_clade_columns():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",))))

    assert list(filtered.matrix.counts.columns) == ["superkingdom||Bacteria||2"]


def test_filter_by_samples_keeps_only_matching_rows_in_both_halves():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(samples=SampleSelector(column="Group", values=("treatment",))))

    assert list(filtered.matrix.counts.index) == ["SRR1", "SRR3"]
    assert list(filtered.metadata.df["acc"]) == ["SRR1", "SRR3"]


def test_filter_combined_taxa_and_samples():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(
        taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)),
        samples=SampleSelector(column="Group", values=("treatment",)),
    ))

    assert list(filtered.matrix.counts.columns) == ["superkingdom||Bacteria||2"]
    assert list(filtered.matrix.counts.index) == ["SRR1", "SRR3"]
    assert list(filtered.metadata.df["acc"]) == ["SRR1", "SRR3"]


def test_filter_sample_filters_applies_and_logic_across_columns():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(sample_filters=(
        SampleSelector(column="Group", values=("treatment",)),
        SampleSelector(column="assay_type", values=("WGS",)),
    )))

    assert list(filtered.matrix.counts.index) == ["SRR1"]
    assert list(filtered.metadata.df["acc"]) == ["SRR1"]


def test_filter_samples_and_sample_filters_combine():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(
        samples=SampleSelector(column="Group", values=("treatment",)),
        sample_filters=(SampleSelector(column="assay_type", values=("WGS",)),),
    ))

    assert list(filtered.matrix.counts.index) == ["SRR1"]


def test_filter_with_empty_criteria_is_identity_on_rows_and_cols():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria())

    assert list(filtered.matrix.counts.index) == list(cohort.matrix.counts.index)
    assert list(filtered.matrix.counts.columns) == list(cohort.matrix.counts.columns)


def test_filter_preserves_taxa_lookup_through_matrix():
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    filtered = cohort.filter(FilterCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",))))

    # lookup/lineage are preserved -> .taxa still resolves the surviving column
    assert "superkingdom||Bacteria||2" in set(filtered.matrix.taxa["taxon_key"])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest Tests/unit/taxonomy/test_cohort.py -v`
Expected: 7 failures with AttributeError — `Cohort` has no `filter` method.

- [ ] **Step 3: Implement `Cohort.filter` and helpers**

Replace the full contents of `Engines/TaxonomyEngine/cohort.py`:

```python
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from Common.contracts.selectors import FilterCriteria, SampleSelector, TaxaSelector
from Engines.MetadataEngine.metadata import Metadata
from .abundance_matrix import AbundanceMatrix


@dataclass(frozen=True, eq=False)
class Cohort:
    matrix: AbundanceMatrix
    metadata: Metadata

    def __post_init__(self) -> None:
        aligned = self.metadata.reindex_to(self.matrix.counts.index)
        object.__setattr__(self, "metadata", aligned)

    def filter(self, criteria: FilterCriteria) -> Cohort:
        new_matrix = self._filter_taxa(self.matrix, criteria.taxa)
        sample_selectors = [s for s in (criteria.samples, *criteria.sample_filters) if s is not None]
        new_metadata = self._filter_metadata(self.metadata, sample_selectors)
        new_matrix = self._reindex_matrix_rows(new_matrix, list(new_metadata.df["acc"]))
        return Cohort(matrix=new_matrix, metadata=new_metadata)

    @staticmethod
    def _filter_taxa(matrix: AbundanceMatrix, selector: TaxaSelector | None) -> AbundanceMatrix:
        if selector is None:
            return matrix
        taxa = matrix.taxa
        keys = set(taxa[taxa[selector.rank].isin(selector.names)]["taxon_key"])
        kept_columns = [c for c in matrix.counts.columns if c in keys]
        new_counts = matrix.counts[kept_columns]
        return AbundanceMatrix(counts=new_counts, lookup=matrix._lookup, lineage_df=matrix._lineage_df)

    @staticmethod
    def _filter_metadata(metadata: Metadata, selectors: list[SampleSelector]) -> Metadata:
        result = metadata
        for selector in selectors:
            result = result.filter(selector)
        return result

    @staticmethod
    def _reindex_matrix_rows(matrix: AbundanceMatrix, sample_ids: list[str]) -> AbundanceMatrix:
        present = [acc for acc in sample_ids if acc in matrix.counts.index]
        new_counts = matrix.counts.reindex(present)
        return AbundanceMatrix(counts=new_counts, lookup=matrix._lookup, lineage_df=matrix._lineage_df)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest Tests/unit/taxonomy/test_cohort.py -v`
Expected: 9 passed (2 from Task 3 + 7 new).

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/cohort.py Tests/unit/taxonomy/test_cohort.py
git commit -m "feat(taxonomy): add Cohort.filter for lockstep taxa+sample filtering"
```

---

## Task 5: Add `Cohort.write`

**Files:**
- Modify: `Engines/TaxonomyEngine/cohort.py`
- Modify: `Tests/unit/taxonomy/test_cohort.py`

- [ ] **Step 1: Append write tests**

Append to `Tests/unit/taxonomy/test_cohort.py`:

```python
def test_write_produces_abundance_matrix_csv_and_metadata_csv(tmp_path):
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    paths = cohort.write(tmp_path)

    matrix_path = tmp_path / "abundance_matrix.csv"
    metadata_path = tmp_path / "metadata.csv"
    assert matrix_path.exists()
    assert metadata_path.exists()
    assert set(paths) == {matrix_path, metadata_path}


def test_write_metadata_csv_has_no_pandas_index_column(tmp_path):
    cohort = Cohort(matrix=_matrix(), metadata=_metadata_full())

    cohort.write(tmp_path)

    written = pd.read_csv(tmp_path / "metadata.csv")
    assert "Unnamed: 0" not in written.columns
    assert list(written.columns)[0] == "acc"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `pytest Tests/unit/taxonomy/test_cohort.py -v -k write`
Expected: 2 failures — `Cohort` has no `write` method.

- [ ] **Step 3: Add `write` to `Cohort`**

Add the following imports and method to `Engines/TaxonomyEngine/cohort.py`.

Add to the imports near the top:

```python
from pathlib import Path
```

Add the following method to the `Cohort` class (below `filter`, above the `_filter_taxa` staticmethod):

```python
    def write(self, out_dir: Path, fmt: str = "counts") -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        matrix_path = self.matrix.write(out_dir / "abundance_matrix.csv", fmt)
        metadata_path = self.metadata.write(out_dir / "metadata.csv")
        return [matrix_path, metadata_path]
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `pytest Tests/unit/taxonomy/test_cohort.py -v`
Expected: 11 passed.

- [ ] **Step 5: Commit**

```bash
git add Engines/TaxonomyEngine/cohort.py Tests/unit/taxonomy/test_cohort.py
git commit -m "feat(taxonomy): add Cohort.write delegating matrix + metadata writers"
```

---

## Task 6: Wire facade — replace `get_profile_subset` with `build_cohort`

**Files:**
- Modify: `Engines/TaxonomyEngine/__init__.py`
- Modify: `Tests/unit/taxonomy/test_taxonomy_facade.py`
- Modify: `Tests/unit/taxonomy/test_public_namespace.py`

- [ ] **Step 1: Rewrite the facade test**

Replace the full contents of `Tests/unit/taxonomy/test_taxonomy_facade.py`:

```python
import pandas as pd
import Engines.TaxonomyEngine as taxonomy
from Common.contracts.selectors import FilterCriteria, TaxaSelector
from Engines.MetadataEngine.metadata import Metadata
from Engines.TaxonomyEngine.cohort import Cohort


def _matrix():
    long_df = pd.DataFrame({
        "acc": ["SRR1", "SRR1", "SRR2"],
        "tax_id": [2, 10239, 2],
        "rank": ["superkingdom", "superkingdom", "superkingdom"],
        "name": ["Bacteria", "Viruses", "Bacteria"],
        "total_count": [100, 40, 80],
        "self_count": [100, 40, 80],
        "ileft": [1, 3, 1],
        "iright": [2, 4, 2],
    })
    return taxonomy.build_abundance_matrix(long_df, rank="superkingdom")


def test_build_cohort_returns_cohort_pairing_matrix_and_metadata():
    matrix = _matrix()
    metadata = Metadata(df=pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["t", "c"]}))

    cohort = taxonomy.build_cohort(matrix, metadata)

    assert isinstance(cohort, Cohort)
    assert list(cohort.metadata.df["acc"]) == list(cohort.matrix.counts.index)


def test_build_cohort_then_filter_narrows_by_taxa():
    matrix = _matrix()
    metadata = Metadata(df=pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["t", "c"]}))

    filtered = taxonomy.build_cohort(matrix, metadata).filter(
        FilterCriteria(taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)))
    )

    assert list(filtered.matrix.counts.columns) == ["superkingdom||Bacteria||2"]
```

- [ ] **Step 2: Rewrite the public namespace test**

Replace the full contents of `Tests/unit/taxonomy/test_public_namespace.py`:

```python
from askslm import taxonomy
from askslm.contracts import FilterCriteria, TaxaSelector, SampleSelector


def test_taxonomy_exposes_core_callables():
    for name in ("load", "resolve", "build_abundance_matrix", "build_cohort"):
        assert callable(getattr(taxonomy, name))


def test_contracts_reexports_selectors():
    assert FilterCriteria().taxa is None
    assert TaxaSelector("superkingdom", ("Bacteria",)).rank == "superkingdom"
    assert SampleSelector("Group", ("a",)).column == "Group"
```

- [ ] **Step 3: Run the facade tests to verify they fail**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_facade.py Tests/unit/taxonomy/test_public_namespace.py -v`
Expected: failures with AttributeError — `taxonomy` has no `build_cohort`.

- [ ] **Step 4: Update the facade module**

Replace the full contents of `Engines/TaxonomyEngine/__init__.py`:

```python
from __future__ import annotations

from pathlib import Path

import pandas as pd

from Accessors.TaxonomyAccessor.taxonomy_file_accessor import TaxonomyFileAccessor
from Accessors.MergedDumpAccessor.merged_dump_accessor import MergedDumpAccessor
from Common.contracts.taxonomy_results import ResolutionSummary, ResolvedTaxonomy
from Engines.MetadataEngine.metadata import Metadata
from .abundance_matrix import AbundanceMatrix
from .abundance_matrix_builder import AbundanceMatrixBuilder
from .cohort import Cohort
from .taxonomy_resolver import TaxonomyResolver

DEFAULT_MERGED_DMP = Path(__file__).parent.parent.parent / "Accessors" / "TaxonomyAccessor" / "merged.dmp"


def load(source: str | Path) -> pd.DataFrame:
    return TaxonomyFileAccessor().read(Path(source))


def resolve(taxonomy_df: pd.DataFrame, merged_dmp: str | Path = DEFAULT_MERGED_DMP) -> ResolvedTaxonomy:
    mapping = MergedDumpAccessor().load(Path(merged_dmp))
    resolver = TaxonomyResolver(mapping)
    summary_dict, changes_df = resolver.summarize_resolution(taxonomy_df)
    return ResolvedTaxonomy(
        df=resolver.resolve(taxonomy_df),
        changes_df=changes_df,
        summary=_to_summary(summary_dict),
    )


def build_abundance_matrix(taxonomy_df: pd.DataFrame, rank: str = "genus") -> AbundanceMatrix:
    return AbundanceMatrixBuilder().build(taxonomy_df, rank)


def build_cohort(matrix: AbundanceMatrix, metadata: Metadata) -> Cohort:
    return Cohort(matrix=matrix, metadata=metadata)


def _to_summary(summary_dict: dict) -> ResolutionSummary:
    return ResolutionSummary(
        input_rows=summary_dict["input_rows"],
        rows_updated=summary_dict["rows_updated"],
        unique_old_tax_ids_updated=summary_dict["unique_old_tax_ids_updated"],
    )
```

- [ ] **Step 5: Run the facade tests to verify they pass**

Run: `pytest Tests/unit/taxonomy/test_taxonomy_facade.py Tests/unit/taxonomy/test_public_namespace.py -v`
Expected: all passed.

- [ ] **Step 6: Commit**

```bash
git add Engines/TaxonomyEngine/__init__.py Tests/unit/taxonomy/test_taxonomy_facade.py Tests/unit/taxonomy/test_public_namespace.py
git commit -m "refactor(taxonomy): expose build_cohort facade, drop get_profile_subset"
```

---

## Task 7: Update the e2e flow test

**Files:**
- Modify: `Tests/e2e/test_taxonomy_flow.py`

- [ ] **Step 1: Replace the e2e test contents**

Replace the full contents of `Tests/e2e/test_taxonomy_flow.py`:

```python
from pathlib import Path
import pandas as pd
from askslm import taxonomy
from askslm.contracts import FilterCriteria, TaxaSelector, SampleSelector
from Engines.MetadataEngine.metadata import Metadata

_FIXTURES = Path(__file__).parent.parent / "fixtures"
TAX = _FIXTURES / "taxonomy_tiny.csv"
DMP = _FIXTURES / "merged_tiny.dmp"


def test_full_flow_subset_and_formats(tmp_path):
    taxonomy_df = taxonomy.load(TAX)
    resolved = taxonomy.resolve(taxonomy_df, merged_dmp=DMP)
    matrix = taxonomy.build_abundance_matrix(resolved.df)
    metadata = Metadata(df=pd.DataFrame({"acc": ["SRR1", "SRR2"], "Group": ["treatment", "control"]}))

    cohort = taxonomy.build_cohort(matrix, metadata).filter(
        FilterCriteria(
            taxa=TaxaSelector("superkingdom", ("Bacteria",)),
            samples=SampleSelector("Group", ("treatment",)),
        )
    )

    assert list(cohort.matrix.counts.index) == ["SRR1"]
    assert list(cohort.metadata.df["acc"]) == ["SRR1"]
    assert list(cohort.matrix.counts.columns) == ["genus||Escherichia||561"]
    for fmt, name in [("counts", "c.csv"), ("relative", "r.csv"), ("maaslin", "m.tsv"), ("biom", "t.biom")]:
        assert matrix.write(tmp_path / name, fmt=fmt).exists()
```

- [ ] **Step 2: Run the e2e test to verify it passes**

Run: `pytest Tests/e2e/test_taxonomy_flow.py -v`
Expected: 1 passed.

- [ ] **Step 3: Commit**

```bash
git add Tests/e2e/test_taxonomy_flow.py
git commit -m "test(e2e): update taxonomy flow to use Cohort and Metadata"
```

---

## Task 8: Delete `ProfileSubset`, `ProfileSubsetBuilder`, and their tests

**Files:**
- Delete: `Engines/TaxonomyEngine/profile_subset.py`
- Delete: `Engines/TaxonomyEngine/profile_subset_builder.py`
- Delete: `Tests/unit/taxonomy/test_profile_subset.py`
- Delete: `Tests/unit/taxonomy/test_profile_subset_builder.py`

- [ ] **Step 1: Delete the four files**

Run:

```bash
git rm Engines/TaxonomyEngine/profile_subset.py \
       Engines/TaxonomyEngine/profile_subset_builder.py \
       Tests/unit/taxonomy/test_profile_subset.py \
       Tests/unit/taxonomy/test_profile_subset_builder.py
```

- [ ] **Step 2: Verify nothing else still imports them**

Run: `grep -rn "ProfileSubset\|profile_subset\|SubsetCriteria\|get_profile_subset" . --include="*.py"`
Expected: no matches (notebooks are checked in Task 9).

If matches appear, stop and fix them before proceeding — the rest of the suite will fail otherwise.

- [ ] **Step 3: Run the full unit + e2e test suite**

Run: `pytest Tests/unit Tests/e2e -v`
Expected: all passed; no import errors.

- [ ] **Step 4: Commit**

```bash
git commit -m "refactor(taxonomy): remove ProfileSubset and SubsetCriteria"
```

---

## Task 9: Update `Notebooks/new.ipynb`

**Files:**
- Modify: `Notebooks/new.ipynb`

- [ ] **Step 1: Audit the notebook**

Run: `grep -n "ProfileSubset\|profile_subset\|SubsetCriteria\|get_profile_subset\|profile.csv" Notebooks/new.ipynb`

Inspect each hit. The expected replacements are:

| Old | New |
|---|---|
| `from ... import ProfileSubsetBuilder` | (remove) |
| `from Common.contracts.selectors import SubsetCriteria` | `from Common.contracts.selectors import FilterCriteria` |
| `taxonomy.get_profile_subset(matrix, metadata_df, criteria)` | `taxonomy.build_cohort(matrix, Metadata(df=metadata_df)).filter(criteria)` (also `from Engines.MetadataEngine.metadata import Metadata`) |
| `SubsetCriteria(...)` | `FilterCriteria(...)` |
| `subset.profile_df` | `cohort.matrix.counts` |
| `subset.metadata_df` | `cohort.metadata.df` |
| Output filename `profile.csv` | `abundance_matrix.csv` (now produced by `cohort.write(out_dir)`) |

- [ ] **Step 2: Make the edits in the notebook**

Apply the replacements above in `Notebooks/new.ipynb`. If a cell wrote to `out_dir/profile.csv` manually, replace with `cohort.write(out_dir)` and remove now-redundant CSV writes.

- [ ] **Step 3: Re-run the notebook end-to-end and verify outputs**

Open the notebook, run all cells, and confirm:
- No `NameError` / `ImportError`.
- The output directory contains `abundance_matrix.csv` and `metadata.csv` (no stale `profile.csv`).

If a stale `profile.csv` exists in `Notebooks/out/<name>/` from a previous run, delete it manually — the new code does not produce it and stale files would mislead reviewers.

- [ ] **Step 4: Commit**

```bash
git add Notebooks/new.ipynb
git commit -m "chore(notebook): migrate new.ipynb to Cohort + FilterCriteria"
```

---

## Final Verification

- [ ] **Run the full suite**

Run: `pytest Tests -v`
Expected: all passed; no warnings about deprecated names.

- [ ] **Confirm no orphaned references remain**

Run: `grep -rn "ProfileSubset\|SubsetCriteria\|get_profile_subset\|profile_df\|full_metadata_df" . --include="*.py" --include="*.ipynb"`
Expected: no matches.
