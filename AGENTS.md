# AGENTS.md

## What this repo is
Ask-SLM is a workbench for reproducible metagenomic analysis. The user drives everything through
the web UI; the LLM agent authors and runs Python using the `askslm` package and the domain
library palette to build and analyze studies as workspaces of phase scripts.

## Architecture

- `src/askslm/` — the toolbox the agent calls (workspace phase tooling, metadata, taxonomy, accessors, cli).
- `src/agent/` — the LLM agent (run_python, session, registry).
- `src/web/` — the web UI; the only surface the user touches.

Dependencies flow downward: agent and web call `askslm`, never the reverse.

## Workspace phase workflow (numbered phases)
A study lives in `Workspaces/<name>/` as phases handed off through files on disk:
`0_inputs/ -> 1_build/feature_table.biom -> 2_transform/<exploration>/result/feature_table.biom -> 3_analyze/<exploration>/<analysis>/{data,plots}`.

- **Scaffold with the CLI, never by hand:** `askslm workspace new <name>`, `askslm transform add <ws> <exploration>`, `askslm analysis add <ws> <exploration> <name>`.
- **Every phase script starts** `from askslm import workspace` then `ws = workspace.phase(__file__)`. No `sys.path` / `parents[N]`. Use `ws.inputs`, `ws.upstream()`, `ws.result`, `ws.data`, `ws.plots`, `ws.shared`.
- **Promotion rule:** write a step inline first; lift it into the phase-level `shared.py` (one per `2_transform` / `3_analyze`, shared across all explorations/analyses) only when a 2nd script in that phase needs it.
- **Two libraries:** general reusable logic lives in the `askslm` package; study-specific helpers live in `<phase>/shared.py`.
- **Naming:** explorations are intent-named (`no-control_bacteria`); analyses are grouped under their exploration by method (`braycurtis`).
- **Serialization:** communities are biom **JSON** (`to_json` / `load_table`) — HDF5 cannot round-trip the nested lineage metadata.
- Rationale and full model: `Docs/feature-table-and-library-palette.html` and `Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html`.

## Validation workflow
- Install dependencies: `pip install -r Docs/requirements.txt && pip install -e .`
- Run the test suite: `python -m pytest Tests -q`.
- Verify the canonical example by running the phase scripts under `Workspaces/ABX_new` in order.

## Documentation maintenance
If you change flow, contracts, phase structure, or outputs, update the relevant docs in the same
change set: `CLAUDE.md`, `AGENTS.md`, and `Docs/feature-table-and-library-palette.html`.
