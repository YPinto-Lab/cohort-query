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

**Pre-implementation.** The pre-pivot workspace/agent/web codebase has been removed and the new
package is not built yet. What is in `src/askslm/` today is the material the new design reuses:
`sra_schema.py` (SRA column contracts) and `taxonomy.lineage_table` (ete3 tax_id → lineage).

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

Currently empty — the suite went with the deleted code. New tests land with the walking skeleton.
