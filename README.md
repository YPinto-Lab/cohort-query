# Ask-SLM

A read-only Python package that turns a research question into a cross-study metagenomic feature
table. Ask in plain language; an LLM translates it into SQL over a prebuilt SRA × Metalog DuckDB
mirror; review the cohort; materialize one `.biom`.

```
$ askslm
? What cohort do you need? fecal metagenomes from adults with IBD, Western countries
  … 412 biosamples · STAT 380 · MetaPhlAn 228 · mOTUs 222
? What now? (↑/↓)
  › Run it
    Refine the question
    Show the SQL and overlap
    Save plan and quit
    Quit
```

First run asks for the database path and a Gemini API key once, and remembers them in
`~/.askslm/config.toml` (or set `ASKSLM_DB`/`ASKSLM_LLM_KEY` — the environment always wins, so
the lab server and CI never see a prompt). "Save plan and quit" writes the question, its
translation, and the cohort preview as JSON; replay it without touching the LLM:

```bash
askslm run plans/ibd-western.json
```

Scope ends at the `.biom` — open it in whatever you already use.

## Status

**Walking skeleton.** The question -> `.biom` path is real end to end: a real LLM (Gemini)
translates the question into SQL per metadata source, the cohort is previewed against the real
mirror, `run()` materializes a real biom, and the `$ askslm` terminal app and plan persistence
(above) both exist and are hand-verified against the fixture mirror. What's still rough: the
terminal app is not unit-tested (it's thin glue over `ask()`/`run()`, verified by driving it, not
by a test suite), and Translation accuracy against the eval set has not yet been measured — see
below.

The two verbs underneath the terminal app are also usable directly from Python:

```python
import os
import askslm

askslm.config(db="askslm_mirror.duckdb", llm="gemini", llm_key=os.environ["GEMINI_KEY"])
plan = askslm.ask("fecal metagenomes from adults with IBD, Western countries", save="plans/ibd.json")
print(plan)
table, report = plan.run(profile_sources=askslm.Source.METALOG_MOTUS3, out="cohort.biom")

# later, no LLM hop:
replayed = askslm.load_plan("plans/ibd.json")
table, report = replayed.run(profile_sources=askslm.Source.METALOG_MOTUS3, out="cohort.biom")
```

`llm="canned"` plus an injected backend is what the test suite uses instead of live Gemini calls.
Translation accuracy against the eval set in `Scripts/eval/` has not yet been measured — that
script needs the real mirror and a live API key, so it has never been run.

The design is complete and reviewed:

- `Docs/superpowers/specs/2026-06-17-askslm-architecture-hld-lld.html` — HLD/LLD, the *how*
- `Docs/superpowers/specs/2026-06-17-askslm-sra-metalog-cohort-design.html` — the *why*
- `Docs/superpowers/plans/2026-06-18-metalog-duckdb-build.md` — the mirror ETL

## Install

```bash
pip install -r Docs/requirements.txt
pip install -e .
```

Python 3.12+. The ete3 NCBI database (`~/.etetoolkit/taxa.sqlite`) must be built locally.

## The mirror

The package only ever opens a prebuilt DuckDB read-only. Building it is a separate ETL
producing **three** files, in this order:

```bash
bash Scripts/build_mirror/build_all.sh          # all three
bash Scripts/build_mirror/build_all.sh mirror   # just step 3, if the sidecars exist
```

| File | Contents | Build time |
|---|---|---|
| `sra_taxonomy_sorted.duckdb` | `tax_fact` — 13.6B rows sorted by `acc`, 4 of 9 columns | ~2 h |
| `sra_metadata_sorted.duckdb` | `metadata_fact` — 39.1M rows sorted by `biosample`, all columns | ~7 min |
| `askslm_mirror.duckdb` | views over both, plus Metalog tables, embeddings, `stat_coverage` | ~1 h |

Paths come from the environment (`SRA_DB`, `METALOG_DIR`, `MIRROR_DIR`, `PY`); the defaults
are the Pinto lab's. Steps can also be run individually — see each script's `--help`.

Only the mirror is passed to `config(db=...)`. It records the two sidecar paths in
`mirror_config` and the package re-attaches them on connect, so the sidecars must stay where
they were when the mirror was built, or the mirror must be rebuilt.

### Why the big tables live outside the mirror

Sort order **is** the index in a column store. DuckDB keeps min/max statistics per
122,880-row group and can skip a whole group but never part of one, so a cohort query costs
whatever the *groups it touches* cost — not what the rows it wants cost. Sorted by its read
key, a cohort lands in a handful of groups instead of all of them.

Measured on a 3,573-biosample cohort (Slurm jobs 26350723, 26360126):

| | Time |
|---|---|
| unsorted `sra_metadata`, `SELECT *` — touches all 319 row groups | 1,772.7 s |
| sorted, `SELECT *` — touches 20 | 50.0 s |
| sorted, without the unread `jattr` column | **17.8 s** |

Sorting also shrinks the file: clustering same-study rows together took the metadata from
43.5 GB to 31 GB, since their `jattr`/`attributes` blobs compress far better adjacent.

Steps 1 and 2 read only the SRA download and are independent; step 3 needs both, because it
defines its views against them and derives `stat_coverage` from the taxonomy.

## Tests

```bash
python -m pytest Tests -q
```

Runs against a generated fixture mirror and a canned LLM backend — no live database or API key
needed. `Scripts/eval/run_eval.py` is the separate, un-gated measurement against the real mirror
and a real Gemini key; it is not part of this suite.
