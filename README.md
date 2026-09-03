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
pip install -e .
```

Python 3.12+. The ete3 NCBI taxonomy database (`~/.etetoolkit/taxa.sqlite`) must be built
locally — `ete3` does this itself on first use. Contributing? `pip install -r
Docs/requirements.txt` adds the extras needed to run the test suite and the mirror-build plots.

You need two things before the first `askslm` run:

- **The mirror** — one prebuilt DuckDB that `askslm` opens read-only. On a lab install it's
  already built and handed to you as a single `.duckdb` file — ask your lab for the current
  path. Building it yourself is a separate, one-time ETL that fetches its own raw inputs; see
  [Building the mirror](#building-the-mirror) below if that's your job.
- **A Gemini API key** — for the LLM translation step.

Run `askslm`. The first time, it asks for the database path and the key once and remembers them
in `~/.askslm/config.toml` (or set `ASKSLM_DB` / `ASKSLM_LLM_KEY` — the environment always wins,
so the lab server and CI never see a prompt). Every run after that just opens the prompt shown
above.

## Building the mirror

Only needed if you're building or refreshing the mirror yourself rather than being handed a
finished `.duckdb`. With nowhere to point it, one command does the whole thing — fetches both
raw inputs (Metalog, SRA + STAT) straight from their public sources, then builds:

```bash
sbatch Scripts/build_mirror/build_all.sh --out-dir /path/with/space
```

See [`Docs/building-the-mirror.md`](Docs/building-the-mirror.md) for the full guide, including
using inputs you already have instead of fetching, and resuming a partial build.

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
