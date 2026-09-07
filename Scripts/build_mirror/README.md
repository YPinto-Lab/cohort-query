# Building the mirror

`askslm` reads one prebuilt DuckDB. This directory builds it, in **five steps** that
produce **three files**. Run them with one command:

```bash
bash build_all.sh \
    --sra-db      ~/downloads/sra_processed.duckdb \
    --metalog-dir ~/downloads/Metalog \
    --out-dir     /path/with/space
```

`build_all.sh --help` lists the rest. Nothing else here is meant to be run by hand.

## The steps

| # | Script | Produces | Time |
|---|---|---|---|
| 1 | `steps/step1_sort_taxonomy.py` | `sra_taxonomy_sorted.duckdb` — `tax_fact`, sorted by `acc`, 4 of 9 columns | ~2 h |
| 2 | `steps/step2_sort_metadata.py` | `sra_metadata_sorted.duckdb` — `metadata_fact`, sorted by `biosample` | ~10 min |
| 3 | `steps/step3_assemble_mirror.py` | `askslm_mirror.duckdb` — views over 1 and 2, Metalog tables, `stat_coverage` | ~15 min |
| 4 | `steps/step5_catalog_schema.py` | `schema_catalog` — columns and real value vocabularies, for the LLM prompt | ~1 min |
| 5 | `steps/step6_embed_concepts.py` | `column_value_embeddings` — local SapBERT vectors over native-column values | ~10 min |

Steps 1 and 2 read only the SRA download and are independent. Step 3 needs both, since
it defines its views against them and derives `stat_coverage` from the taxonomy. Steps
4–5 write **into** the mirror from step 3, in that order — step 5 reads step 4's output.

**Steps 4–5 are not optional.** Without them the LLM has no column vocabulary and no
concept search over native-column values.

**Transitional state (2026-09-07):** `attribute_keys` and `attribute_key_embeddings` —
formerly built by a `step4_index_attributes.py` this pipeline no longer runs — are being
replaced by a build-time embedding index over `jattr` (see the Obsidian design note,
"Inverted Index Plan"). Until that replacement ships, `verify_mirror()`'s
`REQUIRED_TABLES` check still expects both tables, so **`build_all.sh`'s own final
verification step will fail** on a fresh build — this is intentional (a loud failure
beats `ask()` silently breaking on a missing table), not a bug. Don't "fix" it by
resurrecting `step4_index_attributes.py`; either build against an existing mirror that
already has these tables, or wait for the replacement.

## Resuming

| Flag | Runs |
|---|---|
| `--stage sidecars` | 1–2 |
| `--stage mirror` | 3–6 |
| `--stage enrich` | 4–6 — after re-tuning the catalog, without repeating the 2 h sort |

Every step writes to a `<target>.building` file and renames it over the target only
after its own checks pass, so a failed or repeated run never damages an existing
artifact.

## Layout

```
build_all.sh     the only entry point
steps/           the six build steps, in execution order
tools/           read-only diagnostics -- inspect_mirror.py, probe_attributes.py
tests/           tests for the steps (not collected by the root pytest run)
```

## Why the big tables live outside the mirror

Sort order **is** the index in a column store. DuckDB keeps min/max statistics per
122,880-row group and can skip a whole group but never part of one, so a cohort query
costs whatever the *groups it touches* cost — not what the rows it wants cost. Sorted by
its read key, a cohort lands in a handful of groups instead of all of them.

Measured on a 3,573-biosample cohort, cold, on a dedicated node:

| | Time |
|---|---|
| unsorted `sra_metadata`, `SELECT *` — touches all 319 row groups | 1,772.7 s |
| sorted, `SELECT *` — touches 20 | 298.8 s |
| sorted, without the unread `jattr` column | 182.1 s |

Roughly **10× cold**; the same reads are ~16 s once the pages are cached. Sorting also
shrinks the data — clustering same-study rows put their `jattr`/`attributes` blobs next
to each other, taking the metadata from 43.5 GB to 31 GB.
