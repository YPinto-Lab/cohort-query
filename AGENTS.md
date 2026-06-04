# AGENTS.md

## What this repo is
Ask-SLM is a microbiome/metagenomic query engine. Use `askslm.py` for scripted runs and `runner.ipynb` for interactive work.

## Workspace phase workflow (numbered phases)
A study lives in `Workspaces/<name>/` as phases handed off through files on disk:
`0_inputs/ -> 1_build/community.biom -> 2_transform/<exploration>/result/community.biom -> 3_analyze/<exploration>/<analysis>/{data,plots}`.

- **Scaffold with the CLI, never by hand:** `askslm workspace new <name>`, `askslm transform add <ws> <exploration>`, `askslm analysis add <ws> <exploration> <name>`.
- **Every phase script starts** `from askslm import workspace` then `ws = workspace.phase(__file__)`. No `sys.path` / `parents[N]`. Use `ws.inputs`, `ws.upstream()`, `ws.result`, `ws.data`, `ws.plots`, `ws.shared`.
- **Promotion rule:** write a step inline first; lift it into that phase's `shared.py` only when a 2nd script in the same phase needs it.
- **Two libraries:** general reusable logic lives in the `askslm` package; study-specific helpers live in `<phase>/shared.py`.
- **Naming:** explorations are intent-named (`no-control_bacteria`); analyses are grouped under their exploration by method (`braycurtis`).
- **Serialization:** communities are biom **JSON** (`to_json` / `load_table`) — HDF5 cannot round-trip the nested lineage metadata.
- Rationale and full model: `Docs/abundancetable.html` and `Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html`.

> Note: the legacy `## Workspace conventions` / `## CLI entrypoints` sections below describe the older `Workspaces/<ws>/{inputs,results}` layout and `askslm.py` command set, which the numbered-phase workflow supersedes for new studies.

## Architecture to respect
- Dependency flow is **Client -> Managers -> Engines -> Accessors**; do not call upward.
- Put orchestration in `managers/analysis_pipeline_manager.py`.
- Keep computations in `Engines/` and external I/O in `Accessors/`.
- Shared cross-layer payloads and schemas live in `Common/contracts/*`.

## Workspace conventions
- Canonical workspace layout is `Workspaces/<workspace>/inputs`, `mapping_configs`, and `results`.
- `SRAWorkspaceInputAccessor` accepts split inputs such as `metadata_*.csv`, `metadata_parts/*.csv`, `taxonomy_parts/*.csv`, then writes canonical `metadata.csv` / `taxonomy.csv` when needed.
- CLI path resolution defaults to workspace-native folders and is case-insensitive for folder names.

## Mapping and taxonomy rules
- `MappingEngine` is guided-config: first run writes `<project>.json.template`, later runs consume `<project>.json`.
- Metadata discovery comes from `jattr`, `attributes`, and direct metadata columns; `metadata-overview` reports all three sources.
- Taxonomy lineage uses the nested-set model (`ileft`/`iright`) via `TaxonomyAccessor` and `Accessors/TaxonomyAccessor/merged.dmp`.
- `build-taxonomy-lineage` creates `results/abundance_matrices/stage_05_accessor/taxon_query_db.json`; run it before `alpha-diversity`.

## DatasetAssemblyEngine artifact flow
- Stage order is `enrichment -> taxonomy_resolution -> aggregation -> final_assembly -> accessor`.
- Canonical abundance outputs are written in **Final Assembly**, not earlier stages.
- Key stage folders under `results/abundance_matrices/` are `stage_01_enrichment`, `stage_02_taxonomy_resolution`, `stage_03_aggregation`, `stage_04_final_assembly`, and `stage_05_accessor`.

## CLI entrypoints and aliases
- `askslm.py` is the primary CLI entrypoint; `cli.py` builds the parser.
- `--workspace` is canonical; `--view` is accepted only as a deprecated alias.
- Main commands: `metadata-overview`, `abundance-matrix`, `alpha-diversity`, `taxonomic-abundance`, `single-taxon-abundance`, `build-taxonomy-lineage`, `init`.

## Validation workflow
- Install dependencies from `Docs/requirements.txt`.
- Quick syntax check: `python -m py_compile askslm.py cli.py`.
- Smoke-test the CLI with `python askslm.py metadata-overview --workspace ABX` and `python askslm.py abundance-matrix --workspace ABX`.
- Tests are `unittest`-based; targeted examples include `python -m unittest Tests.unit.test_cli_top_values_formatting` and `python -m unittest Tests.e2e.test_cli_end_to_end`.

## Documentation maintenance
If you change flow, contracts, stage order, cache behavior, or outputs, update the relevant docs in the same change set (`Docs/CLAUDE.md`, `Docs/engineering-playbook.md`, and the focused docs under `Docs/product-documentation/*`).

