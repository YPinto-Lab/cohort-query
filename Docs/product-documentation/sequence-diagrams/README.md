# Ask-SLM Sequence Diagrams (Manager-Focused)

This folder intentionally contains only high-value operational flows that are useful for technical managers and maintainers.

## Diagram Set

1. `01-runner-orchestration-and-cache.wsd`
   - Main notebook-driven pipeline stages.
   - Legacy cache/stamp visualization kept for historical context.

2. `02-mapping-config-decision-flow.wsd`
   - Per-project mapping config handling.
   - Missing-config fallback behavior and strict-mode failure path.

3. `03-cli-runtime-and-lineage-guardrails.wsd`
   - Runtime path resolution (workspace directories and explicit overrides).
   - `build-taxonomy-lineage` and alpha-diversity lineage prerequisite.

4. `04-taxonomy-to-analysis-artifact-chain.wsd`
   - Taxonomy Resolution -> Aggregation -> Final Assembly -> Accessor dependency chain.

## Current Naming Notes

Current docs use artifact-first naming:

- Taxonomy stage is now **Taxonomy Resolution**
- Canonical outputs (`abundance_matrix.csv`, `abundance_maaslin.tsv`) are written in Final Assembly
- `results/abundance_matrices/` may be organized with stage subfolders

## Why This Reduced Set

- Removes low-value detail and visual noise.
- Focuses on flows that impact delivery risk, runtime cost, and operational behavior.
- Excludes logger internals and UI rendering detail.

## Render

Paste any `.wsd` file into https://www.websequencediagrams.com/app to render.
