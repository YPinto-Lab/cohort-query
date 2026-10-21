# q11-illumina-novaseq-platform

**Question:** "samples sequenced on Illumina NovaSeq"

**Why this question:** sequencing-technology scoping via a real native column -- a clean
exact-match baseline, same shape as q02/q10.

## Run: 2026-10-19_initial

**Translation:** `SELECT biosample FROM sra_metadata WHERE instrument ILIKE '%novaseq%'`

## Verification

- Gold: 9,538,316. Generated: 9,538,316. Overlap: 9,538,316. Missed: 0. Extra: 0.

## Judgment: MATCH

Exact match.
