# Cohort enrichment and splitting — design

**Date:** 2026-05-27
**Status:** Approved

## Motivation

An agent operating on cohorts frequently needs two operations that currently require generating ad-hoc pandas code:

1. **Attaching external data** — a researcher loads cluster assignments, clinical variables, or any per-subject table from an external source (Excel, CSV, or an in-memory DataFrame the agent computed) and wants those columns available on every sample in the cohort.
2. **Splitting a cohort by a label** — once a grouping column exists on the metadata, the agent partitions the cohort into one sub-cohort per unique label for downstream per-group analysis.

Without library support, the agent must write a `for cluster_id, group in df.groupby(...)` loop with manual `cohort.filter(FilterCriteria(...))` calls — leaking pandas internals into agent code and requiring knowledge of `host_subject_id_sam`, `acc`, and the internal `metadata.df` attribute.

Additionally, the agent currently inspects cohort shape and column values by reaching into `cohort.matrix.counts.shape` and `cohort.metadata.df[column].unique()`, which exposes implementation detail.

## Library boundary principle

The library owns cohort shape: filtering, splitting, enriching, and inspecting which samples or taxa are present. Statistical analysis — diversity metrics, ordination, differential abundance — belongs to the agent, which calls whitelisted domain libraries (scikit-bio, MaAsLin2, scipy) directly. The library never wraps statistics.

## Design

### 1. `Cohort.enrich(df, *, left_on, right_on) → Cohort`

Left-joins `df` onto the cohort's metadata on the given key columns. Any column in `df` except `right_on` is added to `metadata.df`. Samples with no match in `df` receive `NaN` in the new columns.

```python
def enrich(
    self,
    df: pd.DataFrame,
    *,
    left_on: str,
    right_on: str,
) -> Cohort:
```

**Semantics:**

- `left_on` — column in `self.metadata.df` to join on (e.g. `"host_subject_id_sam"`)
- `right_on` — column in `df` to join on (e.g. `"Subject"`)
- Broadcast-safe: if `df` is subject-level (one row per subject) and metadata is sample-level (many rows per subject), every sample for a subject receives the same values.
- Returns a new `Cohort` — same `matrix`, enriched `Metadata`.
- Raises `ValueError` if `left_on` is not a column in `metadata.df`.
- Raises `ValueError` if `right_on` is not a column in `df`.

**Usage:**

```python
import pandas as pd

cluster_map = pd.read_excel("Viral_Ecological_Clusters_Master_Map-v2.xlsx", sheet_name="Cluster Mapping")

enriched = cohort.enrich(cluster_map, left_on="host_subject_id_sam", right_on="Subject")
```

---

### 2. `Cohort.split_by(column) → dict[str, Cohort]`

Partitions the cohort into one sub-cohort per unique value of `column` (which must exist in `metadata.df`). The returned dict maps each unique value to a fully aligned `Cohort`.

```python
def split_by(self, column: str) -> dict[str, Cohort]:
```

**Semantics:**

- `column` — column in `self.metadata.df` whose unique values become the dict keys.
- Each sub-cohort's matrix is row-filtered to only the samples that appear in that group's metadata.
- Raises `ValueError` if `column` is not in `metadata.df`.
- Samples with `NaN` in `column` are excluded from the result.

**Usage:**

```python
cluster_cohorts = (
    cohort
    .enrich(cluster_map, left_on="host_subject_id_sam", right_on="Subject")
    .split_by("Cluster_ID")
)

for cid, c in cluster_cohorts.items():
    print(cid, c.n_samples, c.n_taxa)
```

---

### 3. `Cohort.n_samples` and `Cohort.n_taxa` — shape properties

```python
@property
def n_samples(self) -> int:
    return self.matrix.counts.shape[0]

@property
def n_taxa(self) -> int:
    return self.matrix.counts.shape[1]
```

Hides `matrix.counts.shape` from the agent. No logic — pure delegation.

---

### 4. `Cohort.unique(column) → list[str]`

```python
def unique(self, column: str) -> list[str]:
```

Returns the sorted unique values of `column` in `metadata.df` as a plain Python list. Hides `metadata.df` from the agent.

- Raises `ValueError` if `column` is not in `metadata.df`.

**Usage:**

```python
cohort.unique("assay_type")   # ["WGS"]
cohort.unique("Cluster_ID")   # ["1", "2", "3", "4"]
```

---

## Files changed

| File | Change |
|---|---|
| `Engines/TaxonomyEngine/cohort.py` | Add `enrich`, `split_by`, `n_samples`, `n_taxa`, `unique` |
| `tests/unit/taxonomy/test_cohort.py` | Unit tests for all four additions |

No new files. No changes to contracts, selectors, or public facades — `Cohort` is already exported via `askslm.taxonomy`.

## Testing

Each method gets a focused unit test:

- `enrich`: broadcast join (subject-level df → sample-level metadata), missing subjects → NaN, invalid column → ValueError
- `split_by`: correct partitioning, no cross-contamination, NaN rows excluded, invalid column → ValueError
- `n_samples` / `n_taxa`: trivial shape checks
- `unique`: sorted list, invalid column → ValueError
