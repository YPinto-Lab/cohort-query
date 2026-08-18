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
    Choose profile sources
```

Scope ends at the `.biom` — open it in whatever you already use.

## Status

**Walking skeleton.** The question -> `.biom` path is real end to end: a real LLM (Gemini)
translates the question into SQL per metadata source, the cohort is previewed against the real
mirror, and `run()` materializes a real biom. Still missing: the terminal app and plan
persistence — see the usage snippet below for how to drive it in the meantime.

```python
import os
import askslm

askslm.config(db="askslm_mirror.duckdb", llm="gemini", llm_key=os.environ["GEMINI_KEY"])
plan = askslm.ask("fecal metagenomes from adults with IBD, Western countries")
print(plan)
table, report = plan.run(profile_sources=askslm.Source.METALOG_MOTUS3, out="cohort.biom")
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

The package only ever opens a prebuilt DuckDB read-only. Building it is a separate, one-time ETL:

```bash
python Scripts/build_mirror/build_duckdb.py \
    --metalog-dir ~/Downloads/Metalog \
    --sra-metadata <sra_metadata.csv> \
    --sra-taxonomy <sra_taxonomy.csv> \
    --out askslm_mirror.duckdb
```

## Tests

```bash
python -m pytest Tests -q
```

Runs against a generated fixture mirror and a canned LLM backend — no live database or API key
needed. `Scripts/eval/run_eval.py` is the separate, un-gated measurement against the real mirror
and a real Gemini key; it is not part of this suite.
