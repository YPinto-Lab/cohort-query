# q14-infant-samples-young-age

**Question:** "samples from infants"

**Why this question:** age concept at the opposite extreme from q08 ("over 65 years old") --
tests whether the jattr concept search handles a young-age concept with the same (partial)
breadth it showed for the old-age one, without a clean numeric column to fall back on.

## Run: 2026-10-19_initial

**Translation:**
```json
[
  {"source": "SRA_METADATA", "sql": null, "jattr_criteria": ["infant"]},
  {"source": "METALOG_METADATA", "sql": "SELECT biosample, sample_alias FROM metalog_metadata WHERE age_category IN ('baby', 'baby, child')"}
]
```
Correctly `sql=None` for SRA (no clean native infant-age column); Metalog used its own native
`age_category` column.

## Verification against narrow gold (infant_age_sam / host_age_infant_sam / fed_as_infant_sam)

- Gold: 32,039. Generated: 71,038. Overlap: 1,585. Missed: 30,454. Extra: 69,453.

Low overlap looks dramatic, but checked `discovered.jattr_matches` directly: the "infant"
concept matched 57 real keys/values, dominated by literal VALUES (`"infant"`, `"Infant"`,
`"infants"`, `"human infant"`) rather than my hand-picked 3-key list -- not shown surfacing
`infant_age_sam`/`host_age_infant_sam`/`fed_as_infant_sam` in the top 15 inspected. Same
already-established class of finding as q01/q03: a narrow single/few-key gold under-enumerates
a population reached mostly through VALUE content, not the specific keys I guessed. Not
independently re-derived with a broader gold (time-boxed, same reasoning as q03).

## Judgment: PARTIAL

Consistent with the q01/q03 precedent (gold incompleteness for value-matched concepts), not
confirmed as a system defect.
