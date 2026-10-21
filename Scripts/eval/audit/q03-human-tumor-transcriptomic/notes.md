# q03-human-tumor-transcriptomic

**Question:** "human tumor samples from transcriptomic sequencing"

**Why this question:** fresh question authored to cover the "non-metagenome" benchmark gap
(per project memory: STAT profiles every SRA run, so human-tumour cohorts are valid science
and must never be filtered by a metagenome-only bias).

## Run: 2026-10-19_initial

**Plan:** `/private/pinto-lab/plans/20261019_123049_human-tumor-samples-from-transcriptomic/plan.json`

**Translation:**
```json
{
  "sql": "SELECT biosample FROM sra_metadata WHERE organism = 'Homo sapiens' AND (assay_type = 'RNA-Seq' OR librarysource IN ('TRANSCRIPTOMIC', 'METATRANSCRIPTOMIC'))",
  "jattr_criteria": ["tumor sample", "cancer sample", "neoplasm"],
  "jattr_combinator": "any",
  "sql_jattr_combinator": "intersect"
}
```

Correctly recognized as non-metagenomic (no librarysource=METAGENOMIC bias at all), correctly
intersected native RNA-Seq/transcriptomic scoping with tumor-concept jattr criteria.

## Verification against gold (distinct biosamples; see gold.sql)

- Gold: 33,405 (Homo sapiens / TRANSCRIPTOMIC / `is_tumor_sam[0]='Yes'`)
- Generated: 68,342
- Overlap: 5,212. Missed: 28,193. Extra: 63,130.

## Root cause: `is_tumor_sam` itself was never matched by any of the 3 jattr concepts

Checked `discovered.jattr_matches` directly: none of "tumor sample"/"cancer sample"/"neoplasm"
matched `is_tumor_sam` (confirmed: `'is_tumor_sam' in matched_on` is False for all three). The
system instead matched ~211 OTHER real tumor/cancer-related keys and values
(`tumor_sample_sam`, `cancer_sam`, `carcinoma_sam`, `neoplasia_type_sam`, free-text values like
`"Tumor"`/`"Neoplasm"`, etc.) -- a genuinely different, overlapping-but-distinct population from
my single-key gold definition. Same class of finding as q01: a narrow single-key gold
under-enumerates the real population a content-based search legitimately reaches via other
synonyms. Not independently spot-checked sample-by-sample here (time-boxed per Task 10's
breadth-over-depth goal) -- flagging as PARTIAL rather than fully re-deriving a value-aware
gold v2 the way q01 did.

## Judgment: PARTIAL

Low overlap against a narrow single-key gold, consistent with the already-understood pattern
(gold incompleteness for free-text/content-matched concepts) rather than a confirmed new defect.
Worth a deeper pass later if this concept area gets revisited.

## needs_researcher_confirmation: yes

Is 15.6% overlap (5212/33405) against this narrow gold acceptable given the q01 precedent
(gold incompleteness, not necessarily a system defect), or does this concept area warrant the
same value-aware re-scoring q01 got?
