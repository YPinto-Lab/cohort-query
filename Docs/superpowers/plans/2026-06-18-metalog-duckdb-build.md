# Plan — build the shared SRA × Metalog DuckDB mirror

**Date:** 2026-06-18 · **Status:** ready to implement · **Branch when coding:** `feature-metalog-duckdb-build`

## Context
The `askslm` package is **read-only** over one shared DuckDB. This plan covers the *separate* ETL that
**builds** that DuckDB from the Metalog downloads (`~/Downloads/Metalog`) plus the existing SRA parquet.
Verified against the real files on 2026-06-18 (see [[project_metalog_sra_join]]): the join works —
SRA IBDProjects 3,558 biosamples ∩ Metalog human = **1,294** samples.

## Recommended interaction: a persistent DuckDB mirror
Three options; recommend **A**.

| | Approach | Verdict |
|---|---|---|
| **A** | **Build a persistent `askslm_mirror.duckdb` once; package opens it read-only.** | **Recommended.** Matches the design (one shared DB) and the SRA side (parquet→duckdb). Gzipped TSVs are parsed once into columnar storage; LLM-generated SQL then runs fast joins. |
| B | DuckDB over raw files via `read_csv` at query time (no persisted DB). | Re-parses multi-GB gzip on every query; slow. Fine only for ad-hoc exploration. |
| C | Pure Python/pandas load per query. | Slowest, memory-heavy; rejected. |

The package never builds or writes the mirror — this script does, run once (or on refresh) by the lab.

## Source schemas (the DuckDB tables)
Profiles stay **long** (pivot to features×samples happens in the package at materialization, not here).
Every Metalog table gets an `environment` column (human | animal | ocean | environmental) from the filename.

### METADATA sources
- **`metalog_metadata`** (wide, UNION of 4 `*_extended_wide` files; 108 cols). Keys/bridge + harmonized phenotype:
  - `sample_alias` TEXT — joins to the profile tables (Metalog-internal id)
  - `spire_sample_name` TEXT — **the bridge**: == `sra_metadata.biosample` (mostly `SAMN`/`SAME`/`SAMD`; some `SRS`/`ERR`)
  - `study_code`, `geographic_location`, `collection_date`, `sex`, `age_years` (num), `age_range`, `age_category`,
    `bmi`/`weight_kg`/`height_cm` (num), `diet`, `smoker`, `subject_disease_status`, `subject_id`, `intervention`,
    `medication`, `timepoint`, `tax_id` (host), `pmid`/`doi`, … (+ `environment`)
- **`sra_metadata`** — per `SRAMetadataSchema` (`acc`, `biosample`, `sample_acc`, `bioproject`, `assay_type`,
  `geo_loc_*`, `organism`, `jattr`, … 36 fields). Key to biosample via `biosample`.

### PROFILE sources (long) — each tagged with its `ProfilerFamily`
| Table | Family | Unit | Columns |
|---|---|---|---|
| `metalog_metaphlan4_species` | METAPHLAN | relative | `sample_alias`, `species` (`s__…`), `rel_abund`, `environment` |
| `metalog_metaphlan4` (all levels) | METAPHLAN | relative | `sample_alias`, `clade_name` (`k__…t__SGB…`), `rel_abund`, `environment` |
| `metalog_motus3` | MOTUS | relative | `sample_alias`, `species`, `rel_abund`, `insert_count`, `environment` |
| `metalog_spire_motus` | MOTUS | relative | `sample_alias`, `species`, `rel_abund`, `insert_count`, `environment` |
| `sra_taxonomy` (STAT) | STAT | counts | per `SRATaxonomySchema`: `acc`, `tax_id`, `rank`, `name`, `total_count`, `self_count`, `ilevel/ileft/iright`, `bioproject` |
| `metalog_mlp` *(not v1)* | — | — | `sample_alias`, `microbial_load_prediction` (human only) |

A biom is built from **one family** (`STAT` | `METAPHLAN` | `MOTUS`); STAT (read-count) and MetaPhlAn (coverage) are
different estimators and never pool (see HLD §B.11). So the build needs no STAT↔MetaPhlAn crosswalk in v1.

> Caveat: MetaPhlAn4 all-levels uses **SGB** clade ids (`t__SGB1871`) that don't all map to NCBI tax_id; the
> `s__` species file is the NCBI-alignable one. Within the MetaPhlAn family this is irrelevant (clades are native ids).

### Reference table (static) — `metaphlan_clades` *(roadmap, not v1)*
- **`metaphlan_clades`** — `~/Downloads/metaphlan4_clades.tsv` (95,710 rows): `clade_name`, `lineage`,
  `NCBI_taxids` (pipe-aligned). **Not needed for v1 builds** (within a family feature ids are native). Keep it for the
  roadmap **STAT→MetaPhlAn unification** (convert STAT counts to coverage + `tax_id → clade` relabel) and for aligning
  taxa across a separately-built STAT biom and MetaPhlAn biom. Load it read-only if/when that work starts.

### Join keys (resolve everything to biosample)
```
metalog profile.sample_alias  ⋈  metalog_metadata.sample_alias
metalog_metadata.spire_sample_name  ==  sra_metadata.biosample      # canonical key (SAMN/SAME/SAMD)
sra_taxonomy.acc  ⋈  sra_metadata.acc → sra_metadata.biosample
```
Index `sample_alias`, `spire_sample_name`, `biosample`, `acc`.

### Materialize `biosample` as the single primary key (do the two-hop ONCE, at build)
The package must see **one key across all sources**, not re-run the two-hop per query. So after loading, **stamp a
`biosample` column onto every Metalog table** (the metadata and all profile tables) and index it. Run-time joins are
then single-key; the package needs no `AccessionNormalizer`.

- `metalog_metadata.biosample` = its `spire_sample_name` **when that value is an NCBI BioSample** (`SAMN`/`SAME`/`SAMD`
  — confirmed by joining to `sra_metadata.biosample`); else `NULL`.
- Each Metalog **profile** table gets `biosample` by joining `sample_alias → metalog_metadata.sample_alias`, e.g.
  ```sql
  ALTER TABLE metalog_metaphlan4_species ADD COLUMN biosample TEXT;
  UPDATE metalog_metaphlan4_species p
  SET biosample = m.biosample
  FROM metalog_metadata m
  WHERE p.sample_alias = m.sample_alias;
  CREATE INDEX ON metalog_metaphlan4_species (biosample);
  ```
- **Null tail (kept, not dropped):** a Metalog sample whose `spire_sample_name` is not a BioSample (some `SRS`/`ERR`/
  study-internal) gets `biosample = NULL`; it stays addressable by `sample_alias` (Metalog-only — nothing to join to).
- **Multiplicity rule:** if one `sample_alias` resolves to several biosamples (external accession ↔ sample isn't
  always 1:1), pick the BioSample-prefixed value deterministically and record the collisions in the build report —
  resolve the ambiguity **here**, once, visibly, never at query time.

## The build script — UNION the 4 environments
`Scripts/build_mirror/build_duckdb.py` (one class, small methods). DuckDB's globbed `read_csv` with
`filename=true` does the UNION and the `environment` column in one statement, e.g. per profiler:

```sql
CREATE TABLE metalog_metaphlan4_species AS
SELECT * EXCLUDE (filename),
       regexp_extract(filename, '([a-z]+)_metaphlan4_species', 1) AS environment
FROM read_csv('…/Taxonomic Profiles/*/*_metaphlan4_species_*.tsv.gz',
              delim='\t', header=true, filename=true, compression='gzip');
```
Steps: (1) one `CREATE TABLE … AS read_csv(glob)` per profiler + for `*_extended_wide` → `metalog_metadata`;
(2) load SRA parquet → `sra_metadata`, `sra_taxonomy`; (3) **stamp `biosample` onto every Metalog table** (the
two-hop, done once — see above); (4) create indexes on the join keys incl. `biosample` everywhere; (5) write
`askslm_mirror.duckdb`.

## Verification
- Row/sample counts per table; distinct `sample_alias` per profiler vs metadata.
- **Smoke test the join** reproduces the known number:
  `SELECT count(*) FROM (SELECT DISTINCT spire_sample_name FROM metalog_metadata) m
   JOIN sra_metadata s ON m.spire_sample_name = s.biosample;`  → matches the 1,294 IBDProjects overlap.
- `spire_sample_name` prefix histogram is mostly `SAMN`/`SAME`/`SAMD`.
- After stamping: every profile table has `biosample`; count non-null vs null (the fallback tail) and assert no
  `sample_alias` maps to >1 biosample after the multiplicity rule.

## Out of scope
The read-only package itself, the LLM/translator, and refresh automation. This script just assembles the mirror.
