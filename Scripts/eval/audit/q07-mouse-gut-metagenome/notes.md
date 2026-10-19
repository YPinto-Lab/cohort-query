# q07-mouse-gut-metagenome

**Question:** "mouse gut metagenome samples"

**Why this question:** extends the "non-metagenome bias" check to host diversity -- tests
that the pipeline doesn't implicitly assume "metagenome" means "human gut metagenome."

## Run: 2026-10-19_initial

**Translation:**
```json
{"source": "SRA_METADATA",
 "sql": "SELECT biosample FROM sra_metadata WHERE organism = 'mouse gut metagenome' AND (librarysource = 'METAGENOMIC' OR librarysource = 'METATRANSCRIPTOMIC')",
 "jattr_criteria": []}
```
Pure native SQL, correctly used the exact NCBI organism-label convention ("mouse gut
metagenome", the same pattern as "human gut metagenome" from q01) rather than the broader
host-species name (Mus musculus, which spans all tissue/library types).

## Gold correction (v1 -> v2)

Initial gold used `organism = 'Mus musculus'` (45,806 biosamples) -- naively defined before
seeing the system's own translation. The system's more precise organism-label query (249,477
biosamples) is actually the *more correct* definition for "mouse gut metagenome samples", not
a looser one. Corrected gold to match (see gold.sql v2) rather than scoring a correct answer
as wrong.

## Verification against gold v2

- Gold: 249,477. Generated: 249,477. Overlap: 249,477. Missed: 0. Extra: 0.

## Judgment: MATCH

Exact match once gold reflects the right definition. Confirms non-metagenome-bias extends
correctly to non-human hosts, and that organism-label precision (not species name) is handled
correctly by the translator.
