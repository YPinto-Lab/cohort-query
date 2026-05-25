# ADR: Abundance matrix count semantics (single-rank `total_count` + Unclassified bucket)

**Date:** 2026-05-25
**Status:** Accepted
**Affects:** `taxonomy.build_abundance_matrix`, `AbundanceMatrix`, `taxonomy.get_profile_subset`
(spec §4.5 / §5.4). Supersedes the initial Plan 1 implementation (Tasks 7/8/12), which is to
be revised.

## Context

Each taxonomy row sits in a **per-accession nested set** and carries two counts:

- **`self_count`** — reads assigned **directly** to that taxon node (resolved to exactly that
  level, no finer). Kraken's "taxon count."
- **`total_count`** — reads for that node **and its entire subtree** — the cumulative
  **clade count**. Kraken's "clade count."

Because `total_count` is cumulative, a parent node's value already *contains* its children's
(`Bacteria.total_count` ⊇ `Proteobacteria.total_count` ⊇ `Escherichia.total_count`).

The first implementation built the matrix from **every** taxon at **every** rank using
`total_count`, producing **overlapping** columns. Summing `total_count` across a subtree (or
treating nested nodes as independent features) **double-counts** reads and would distort any
distance / ordination / compositional analysis. This was a correctness defect.

## Decision

1. **Single rank.** `build_abundance_matrix(taxonomy_df, rank="genus")` produces a matrix
   whose features are the nodes **at one rank**. Default `rank="genus"` (more stable and less
   sparse than species for cross-sample comparison).
2. **Value = the rank-node's own `total_count`.** Sibling clades at a fixed rank do not
   overlap, so this is non-overlapping and read-consistent. **Never sum `total_count` across
   nodes.** (Equivalently: a node's `total_count` already equals the sum of `self_count` over
   its subtree.)
3. **`Unclassified_<rank>` bucket.** Reads that stopped above `rank` — i.e. the `self_count`
   of every ancestor node coarser than `rank` — are pooled, per sample, into a single
   `Unclassified_<rank>` feature. This preserves per-sample totals, so `relative` rows are
   honest compositions that sum to 1.
4. **`get_profile_subset` operates on this single-rank matrix.** A clade filter
   (`TaxaSelector(rank="superkingdom", names=("Bacteria",))`) keeps the rank-level features
   whose lineage passes through the clade; the `Unclassified_<rank>` feature has no lineage
   and is excluded by any clade filter.

## Worked example (one sample, collapse to genus)

```
rank          name             self   total
superkingdom  Bacteria          10    100     # 10 reads only ID'd as "Bacteria"
  phylum      Firmicutes         5     30      # 5 reads only ID'd as "Firmicutes"
    genus     Lactobacillus     25     25
  phylum      Proteobacteria     0     60
    genus     Escherichia       50     50
    genus     Salmonella        10     10
```

Collapse to **genus** → take each genus node's `total_count`:

```
Lactobacillus 25, Escherichia 50, Salmonella 10                 (= 85)
Unclassified_genus = Bacteria.self(10) + Firmicutes.self(5)     (= 15)
sample total = 100  ✓   (matches Bacteria.total_count)
```

Relative abundance of Escherichia = 50 / 100 = **50%** (honest), not 50 / 85 = 59% (what
dropping the unresolved reads would have produced).

## Consequences

- Matrix columns are non-overlapping; `relative` is a true composition; distance/ordination
  on a `get_profile_subset` result is meaningful.
- `rank` becomes a primary parameter of `build_abundance_matrix` (default `genus`).
- Tasks 7/8/12 of Plan 1 (and their tests + the tiny fixture) must be revised to this model.

## Alternatives considered

- **All nodes, `self_count`** — non-overlapping and loses no reads, but features sit at mixed
  ranks, which is non-standard for distance/compositional work.
- **Drop unresolved reads** — simpler, but inflates relative abundances and hides the
  unresolved fraction.
- **Keep overlapping multi-rank `total_count`** — rejected: double-counts, easy to misuse.
