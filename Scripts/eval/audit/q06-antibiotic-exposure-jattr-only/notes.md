# q06-antibiotic-exposure-jattr-only

**Question:** "samples with antibiotic exposure"

**Why this question:** second jattr-only concept (no native SQL column for antibiotic
exposure exists), chosen for its large real naming-variant neighborhood (300+ real key
variants scouted this session) -- a breadth test distinct from q04's BMI case.

## Run: 2026-10-19_initial

**Translation:**
```json
{"source": "SRA_METADATA", "sql": null,
 "jattr_criteria": ["antibiotic exposure", "antibiotic treatment", "antibiotic administration"],
 "jattr_combinator": "any"}
```
Correctly `sql=None` -- no native column exists, pure jattr concept search, three phrasing
variants unioned.

## Verification against gold (narrow: antibiotic_exposure_sam OR antibiotics_exposure_sam)

- Gold: 2,874. Generated: 75,172. Overlap: 2,874 (100% recall). Extra: 72,298.

## Judgment: PARTIAL (same pattern as q01/q03/q06 family)

Full recall against the narrow gold -- the system's generated cohort is a strict superset.
The 72,298 "extra" rows are the now-familiar, already-settled pattern: real matches via many
other genuine antibiotic-related keys/values my narrow 2-key gold didn't enumerate, consistent
with q01's resolved finding (gold incompleteness, not a system defect) and the confirmed
value-polarity-agnostic design. Not spot-checked further (time-boxed, same reasoning as q03).

## needs_researcher_confirmation: no -- consistent with already-resolved precedent (q01).
