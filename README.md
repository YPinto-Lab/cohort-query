# Ask-SLM

A read-only Python package that turns a research question into a cross-study metagenomic feature
table. Ask in plain language; an LLM translates it into SQL over a prebuilt SRA × Metalog DuckDB
mirror; review the cohort; materialize one `.biom`.

**Contents:** [Quick start](#quick-start) · [How it works](#how-it-works) · [Setup](#setup) ·
[Tests](#tests)

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

- **The mirror** — one prebuilt DuckDB that `askslm` opens read-only. It's built once (by the
  lab, from raw STAT and Metalog data) and then just handed to you as a single `.duckdb` file —
  ask your lab for the current path or copy. Building it yourself is a separate, one-time ETL;
  see [Building the mirror](#building-the-mirror) below if that's your job.
- **A Gemini API key** — for the LLM translation step.

Run `askslm`. The first time, it asks for the database path and the key once and remembers them
in `~/.askslm/config.toml` (or set `ASKSLM_DB` / `ASKSLM_LLM_KEY` — the environment always wins,
so the lab server and CI never see a prompt). Every run after that just opens the prompt shown
above.

### Building the mirror

Only relevant if you're the one refreshing the lab's mirror, not a day-to-day user. Given a
directory of raw Metalog downloads and an existing SRA DuckDB:

```bash
python Scripts/build_mirror/build_duckdb.py \
    --metalog-dir ~/Downloads/Metalog \
    --sra-db /path/to/sra.duckdb \
    --out askslm_mirror.duckdb
```

Design docs: `Docs/superpowers/specs/2026-06-17-askslm-architecture-hld-lld.html` (HLD/LLD, the
*how*), `2026-06-17-askslm-sra-metalog-cohort-design.html` (the *why*), and
`Docs/superpowers/plans/2026-06-18-metalog-duckdb-build.md` (the mirror ETL itself).

## Tests

```bash
python -m pytest Tests -q
```

Runs against a generated fixture mirror and a canned LLM backend — no live database or API key
needed. `Scripts/eval/run_eval.py` is the separate, un-gated measurement against the real mirror
and a real Gemini key; it is not part of this suite.
