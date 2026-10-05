# Building the mirror

Only relevant if you're the one building or refreshing the mirror — most users are handed a
finished `.duckdb` file and never run this. See the main [README](../README.md) for day-to-day
use.

`cohortquery` reads one prebuilt DuckDB. Building it is a separate ETL, and it produces **three
files**. With nothing but somewhere to put them, this is the whole thing:

```bash
sbatch Scripts/build_mirror/build_all.sh --out-dir /path/with/space
```

One command. It fetches both raw inputs straight from their public sources (see below),
runs the six build steps in order, and reports the finished mirror's path when it's done —
point `cohortquery` at that path, add a Gemini API key, and you're running. The fetch alone is
hours (it's NCBI's full SRA metadata + STAT results); submit it as a Slurm job rather than
running it interactively.

Already have a copy of one or both inputs? Pass them and that fetch is skipped:

```bash
bash Scripts/build_mirror/build_all.sh \
    --sra-db      ~/downloads/sra_processed.duckdb \
    --metalog-dir ~/downloads/Metalog \
    --out-dir     /path/with/space
```

It refuses to start if a *given* input is missing, so a typo costs a second rather than
two hours.

## Where the raw inputs come from

Neither is something anyone has to hand you a copy of — both come straight from their public
source, and `build_all.sh` fetches them itself when you don't pass `--sra-db`/`--metalog-dir`.
The fetchers are also runnable standalone (e.g. to pre-fetch into a shared location, or refresh
just one input):

**Metalog** — direct, no-login downloads at
[metalog.embl.de/downloads](https://metalog.embl.de/downloads):

```bash
Scripts/build_mirror/fetch_metalog.sh ~/downloads/Metalog
```

**SRA + STAT** — NCBI publishes SRA metadata and STAT taxonomic classifications as public
parquet on AWS Open Data (`s3://sra-pub-metadata-us-east-1/...`), readable with the `aws` CLI's
`--no-sign-request` — no AWS account needed:

```bash
sbatch Scripts/build_mirror/fetch_sra_raw.sh /path/with/space
```

## What you need first

| Input | What it is |
|---|---|
| `--sra-db` (optional) | an SRA DuckDB you already have, holding `metadata_raw` and `tax_raw` — omit to fetch one |
| `--metalog-dir` (optional) | a Metalog download you already have — omit to fetch one |
| `--out-dir` | somewhere with roughly **0.6×** the size of the SRA data free, plus room for the raw fetch if you're not supplying `--sra-db` yourself |

## What you get

| File | Contents | Time |
|---|---|---|
| `sra_taxonomy_sorted.duckdb` | `tax_fact` — taxonomy sorted by `acc`, 4 of 9 columns | ~2 h |
| `sra_metadata_sorted.duckdb` | `metadata_fact` — metadata sorted by `biosample`, all columns | ~10 min |
| `cohortquery_mirror.duckdb` | views over both + Metalog tables + attribute index + catalog + embeddings | ~35 min |

Point the package at the **mirror** only — it records the other two and re-attaches them
on connect:

```python
cohortquery.config(db="/path/with/space/cohortquery_mirror.duckdb")
```

All three must stay where you built them. Move one and rebuild the mirror, or edit its
`mirror_config` row.

## The six steps

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

## Why the big tables live outside the mirror

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
