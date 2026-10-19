# q08-age-over-65-numeric-threshold

**Question:** "samples from patients over 65 years old"

**Why this question:** capability-boundary test -- does the pipeline have any way to
evaluate a numeric threshold against a jattr value?

## Run: 2026-10-19_initial

**Translation:**
```json
[
  {"source": "SRA_METADATA", "sql": null, "jattr_criteria": ["age over 65 years old"]},
  {"source": "METALOG_METADATA", "sql": "SELECT biosample, sample_alias FROM metalog_metadata WHERE age_years > 65.0"}
]
```

**Metalog correctly used a real native numeric column** (`age_years > 65.0`) -- clean,
correct, exact threshold evaluation, because Metalog's harmonized schema has an actual numeric
age column.

**SRA has no native age column**, so it fell back to a single jattr_criteria phrase, "age over
65 years old", resolved via embedding-distance concept search (51 biosample matches). Inspected
the actual matched values directly: a MIX of correct (`>65`, `65 years old`, `65-year-old`) and
clearly wrong values (`age_above_45_sam` -- a 45 threshold, not 65; `60-65 years old` and
`60 - 65 years` -- ranges spanning BELOW 65; `over 60`, `older_60` -- a 60 threshold; `Age 64`
-- literally under 65). This directly confirms the predicted capability gap: the concept search
does pure text/embedding proximity to the literal digits "65", not actual numeric evaluation --
it cannot distinguish ">65" from "a nearby but different numeric threshold" or "a range that
happens to include 65."

## Judgment: capability gap confirmed (not a bug -- documents an architecture limit)

SRA-side results for this question are **not reliable** for a numeric-threshold question: some
matches are correct, some are off by the threshold itself. Metalog-side results are fully
correct because a real numeric column exists there. There is currently no mechanism anywhere
in JattrConceptIndex/CriterionResolver to evaluate `>`, `<`, or any numeric comparison against
a matched jattr value -- only embedding-distance "closeness in meaning," which happens to give
partial, unreliable signal for numeric concepts expressed as text.

## needs_researcher_confirmation: yes

Worth a future design pass (e.g. a numeric-predicate criterion type, separate from
jattr_criteria's semantic matching) if numeric-threshold questions are expected to be common,
or is this an acceptable known limitation given Metalog already handles the clean cases?
