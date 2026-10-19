# q10-united-states-geography

**Question:** "samples collected in the United States"

**Why this question:** geography coverage, per CLAUDE.md's own motivating example question
("fecal metagenomes from adults with IBD, Western countries").

## Run: 2026-10-19_initial

**Translation:**
```json
{"source": "SRA_METADATA",
 "sql": "SELECT biosample FROM sra_metadata WHERE geo_loc_name_country_calc = 'USA'",
 "jattr_criteria": []}
```
Simpler than expected: the translator used a real native SQL column
(`geo_loc_name_country_calc`), not a jattr concept at all.

## Verification against gold

- Gold: 7,776,499. Generated: 7,776,499. Overlap: 7,776,499. Missed: 0. Extra: 0.

## Judgment: MATCH

Exact match. Large count is expected and correct -- the US historically dominates SRA
submission volume across all library/assay types (not metagenome-specific; this question
didn't scope to metagenomic samples).
