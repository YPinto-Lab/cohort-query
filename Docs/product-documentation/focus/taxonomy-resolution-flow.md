# Taxonomy Resolution Flow (Artifact-First)

This page answers:

- Where Taxonomy Resolution sits in the pipeline
- Where artifacts are written in `abundance_matrices/`
- Why final matrix files are written only in Final Assembly

## Stage Order

1. Enrichment
2. Taxonomy Resolution
3. Aggregation
4. Final Assembly
5. Accessor

## Key Rule

If any stage before Final Assembly fails, Final Assembly does not run.

This prevents partial or misleading `abundance_matrix.csv` and `abundance_maaslin.tsv` outputs.

## Output Layout

```text
results/abundance_matrices/
├── manifests/pipeline_manifest.json
├── stage_01_enrichment/
├── stage_02_taxonomy_resolution/
├── stage_03_aggregation/
├── stage_04_final_assembly/
└── stage_05_accessor/
```

## Taxonomy Resolution Stage Outputs

In `stage_02_taxonomy_resolution/`:

- `resolved_taxonomy.csv`
- `taxonomy_resolution_changes.csv`
- `taxonomy_resolution_summary.json`

This stage resolves deprecated tax IDs and records exactly what changed.
It does not write canonical matrix outputs.

## Final Assembly Outputs

In `stage_04_final_assembly/`:

- `abundance_matrix.csv` (wide canonical output)
- `abundance_maaslin.tsv` (MaAsLin canonical output)
- `analysis_wide_dataset.csv`
- `merge_summary.json`

## Resume Behavior

On startup, engine computes input-folder hash and validates required artifacts.
If hash matches and all required outputs are valid, engine stops with no work.
If hash differs or files are missing, engine resumes from first invalid stage.
