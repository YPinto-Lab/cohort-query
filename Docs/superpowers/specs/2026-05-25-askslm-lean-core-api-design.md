# Ask-SLM Lean Core — API Reference & Design Spec

**Date:** 2026-05-25
**Status:** Approved design (target state for the deep refactor)
**Goal:** Refactor Ask-SLM down to a small, well-tested, well-documented core of clean
capabilities, so a UI/CLI ("final layer") can be built on top later with confidence.

This document is the **contract we refactor toward**. It is both the design spec and the
public API reference for the planned final codebase.

---

## 1. Motivation

The current codebase carries unneeded features, large multi-responsibility functions,
poor interface input/output, no unit tests, and stale documentation. The metadata
*mapping* work proved (via the demo) to be better handled by AI at the UI layer, not by
hand-written pipeline code.

The refactor keeps only the capabilities that are genuinely needed, expresses them as a
small set of clean functions with precise inputs/outputs, and tests each one.

---

## 2. Scope

### 2.1 Capabilities that survive (the lean core)

**Metadata**
1. `extract` — load SRA metadata and parse `jattr`/`attributes` blobs into a tidy table.
2. `overview` — summarize metadata: discovered keys, per-project counts, coverage matrix.

**Taxonomy**
3. `load` — read the taxonomy profile file into the long nested-set table.
4. `resolve` — remap deprecated NCBI tax_ids using `merged.dmp`.
5. `build_abundance_matrix` — pivot to a samples × taxa matrix, in several formats.
6. `get_profile_subset` — slice a built matrix by clade and/or sample, returning the
   profile and aligned metadata for downstream third-party analysis (scikit-bio, scipy, …).

### 2.2 Deleted

- `Managers/` (both managers) — no orchestration layer; composition is the caller's job.
- `Engines/MappingEngine/` — metadata mapping moves to the AI/UI layer.
- `Engines/EnvoResolutionEngine/`, `Accessors/OntologyAccessor/`,
  `Accessors/MetalogAccessor/`, `Scripts/scrape_metalog.py` — ENVO/ontology decoding
  dropped; removes the network dependency from the core.
- `Engines/DownstreamAnalysis/` (AlphaDiversity, TaxonomicAbundance, Longitudinal) —
  downstream statistics are the user's job via third-party libraries on a profile subset.
- `Engines/DatasetAssemblyEngine/` stage/fingerprint/caching machinery and the merged
  `analysis_wide_dataset` — replaced by direct, composable functions.
- The **persisted** lineage DB (`taxon_query_db.json` build/save/load) — lineage becomes an
  in-memory, lazily-computed lookup on the abundance matrix (see §6).
- The fat `cli.py` command bodies and all plotting — these belong to the deferred UI layer.

**Relocated, not lost:** taxonomy resolution, count aggregation, nested-set ancestry, and
`jattr`/`attributes` scanning are preserved as small focused classes in the new engines.

### 2.3 Deliberately out of scope (YAGNI for now)

- A `Workspace` abstraction. If revived later, it must be a thin convenience wrapper over
  these functions — not a precondition for using them.
- Idempotency / disk caching. Functions are pure compute; persistence is explicit.
- Multi-condition sample filtering (AND across columns). A `SampleSelector` filters one
  column; callers needing more pre-filter the metadata DataFrame.
- BIOM is supported as an output format; no BIOM *input* path.

---

## 3. Architecture

### 3.1 Layering

`Client → Engine → Accessor`. The Manager layer is removed. Each domain owns a pure-logic
**Engine** and a thin I/O **Accessor**. The public API is a thin facade of callables that
delegate to engine classes.

```
askslm/                         # thin public facade: `metadata`, `taxonomy` namespaces
Engines/
  MetadataEngine/
    metadata_extractor.py       # MetadataExtractor
    source_key_scanner.py       # SourceKeyScanner   (scans jattr/attributes)
    metadata_overview_builder.py# MetadataOverviewBuilder
    metadata_summary_builder.py # MetadataSummaryBuilder
    metadata_matrix_builder.py  # MetadataMatrixBuilder
  TaxonomyEngine/
    taxonomy_resolver.py        # TaxonomyResolver
    abundance_matrix_builder.py # AbundanceMatrixBuilder
    nested_set_lineage_resolver.py # NestedSetLineageResolver
    profile_subset_builder.py   # ProfileSubsetBuilder
Accessors/
  MetadataAccessor/             # read metadata.csv
  TaxonomyAccessor/             # read taxonomy.csv
  MergedDumpAccessor/           # read merged.dmp
  matrix_writers/               # CountsWriter, RelativeWriter, MaaslinWriter, BiomWriter
Common/
  contracts/                    # schemas + result DTOs + selectors
Tests/
  unit/  e2e/
```

### 3.2 Clean-code rules applied (binding)

- **OOP**: one class per file; the public callables are a thin facade over engine classes.
- **Functions ≤ 10 lines, one thing**; extract helpers when they grow.
- **≤ 3 parameters**; group related params into frozen dataclasses.
- **Pass only what is used** — fields, not whole objects, unless the whole is needed.
- **No `else`** — guard clauses or polymorphism (e.g., per-format matrix writers).
- **Naming**: short active verbs for facades (`extract`, `resolve`, `load`); long
  descriptive names for low-level helpers; pattern suffixes (`Builder`, `Resolver`,
  `Writer`, `Accessor`); banned words avoided (`data`, `info`, `manager`, `handler`,
  `util`, `helper`, `temp`, `obj`).
- **Type hints** on all public functions; `pathlib.Path` over strings; `logging` over
  `print`; `@dataclass(frozen=True)` for DTOs/value objects.

### 3.3 Two-DataFrame rule

`metadata_df` and `taxonomy_df` stay separate. They are aligned only inside `ProfileSubset`,
and even there they remain two DataFrames (`profile_df`, `metadata_df`) — never merged.

---

## 4. Public API Reference

Import surface:

```python
from askslm import metadata, taxonomy
```

### 4.1 `metadata.extract`

```python
def extract(source: str | Path | pd.DataFrame) -> pd.DataFrame
```

Read SRA metadata (a CSV path or a pre-loaded DataFrame) and normalize to the canonical
per-sample table keyed by `acc`. Parses the `jattr` / `attributes` JSON blobs into columns
so downstream code sees real fields, not raw blobs.

- **Returns:** `metadata_df` conforming to `SRAMetadataSchema` (plus discovered columns).
- **Backed by:** `MetadataAccessor` (read) → `MetadataExtractor` (normalize/parse).
- **Pure** apart from the read boundary; deterministic; safe to call repeatedly.

### 4.2 `metadata.overview`

```python
def overview(metadata_df: pd.DataFrame) -> MetadataOverview
```

Summarize a single extracted `metadata_df`. No raw/enriched duality, no network, no
MappingEngine.

- **Returns:** `MetadataOverview` (see §5.2).
- **Backed by:** `MetadataOverviewBuilder` orchestrating `SourceKeyScanner`,
  `MetadataSummaryBuilder`, `MetadataMatrixBuilder`.

### 4.3 `taxonomy.load`

```python
def load(source: str | Path) -> pd.DataFrame
```

Read the taxonomy profile file into the long table.

- **Returns:** `taxonomy_df` conforming to `SRATaxonomySchema` — includes the nested-set
  columns `ileft`, `iright`, `ilevel` that power lineage filtering (§6).
- **Backed by:** `TaxonomyAccessor`.

### 4.4 `taxonomy.resolve`

```python
def resolve(taxonomy_df: pd.DataFrame, merged_dmp: Path = DEFAULT_MERGED_DMP) -> ResolvedTaxonomy
```

Remap deprecated NCBI tax_ids to their current ids using `merged.dmp`.

- **Returns:** `ResolvedTaxonomy` (see §5.3).
- **Backed by:** `MergedDumpAccessor` (read map) → `TaxonomyResolver`.

### 4.5 `taxonomy.build_abundance_matrix`

```python
def build_abundance_matrix(taxonomy_df: pd.DataFrame, rank: str | None = None) -> AbundanceMatrix
```

Pivot the (resolved) long table into a samples × taxa matrix. Optional `rank` collapses
counts to a taxonomic rank (e.g. `"genus"`).

- **Returns:** `AbundanceMatrix` (see §5.4) — carries `.counts`, lazy `.relative`, and a
  lazy lineage-bearing `.taxa` lookup.
- **Backed by:** `AbundanceMatrixBuilder` (+ `NestedSetLineageResolver` for `.taxa`).
- **Output formats** via `AbundanceMatrix.write(path, fmt=...)`: `"counts"`, `"relative"`,
  `"maaslin"`, `"biom"`. Each format is a `MatrixFormatWriter` strategy (no if/elif ladder).

### 4.6 `taxonomy.get_profile_subset`

```python
def get_profile_subset(
    matrix: AbundanceMatrix,
    metadata_df: pd.DataFrame,
    criteria: SubsetCriteria,
) -> ProfileSubset
```

Slice an already-built matrix by clade (`criteria.taxa`) and/or sample
(`criteria.samples`), and return the profile together with aligned metadata, ready to hand
to third-party libraries.

- **Returns:** `ProfileSubset` (see §5.5): `.profile_df` (always), `.metadata_df`
  (lazy, aligned on the shared `acc` index).
- **Backed by:** `ProfileSubsetBuilder`, using `matrix.taxa` for clade ancestry (§6).
- **Run order:** after `build_abundance_matrix`. Build once, subset many times.

---

## 5. Contracts & value objects (`Common/contracts`)

Schemas, result DTOs, and selectors live in `Common/contracts/` and are re-exported through
the public facade as `askslm.contracts` for callers.

### 5.1 Schemas (kept, pandera)

- `SRAMetadataSchema` — one row per `acc`; no taxonomy columns.
- `SRATaxonomySchema` — many rows per `acc`; nested-set tree + per-taxon counts.

### 5.2 `MetadataOverview` (frozen dataclass)

```python
summary_df: pd.DataFrame               # overall metrics
projects_df: pd.DataFrame              # per-project sample counts
discovered_keys_df: pd.DataFrame       # discovered source keys, by project
discovered_keys_unique_df: pd.DataFrame# discovered source keys, deduped
coverage_matrix_df: pd.DataFrame       # key coverage across projects
def write(self, out_dir: Path) -> list[Path]
```

### 5.3 `ResolvedTaxonomy` (frozen dataclass)

```python
df: pd.DataFrame          # resolved long taxonomy table
changes_df: pd.DataFrame  # which tax_ids were remapped
summary: ResolutionSummary# counts (rows_updated, unique_ids_updated, …)
```

### 5.4 `AbundanceMatrix` (value object)

```python
counts: pd.DataFrame             # samples × taxa, int
relative: pd.DataFrame           # lazy, row-normalized proportions
taxa: pd.DataFrame               # lazy lineage lookup: taxon_key → ancestor ranks
def write(self, path: Path, fmt: str = "counts") -> Path
```

### 5.5 `ProfileSubset` (value object)

```python
profile_df: pd.DataFrame   # filtered samples × taxa (always loaded)
metadata_df: pd.DataFrame  # aligned metadata (lazy, same sample order)
def write(self, out_dir: Path) -> list[Path]
```

### 5.6 Selectors (frozen dataclasses)

```python
@dataclass(frozen=True)
class TaxaSelector:
    rank: str                  # e.g. "superkingdom"
    names: tuple[str, ...]     # e.g. ("Bacteria",)

@dataclass(frozen=True)
class SampleSelector:
    column: str                # metadata column, e.g. "Group"
    values: tuple[str, ...]    # kept values, e.g. ("treatment",)

@dataclass(frozen=True)
class SubsetCriteria:
    taxa: TaxaSelector | None = None
    samples: SampleSelector | None = None
```

---

## 6. Lineage without a persisted database

The taxonomy table already carries the nested-set columns (`ileft`, `iright`) per
accession. Ancestry is therefore derivable directly — the old persisted
`taxon_query_db.json` is redundant.

`build_abundance_matrix` computes a **lineage lookup once** (lazy `.taxa`) via
`NestedSetLineageResolver`: for the union of taxa, map each taxon to its ancestor ranks
(superkingdom, phylum, …) using nested-set containment
(`ancestor.ileft <= node.ileft AND ancestor.iright >= node.iright`).

`get_profile_subset` then resolves `TaxaSelector(rank="superkingdom", names=("Bacteria",))`
to the set of taxon columns whose lineage includes that clade, and keeps those columns.
Result: "build once, subset many," with lineage held in one place, in memory, never
persisted.

---

## 7. Persistence model

Functions return in-memory value objects. Persistence is **explicit** via each value
object's `write(...)`. There is no automatic disk-first behavior, no idempotency cache, and
no fingerprinting in the core. Such concerns, if ever needed, belong to the deferred UI
layer as a thin wrapper.

---

## 8. Testing strategy

`pytest`, AAA pattern (Arrange / Act / Assert with blank-line separation).

- **Unit (engines):** each engine class tested in isolation with small DataFrame fixtures;
  pure, no I/O. Cover happy path + edge cases (empty input, deprecated id remap, missing
  clade, sample filter with no matches, nested-set ancestry correctness).
- **Accessor:** read/write against temporary files (`tmp_path`).
- **End-to-end:** a tiny fixture dataset exercised through
  load → resolve → build_abundance_matrix → get_profile_subset, asserting profile/metadata
  alignment and format outputs.

Every one of the six public capabilities has direct unit coverage — closing the current
"no unit tests" gap.

---

## 9. Documentation plan

- This API Reference is the canonical contract.
- Docstrings on the six public functions and each value object.
- A short usage `README` showing the canonical flow and a `get_profile_subset` → scikit-bio
  example.
- Stale `.md` sprawl and the heavy product-documentation diagrams are removed.

---

## 10. Canonical usage

```python
from askslm import metadata, taxonomy
from askslm.contracts import SubsetCriteria, TaxaSelector, SampleSelector

metadata_df = metadata.extract("metadata.csv")
report = metadata.overview(metadata_df)

taxonomy_df = taxonomy.load("taxonomy.csv")
taxonomy_df = taxonomy.resolve(taxonomy_df).df

matrix = taxonomy.build_abundance_matrix(taxonomy_df)
matrix.write("abundance_maaslin.tsv", fmt="maaslin")

subset = taxonomy.get_profile_subset(
    matrix,
    metadata_df,
    SubsetCriteria(
        taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)),
        samples=SampleSelector(column="Group", values=("treatment",)),
    ),
)

# hand off to third-party analysis
subset.profile_df    # samples × bacterial taxa
subset.metadata_df   # aligned metadata for PERMANOVA / ordination
```
