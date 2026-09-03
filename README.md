# Ask-SLM

A read-only Python package that turns a research question into a cross-study metagenomic feature
table. Ask in plain language; an LLM translates it into SQL over a prebuilt SRA × Metalog DuckDB
mirror; review the cohort; materialize one `.biom`.

**Contents:** [Quick start](#quick-start) · [How it works](#how-it-works) · [Setup](#setup) ·
[Building the mirror](#building-the-mirror) · [Tests](#tests)

## Quick start

Orange is what you type; everything else is `askslm` talking back — the question, its
translation, the cohort preview, and a menu to run it, refine it, or save the plan for later.

![`askslm` interactive session: asking a cohort question and previewing the result](Docs/img/askslm-session.png)

"Run it" walks you through picking a feature space and sources, then submits the build. Scope
ends at the `.biom` — open it in whatever you already use.

## How it works

```
question (plain English)
        │  LLM translation, per metadata source
        ▼
   SQL over the SRA × Metalog DuckDB mirror  ──►  cohort preview (counts, overlap)
        │  confirm
        ▼
   run(profile_sources=...)  ──►  one feature_table.biom
                                   (counts × samples, + sample & feature metadata)
```

One biom holds one profiler family — STAT, MetaPhlAn, or mOTUs — since pooling across
different abundance estimators isn't valid; bioms ship each source's native taxonomic
granularity, no rank knob.

## Setup

```bash
pip install -r Docs/requirements.txt
pip install -e .
```

Python 3.12+. The ete3 NCBI taxonomy database (`~/.etetoolkit/taxa.sqlite`) must be built
locally — `ete3` does this itself on first use.

You need two things before the first `askslm` run:

- **The mirror** — one prebuilt DuckDB that `askslm` opens read-only. On a lab install it's
  already built and handed to you as a single `.duckdb` file — ask your lab for the current
  path. Building it yourself from raw downloads is a separate, one-time ETL; see
  [Building the mirror](#building-the-mirror) below if that's your job.
- **A Gemini API key** — for the LLM translation step.

Run `askslm`. The first time, it asks for the database path and the key once and remembers them
in `~/.askslm/config.toml` (or set `ASKSLM_DB` / `ASKSLM_LLM_KEY` — the environment always wins,
so the lab server and CI never see a prompt). Every run after that just opens the prompt shown
above.

Design docs: `Docs/superpowers/specs/2026-06-17-askslm-architecture-hld-lld.html` (HLD/LLD, the
*how*) and `Docs/superpowers/specs/2026-06-17-askslm-sra-metalog-cohort-design.html` (the *why*).

## Building the mirror

`askslm` reads one prebuilt DuckDB. Building it is a separate ETL you run once per SRA
download, and it produces **three files**:

```bash
bash Scripts/build_mirror/build_all.sh \
    --sra-db      ~/downloads/sra_processed.duckdb \
    --metalog-dir ~/downloads/Metalog \
    --out-dir     /path/with/space
```

That is the whole procedure. It runs six steps in order and refuses to start if an
input is missing, so a typo costs a second rather than two hours.

### What you need first

| Input | What it is |
|---|---|
| `--sra-db` | the SRA DuckDB download, holding `metadata_raw` and `tax_raw` |
| `--metalog-dir` | the Metalog download; must contain `Metadata/` and `Taxonomic Profiles/` |
| `--out-dir` | somewhere with roughly **0.6×** the size of your SRA download free |

### What you get

| File | Contents | Time |
|---|---|---|
| `sra_taxonomy_sorted.duckdb` | `tax_fact` — taxonomy sorted by `acc`, 4 of 9 columns | ~2 h |
| `sra_metadata_sorted.duckdb` | `metadata_fact` — metadata sorted by `biosample`, all columns | ~10 min |
| `askslm_mirror.duckdb` | views over both + Metalog tables + attribute index + catalog + embeddings | ~35 min |

Point the package at the **mirror** only — it records the other two and re-attaches them
on connect:

```python
askslm.config(db="/path/with/space/askslm_mirror.duckdb")
```

All three must stay where you built them. Move one and rebuild the mirror, or edit its
`mirror_config` row.

### The six steps

1. **sorted taxonomy** — `tax_raw` sorted by `acc`, narrowed to the four columns the reader uses
2. **sorted metadata** — `metadata_raw` sorted by `biosample`, every column kept
3. **mirror** — views over 1 and 2, plus the Metalog profile tables and `stat_coverage`
4. **attribute index** — every `jattr` key, so a question naming a phenotype can find it
5. **schema catalog** — columns and their real value vocabularies, for the LLM prompt
6. **concept embeddings** — local SapBERT vectors, so a question finds a field that means the same thing

Steps 4–6 write into the mirror from step 3 and are **not optional**: without them the
LLM has no column vocabulary and discovery fails on any question that names a phenotype.
The script verifies all twelve required tables exist before reporting success.

Resume a partial build with `--stage sidecars` (1–2), `--stage mirror` (3–6) or
`--stage enrich` (4–6). Every step builds into a `.building` file and renames it over the
target only after its own checks pass, so a failed or re-run build never damages an
existing artifact. `--help` lists the remaining options.

### Why the big tables live outside the mirror

Sort order **is** the index in a column store. DuckDB keeps min/max statistics per
122,880-row group and can skip a whole group but never part of one, so a cohort query
costs whatever the *groups it touches* cost — not what the rows it wants cost. Sorted by
its read key, a cohort lands in a handful of groups instead of all of them.

Measured on a 3,573-biosample cohort (Slurm jobs 26350723, 26360126):

| | Time |
|---|---|
| unsorted `sra_metadata`, `SELECT *` — touches all 319 row groups | 1,772.7 s |
| sorted, `SELECT *` — touches 20 | 50.0 s |
| sorted, without the unread `jattr` column | **17.8 s** |

Sorting also shrinks the data: clustering same-study rows together took the metadata from
43.5 GB to 31 GB, since their `jattr`/`attributes` blobs compress far better adjacent.

## Tests

```bash
python -m pytest Tests -q
```

Those run against a generated fixture mirror and a canned LLM — no live database, no
API key. The one path they cannot cover is the real one, so there is a smoke test for
it, run deliberately rather than in CI because it costs an LLM call and reads the whole
mirror:

```bash
python Scripts/smoke/full_cohort.py --out-dir /some/scratch
```

It asks a real question, materializes a real `.biom`, times both halves, and fails if
nothing was written. `--expect-samples N` turns it into a regression check against a
known cohort.

`Scripts/eval/run_eval.py` is the separate, un-gated measurement of Translation accuracy against
the real mirror and a real Gemini key; it is not part of this suite either.
