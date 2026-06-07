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

## The build recipe (use the askslm facade — do NOT hand-roll the cleaning)
SRA inputs are messy: duplicate rows, an accession repeated many times, one `tax_id` listed under
several names. `askslm` already handles all of that. Build the table with these calls — never
reinvent the cleaning with raw `pd.read_csv` + `DataFrame.pivot`.

**Always build ONE feature table from ALL the data — use every row, across all bioprojects.
Never filter to a single bioproject or otherwise subset the inputs at build time.**

    import pandas as pd
    from biom import Table
    from askslm import metadata, taxonomy, workspace

    ws = workspace.phase(__file__)

    # counts: features (tax_id) x samples (acc), atomic self_count.
    # pivot_table with aggfunc="sum" — NOT DataFrame.pivot, which dies on duplicate rows.
    tax = taxonomy.load(str(ws.inputs / "taxonomy.csv"))
    counts = tax.pivot_table(index="tax_id", columns="acc", values="self_count",
                             aggfunc="sum", fill_value=0)

    # feature metadata: one clean lineage row per tax_id (resolves the multi-name problem).
    features = taxonomy.lineage_table(counts.index)

    # sample metadata: one biom-castable row per acc.
    samples = metadata.extract(str(ws.inputs / "metadata.csv")).set_index("acc")

    # assemble ONE biom.Table = counts + feature metadata + sample metadata.
    table = Table(counts.values,
                  observation_ids=counts.index.astype(str),
                  sample_ids=counts.columns.astype(str))
    table.add_metadata({str(t): r for t, r in features.to_dict("index").items()}, axis="observation")
    table.add_metadata(samples.to_dict("index"), axis="sample")

    (ws.result / "feature_table.biom").write_text(table.to_json("askslm-build"))

`Workspaces/ABX_new/1_build/build.py` is the worked example (it also merges extra per-subject
sheets). If you see `pivot` "Index contains duplicate entries", or biom "Duplicate observation IDs"
/ "Unable to cast metadata", that is the signal you are hand-rolling — switch to the calls above.

## Querying & context — always work on the CURRENT feature table
Once a feature table exists it is the source of truth and the working object. Answer questions about
samples, features, counts, or metadata by loading the relevant `feature_table.biom` and querying it.
Do NOT read the raw `0_inputs/*.csv` to answer such questions — the build already folded the inputs
into the table, and going back to the raw sources is going backwards. Only touch raw inputs when the
user explicitly asks about them or when (re)building.

Sample metadata and feature (lineage) metadata live INSIDE the table. Query them directly — no
custom code, no re-reading CSVs (run_python's working dir is the workspace root, so a relative path
works):

    from biom import load_table
    table = load_table("1_build/feature_table.biom")     # the current table — see the snapshot above
    samples  = table.metadata_to_dataframe("sample")       # one row per sample
    features = table.metadata_to_dataframe("observation")  # one row per feature (lineage)
    counts   = table.to_dataframe(dense=True)              # features x samples

The pipeline is a CHAIN of feature tables: `1_build` makes the first, then each
`2_transform/<…>` and `3_analyze/<…>` produces or measures another. The workspace snapshot lists
every `feature_table.biom` on disk — that is your map of where things are. Before you compute, be
clear which table the question is about: default to the most downstream table relevant to the
request, and never silently fall back to raw inputs or rebuild. If which table to use is ambiguous,
ASK the user rather than guess.

## How execution works (read before using run_python)
Each `run_python` call runs in a FRESH subprocess. State does NOT persist between calls:
`import` statements and plain variables are gone on the next call. Only recognized domain
objects you create at top level (a `biom.Table`, a `MetadataOverview`, a `DataFrame`) survive,
as *handles* that are pre-loaded by name into later calls. `pandas`, `numpy`, `scipy`, `skbio`,
and `askslm` are pre-imported every call under those names — do not rely on aliases like `pd`.

Use `run_python` only for one-shot inspection (a shape, a dtype, a value). For any multi-step
work — and for everything you want to keep — author a phase script with `write_file` and run it
with `run_script`. The script on disk is the durable artifact; its outputs are files in the
workspace.

Start every `run_python` snippet with a single one-line `#` comment stating its intent (e.g.
`# check taxonomy columns and dtypes`). The UI shows that comment as the step's label, so make it
short and specific.

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
