# Ask-SLM Engineering Documentation Starter Outline

Use this as a structure for onboarding and design communication.

## 1. Product Purpose

- What Ask-SLM solves
- Typical users (research engineers, bioinformatics analysts)
- Core capabilities and non-goals

## 2. Data Contracts

- `metadata.csv`: one row per sample (`acc`)
- `taxonomy.csv`: many rows per sample (taxon observations)
- Workspace-native layout (primary): `Workspaces/<view>/inputs/`, `mapping_configs/`, `results/`, `Logs/`
- Path resolution precedence: explicit CLI overrides -> workspace defaults under `Workspaces/<view>/`

Recommended diagrams:
- `sequence-diagrams/01-runner-orchestration-and-cache.wsd`
- `sequence-diagrams/04-taxonomy-to-analysis-artifact-chain.wsd`

## 3. Runner Architecture

- Notebook as thin orchestrator
- Runner orchestration responsibilities in `managers/runner_pipeline_manager.py`
- Stage outputs and artifact locations
- Runner input accessor behavior in `Accessors/SraAccessor/sra_workspace_input_accessor.py`
- Canonical-input no-rewrite optimization to avoid false cache invalidation

Recommended diagrams:
- `sequence-diagrams/01-runner-orchestration-and-cache.wsd`
- `sequence-diagrams/04-taxonomy-to-analysis-artifact-chain.wsd`

## 4. Metadata Standardization

- Template discovery and generation
- Target-first mapping UX
- Project-level config persistence and versioning strategy

Recommended diagrams:
- `sequence-diagrams/02-mapping-config-decision-flow.wsd`

## 5. Ontology Enrichment

- ENVO ID detection
- OLS4 lookup and fallback behavior
- Dictionary export and cache strategy

Recommended diagrams:
- `sequence-diagrams/01-runner-orchestration-and-cache.wsd`

## 6. Analysis Execution Paths

- Notebook interactive engines (`MappingConfigEngine`, `AlphaDiversityEngine`, `TaxonomicAbundanceEngine`)
- CLI non-interactive command flows (`metadata-overview`, `abundance-matrix`, `build-taxonomy-lineage`, `alpha-diversity`, `taxonomic-abundance`, `single-taxon-abundance`)
- Expected outputs for each mode

Recommended diagrams:
- `sequence-diagrams/03-cli-runtime-and-lineage-guardrails.wsd`
- `sequence-diagrams/04-taxonomy-to-analysis-artifact-chain.wsd`

## 7. Operational Concerns

- Per-run logging
- Incremental rebuild via stage stamps
- Stamp dependency graph:
	- `enrichment_stage_stamp.json` depends on `inputs/metadata.csv` state and per-project mapping config states
	- `taxonomy_stage_stamp.json` depends on `inputs/taxonomy.csv` state and `taxon_key_sep`
	- `merge_stage_stamp.json` depends on enrichment + taxonomy stamps
	- `taxonomy_lineage_db_stamp.json` in runner depends on taxonomy stage stamp; in CLI lineage build it depends on taxonomy file hash
- Output/cache paths:
	- `Workspaces/<view>/results/<analysis>/`
	- `Workspaces/<view>/results/_cache/`
- Known failure modes and recovery playbook

## 8. Testing Strategy

- Unit tests by workflow function
- Integration tests by view
- End-to-end CLI regression tests

## 9. Future Evolution

- Lineage DB performance roadmap
- Mapping config validation hardening
- Longitudinal manager interface alignment

## 10. CLI Data Enrichment Notes

- Source-key extraction for CLI output supports:
	- direct metadata columns,
	- `jattr` JSON keys (case-insensitive),
	- `attributes` key-value text (case-insensitive)
- Value normalization rules include empty/null cleanup and float-like integer cleanup (for example `5.0` -> `5`)
- `single-taxon-abundance` and `metadata-overview` rely on this enrichment behavior for report readability