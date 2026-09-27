---
name: workspace-phase-organization
description: Use when creating, populating, or reorganizing a folder under Workspaces/ in Ask-SLM (a study's cohort/biom outputs) — covers 0_inputs/1_build/2_transform/3_analyze layout, naming bioms so the filename alone carries the context, and which phase is allowed to write what.
---

# Workspace phase organization

## Overview
Every `Workspaces/<study>/` folder is one study, organized into numbered phases that hand
data to each other as **files on disk** — nothing held in memory between phases. Full spec
(source of truth): `Docs/superpowers/specs/2026-06-03-workspace-phase-organization-design.html`
(LOCKED 2026-06-03).

Related studies can additionally sit inside an optional **group folder** directly under
`Workspaces/` — see "Grouping related studies" below. Spec:
`Docs/superpowers/specs/2026-09-27-workspaces-grouping-layer-design.html` (LOCKED 2026-09-27).

## The spine
```
0_inputs/ -> 1_build/<study>.biom -> 2_transform/<exploration>/<study>_<what>.biom -> 3_analyze/<exploration>/<analysis>/
```

## Folder tree
No `result/` subfolders anywhere — every phase's outputs sit directly alongside its own script.

```
Workspaces/<study>/
├── 0_inputs/              # raw pulls, exactly as received — nothing derived
├── 1_build/
│   ├── build.py           # reads 0_inputs/, runs ONCE
│   ├── build.md           # frontmatter: kind/intent/inputs/outputs + 2 lines prose
│   └── abx.biom       # THE one shared feature table — named for the study
├── 2_transform/
│   ├── shared.py          # (workspace, transform) helpers
│   └── <exploration>/                    # free-form, intent-named
│       ├── explore.py
│       ├── explore.md
│       └── abx_relative_abundance.biom   # see "Naming a biom"
└── 3_analyze/
    ├── shared.py           # (workspace, analyze) helpers
    └── <exploration>/<analysis>/
        ├── analysis.py
        ├── analysis.md
        └── *.csv, *.png
```

## Rules
- **Idempotency:** a phase writes only inside its own folder. Re-running overwrites that
  phase's outputs and never touches upstream. `1_build/` is the one run-once root everything
  depends on.
- **0_inputs/ is untouched raw material** — a one-time dump (parquet/biom/xlsx) if the source
  is a remote DB/cluster the package can't query live, or an Accessor pull otherwise. Never put
  a script's *output* here.
- **Name every biom so it stands alone — see "Naming a biom" below.** The build output lives in
  `1_build/`, produced by `1_build/build.py` reading from `../0_inputs/`; a transform's output
  lives in its own `2_transform/<exploration>/`. Those *locations* are fixed; the filenames are
  a judgement call.
- **Every build/exploration/analysis folder gets a `.md`** with YAML frontmatter
  (`kind`, `intent`, `inputs`, `outputs`) + 2 lines of prose — see an existing `build.md` for the
  exact shape.
- **Promotion rule:** write a step inline in the first script; lift to that phase's `shared.py`
  only when a second script in the same phase needs it.
- **Two libraries:** general operations (lineage, biom/skbio wrappers) belong in the `askslm`
  package; study-specific glue belongs in the phase's `shared.py`.
- Serialize biom via `table.to_json("askslm-<study>-build")`, never `to_hdf5` — HDF5 can't
  round-trip nested lineage feature metadata (a real `AttributeError` you'll otherwise hit).

## Naming a biom
**The viewer test.** In biom-viewer the path is gone — the user sees the bare filename and
nothing else. So the name has to carry the whole context on its own: *which study, and what
this table is.* A name that only makes sense next to its folder has failed.

This is judgement, not a formula. Think about what the file actually is and write that. A
shape that usually works:

```
<study>_<what-it-is>.biom
abx.biom                              the study's built cohort
abx_relative_abundance.biom           counts -> RA
abx_bacteria_no_controls.biom         filtered
PRJNA400072_phanta_prophage_host_ratio.biom
```

Guidance, not rules:
- **Lead with the study** — it's what tells two otherwise-identical tables apart in a list.
- **Say what's different about it**, not how it was made. `_relative_abundance` over `_transformed`.
- Mirroring the exploration folder is often the right answer; it isn't automatically the right
  answer. If the folder is `v2` or `attempt_final`, the file still needs a real name.
- Short enough to read at a glance; a name nobody can scan is as bad as one nobody can decode.
- Generic names (`feature_table`, `cohort`, `output`, `table`, `final`) are never good enough on
  their own — they describe every biom in the repo.

## Common mistakes (seen in practice)
- Dumping the cohort biom straight into `Workspaces/<study>/` with no phase folders at all.
- Naming a biom for its *role in the pipeline* (`feature_table.biom`, `cohort.biom`) instead of
  its content — a dozen studies then produce a dozen files with the same name.
- Leaning on the folder for meaning: `relative_abundance/output.biom` reads as `output.biom`
  everywhere outside that folder.
- Putting the *merged/built* biom in `0_inputs/` and the *raw* pull in `1_build/` — it's the
  other way around: raw pull → `0_inputs/`, build script's result → `1_build/<study>.biom`.

## Grouping related studies
When two or more study folders are clearly siblings — same source dataset explored with
different tooling, or the same research question run across different cohorts — nest them
under one group folder directly beneath `Workspaces/`:

```
Workspaces/
├── abx/                          # group
│   ├── abx/                      # base study, unchanged internally
│   ├── abx-DAO-read-abu/
│   └── abx-EAT-read-abu/
├── PRJNA400072/                  # group
│   ├── PRJNA400072/
│   ├── PRJNA400072_assembled_viruses/
│   └── PRJNA400072_phanta/
└── IBD_calprotectin/             # standalone — no siblings, stays flat
```

- **Judgement call, no formula.** Don't force a group onto a folder just because a name looks
  prefixable.
- **Members keep their full original name** inside the group — never truncate to just the
  distinguishing suffix. A member folder must still read standalone if moved out of its group.
- **Name collision** (the group's natural name is also an existing study's name, e.g. `abx`):
  that base study moves down unchanged into `<group>/<group>/` as just another member.
- **One layer only** — a group holds studies, never another group.
- `Workspaces/Archive/` already used this pattern informally before it was formalized here.

## Reference examples in this repo
`Workspaces/PRJNA1265906/` and `Workspaces/PRJNA400072/` both follow this layout end to end —
read their `1_build/build.py` + `build.md` as a template before writing a new one.
