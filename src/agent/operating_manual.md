---
kind: reference
audience: ask-slm runtime agent
intent: the durable operating model + a pointer map to authoritative sources
---

# How to work in Ask-SLM

You build and analyze metagenomic studies by authoring and running Python against the `askslm`
package and established libraries (biom, ete3, scikit-bio, scipy, pandas). The disk is the source
of truth. Reuse what `askslm` provides — never hand-roll what the package already does.

## Vocabulary & model
- A **feature table** is ONE `biom.Table`: counts (features × samples) + sample metadata + feature
  metadata (lineage). One feature table per community study.
- A **community** is one sample's microbes (biological).
- Five operation kinds: ingest, build, transform, split, analyze.

## Count semantics (non-negotiable — getting this wrong silently corrupts results)
- `self_count` is the ATOMIC, direct count at a taxon.
- `total_count` is CUMULATIVE over the taxon's whole clade.
- NEVER sum `total_count` across the tree. Build the counts matrix from `self_count`.

## Phase flow
Work is organized into numbered phases on disk:
`0_inputs → 1_build → 2_transform/<exploration> → 3_analyze/<exploration>/<analysis>`.

- **Build** (run once): read each raw source with one Accessor, assemble ONE `biom.Table`
  (counts from `self_count` + lineage feature metadata + sample metadata), then write it as biom
  **JSON** to `1_build/feature_table.biom`. Use JSON, not HDF5 — HDF5 cannot round-trip nested
  lineage metadata.
- **Transform**: shape the upstream feature table, write `result/feature_table.biom`.
- **Analyze**: measure a feature table, write CSVs/plots.

Inside a phase script, `from askslm import workspace; ws = workspace.phase(__file__)` gives you
`ws.inputs`, `ws.result`, `ws.data`, `ws.plots`, `ws.shared`, and `ws.upstream()`.

## When you need more, read the source (use the read_file / list_dir tools)
| Need | Read |
|------|------|
| the feature-table model / library palette (the bible) | `Docs/feature-table-and-library-palette.html` |
| phase-tree organization rationale | `Docs/superpowers/specs/2026-06-03-workspace-phase-organization-design.html` |
| workspace tooling rationale | `Docs/superpowers/specs/2026-06-03-workspace-tooling-design.html` |
| a worked example done right | `Workspaces/ABX_new` (read its `1_build/build.py`) |
| real `askslm` signatures & behavior | `src/askslm/` (e.g. `accessors/`, `workspace.py`, `sra_schema.py`) |
| the code-quality bar for any code you write | `Docs/agent-code-standards.md` |

Do NOT read large data files (e.g. `taxonomy.csv` can be hundreds of MB) into context — inspect
their shape with `run_python` instead.
