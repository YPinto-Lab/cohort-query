# Ask-SLM Engineering Documentation Starter Outline

Use this as a structure for onboarding and design communication.

## 1. Product Purpose

- What Ask-SLM solves
- Typical users (research engineers, bioinformatics analysts)
- Core capabilities and non-goals

## 2. Data Contracts

- `metadata.csv`: one row per sample (`acc`)
- `taxonomy.csv`: many rows per sample (taxon observations)
- View-scoped workspace layout under `Workspaces/<view>/`

Recommended diagrams:
- `sequence-diagrams/00-system-context.wsd`
- `sequence-diagrams/02-input-aggregation-and-canonicalization.wsd`

## 3. Runner Architecture

- Notebook as thin orchestrator
- Runner orchestration responsibilities in `managers/runner_pipeline_manager.py`
- Stage outputs and artifact locations

Recommended diagrams:
- `sequence-diagrams/01-runner-end-to-end.wsd`
- `sequence-diagrams/04-stage-cache-decisions.wsd`

## 4. Metadata Standardization

- Template discovery and generation
- Target-first mapping UX
- Project-level config persistence and versioning strategy

Recommended diagrams:
- `sequence-diagrams/03-mapping-config-lifecycle.wsd`

## 5. Ontology Enrichment

- ENVO ID detection
- OLS4 lookup and fallback behavior
- Dictionary export and cache strategy

Recommended diagrams:
- `sequence-diagrams/05-envo-resolution-flow.wsd`

## 6. Analysis Execution Paths

- Notebook interactive managers
- CLI non-interactive command flows
- Expected outputs for each mode

Recommended diagrams:
- `sequence-diagrams/07-manager-runtime-interaction.wsd`
- `sequence-diagrams/06-cli-analysis-flow.wsd`

## 7. Operational Concerns

- Per-run logging
- Incremental rebuild via stage stamps
- Known failure modes and recovery playbook

## 8. Testing Strategy

- Unit tests by workflow function
- Integration tests by view
- End-to-end CLI regression tests

## 9. Future Evolution

- Lineage DB performance roadmap
- Mapping config validation hardening
- Longitudinal manager interface alignment