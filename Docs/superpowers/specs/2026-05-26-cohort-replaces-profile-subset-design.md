# Cohort replaces ProfileSubset — design

**Date:** 2026-05-26
**Status:** Approved (pending user spec review)

## Motivation

Today the taxonomy pipeline has two structurally similar but asymmetric types:

- `AbundanceMatrix` (`Engines/TaxonomyEngine/abundance_matrix.py`) — samples × taxa counts, plus a taxon lookup and lineage table. Exposes `.relative`, `.taxa`, format-aware `.write(...)`.
- `ProfileSubset` (`Engines/TaxonomyEngine/profile_subset.py`) — samples × taxa counts plus lazily aligned metadata. **Drops** the lookup, the lineage, the relative-abundance computation, and the format-aware writer.

So a filtered abundance matrix is *less* than an abundance matrix. The structural taxonomy information is thrown away the moment a user filters by clade or by sample group.

The underlying unit of meaning in the pipeline is the **pair** `(AbundanceMatrix, sample metadata)`. They are always carried together: a filter on one implies the corresponding filter on the other. The current design fails to name that pair as a first-class concept, so the invariant "matrix and metadata are aligned" lives in convention instead of in a type.

## Goal

Introduce `Cohort` as the first-class value object representing the paired `(matrix, metadata)`. Both the unfiltered whole and any filtered slice are instances of `Cohort`. Remove `ProfileSubset` and `ProfileSubsetBuilder`.

## Design

### New types

#### `Metadata` (`Engines/MetadataEngine/metadata.py`)

Thin value object wrapping the sample metadata DataFrame so it has parity with `AbundanceMatrix`.

```python
@dataclass(frozen=True, eq=False)
class Metadata:
    df: pd.DataFrame   # must contain "acc" column; one row per sample

    def reindex_to(self, sample_ids: Iterable[str]) -> Metadata: ...
    def filter(self, selector: SampleSelector) -> Metadata: ...
    def write(self, path: Path) -> Path: ...
```

Responsibilities:

- **Validate at construction:** `acc` column present, no duplicate `acc` values.
- **`reindex_to(sample_ids)`** — return a new `Metadata` whose rows match the given sample order, dropping samples not present in `df`. Replaces the lazy alignment currently done inside `ProfileSubset.metadata_df`.
- **`filter(selector)`** — return a new `Metadata` keeping only rows whose `selector.column` value is in `selector.values`. Pulled from `ProfileSubsetBuilder._filter_by_selector`.
- **`write(path)`** — write `df` to CSV without the pandas index. The class wraps a DataFrame; it does not subclass one.

#### `Cohort` (`Engines/TaxonomyEngine/cohort.py`)

```python
@dataclass(frozen=True, eq=False)
class Cohort:
    matrix: AbundanceMatrix
    metadata: Metadata

    def __post_init__(self) -> None:
        # eager alignment: reindex metadata to matrix.counts.index, store the aligned value
        ...

    def filter(self, criteria: FilterCriteria) -> Cohort: ...
    def write(self, out_dir: Path, fmt: str = "counts") -> list[Path]: ...
```

Invariant: `metadata.df["acc"]` is in the same order as `matrix.counts.index` and contains exactly those values. Enforced at construction by an internal reindex; after that, all operations preserve it.

#### `FilterCriteria` (renamed from `SubsetCriteria` in `Common/contracts/selectors.py`)

Same shape as today (`taxa: TaxaSelector | None`, `samples: SampleSelector | None`, `sample_filters: tuple[SampleSelector, ...]`). Name change only — the old "subset" framing no longer applies.

### `Cohort.filter` semantics

`filter(criteria)` returns a new `Cohort` produced by:

1. Apply `criteria.taxa` to `matrix` → filtered AbundanceMatrix (column-wise).
2. Apply `criteria.samples` and every `criteria.sample_filters` entry to `metadata` in sequence → filtered Metadata.
3. Reindex matrix rows to the surviving `metadata.df["acc"]` order.
4. Construct `Cohort(filtered_matrix, filtered_metadata)`. The `__post_init__` alignment is a no-op here because step 3 already aligned them; it remains as a safety net.

Filter logic lives as **private methods on `Cohort`** (not a separate builder). It is ~30 lines ported from `ProfileSubsetBuilder` and does not justify a separate class. Taxa-key resolution stays as it is today: `taxa[taxa[selector.rank].isin(selector.names)]["taxon_key"]`.

Taxa filtering on `AbundanceMatrix` is implemented as a small private helper on `Cohort` that returns a new `AbundanceMatrix` with column-filtered `counts` (and the same `lookup` / `lineage_df` references — they are reference data, not state). No new public method is added to `AbundanceMatrix`.

### `Cohort.write` semantics

```
cohort.write(out_dir, fmt="counts") -> [<out_dir>/abundance_matrix.csv, <out_dir>/metadata.csv]
```

- Matrix path: `cohort.write` calls `AbundanceMatrix.write(out_dir / "abundance_matrix.csv", fmt)`, so `MatrixWriterFactory` formats continue to apply (the format determines how counts are serialized inside the file, not the filename).
- Metadata path: `out_dir / "metadata.csv"`, written by `Metadata.write(...)`.
- Filenames change from today's `profile.csv` + `metadata.csv` to `abundance_matrix.csv` + `metadata.csv`. Touching the surface anyway.

### Removed

- `Engines/TaxonomyEngine/profile_subset.py` — `ProfileSubset` class.
- `Engines/TaxonomyEngine/profile_subset_builder.py` — `ProfileSubsetBuilder` class.
- `SubsetCriteria` symbol (replaced by `FilterCriteria`).

### Public API

- `Common/contracts/selectors.py` — rename `SubsetCriteria` → `FilterCriteria`.
- `askslm/contracts.py` — update the re-export list (`FilterCriteria` instead of `SubsetCriteria`). `Cohort` and `Metadata` are exposed from `askslm.taxonomy` / `askslm.metadata` respectively where they are produced.

## Affected callers

- Taxonomy facade — wherever it currently calls `ProfileSubsetBuilder().build(...)`, it instead constructs a `Cohort` from the full matrix and metadata and calls `cohort.filter(criteria)`.
- Tests:
  - `Tests/unit/taxonomy/test_profile_subset_builder.py` → rename + rewrite as `test_cohort.py` covering `Cohort.filter` and `Cohort.write`.
  - `Tests/unit/taxonomy/test_taxonomy_facade.py` — update for the new return type / criteria name.
  - `Tests/unit/taxonomy/test_selectors.py` — update for the `FilterCriteria` rename.
  - `Tests/unit/taxonomy/test_public_namespace.py` — update re-exports.
  - `Tests/e2e/test_taxonomy_flow.py` — update for the rename.
  - New: `Tests/unit/metadata/test_metadata.py` covering `Metadata` construction validation, `reindex_to`, `filter`, `write`.
- Notebooks — `Notebooks/new.ipynb` if it references `ProfileSubset*` or `SubsetCriteria`. Filename outputs become `abundance_matrix.csv` + `metadata.csv`.

## Two-DataFrame rule

This design preserves the project's two-DataFrame rule from `CLAUDE.md`. The matrix and metadata DataFrames are never merged into a single frame. `Cohort` is a *pair*, not a join — it holds two `AbundanceMatrix` and `Metadata` value objects, each owning its own DataFrame(s).

## Non-goals

- No changes to `AbundanceMatrix`'s public surface (no new methods added).
- No changes to lineage resolution, taxon-key format, or `MatrixWriterFactory`.
- No changes to how the initial matrix is built from the taxonomy table (`AbundanceMatrixBuilder` is untouched).
- No new metadata-side analyses (descriptive stats, missingness, etc.). `Metadata` only houses operations that already exist today and are being relocated.

## Migration

One commit / one pass — every caller changes anyway because of the `FilterCriteria` rename and the `Cohort` introduction. Doing the `Metadata` extraction in the same pass is cheaper than threading it through later.
