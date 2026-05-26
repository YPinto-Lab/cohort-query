# Ask-SLM

A small, well-tested Python toolkit for metagenomic analysis of SRA datasets. Public API exposes two domains — `metadata` and `taxonomy` — and is designed to hand its output to third-party libraries (scikit-bio, scipy, MaAsLin2, …) for downstream statistics.

## Install

```bash
pip install -r Docs/requirements.txt
```

Python 3.11+ recommended.

## Canonical usage

```python
from askslm import metadata, taxonomy
from askslm.contracts import SubsetCriteria, TaxaSelector, SampleSelector

# Metadata: expand jattr/attributes blobs into real columns, then summarize.
metadata_df = metadata.extract("metadata.csv")
overview = metadata.overview(metadata_df)
overview.write("out/metadata_overview")

# Taxonomy: load → resolve deprecated NCBI tax_ids → build a single-rank,
# non-overlapping abundance matrix (default rank='genus', value = each rank-node's
# total_count, plus one Unclassified_<rank> bucket per sample).
taxonomy_df = taxonomy.load("taxonomy.csv")
resolved    = taxonomy.resolve(taxonomy_df)
matrix      = taxonomy.build_abundance_matrix(resolved.df)
matrix.write("out/abundance_maaslin.tsv", fmt="maaslin")

# Slice the matrix by clade + sample for downstream analysis. The subset returns
# two aligned DataFrames; they are never merged (two-DataFrame rule).
subset = taxonomy.get_profile_subset(
    matrix,
    metadata_df,
    SubsetCriteria(
        taxa=TaxaSelector(rank="superkingdom", names=("Bacteria",)),
        samples=SampleSelector(column="Group", values=("treatment",)),
    ),
)
subset.profile_df    # samples × bacterial taxa
subset.metadata_df   # aligned metadata, lazy
```

## Design

- Architecture and API contract: `Docs/superpowers/specs/2026-05-25-askslm-lean-core-api-design.md`
- Why abundance is single-rank `total_count` + `Unclassified_<rank>` (avoids double-counting cumulative clade counts): `Docs/superpowers/decisions/2026-05-25-abundance-count-semantics.md`

## Tests

```bash
python -m pytest Tests -q
```
