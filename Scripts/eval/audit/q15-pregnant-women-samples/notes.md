# q15-pregnant-women-samples

**Question:** "pregnant women samples"

**Why this question:** clean, literal, well-populated single key (`pregnant_sam`) chosen as a
"should be easy" control case -- instead surfaced a genuine combinator finding.

## Run: 2026-10-19_initial

**Translation:**
```json
{"source": "SRA_METADATA", "sql": null,
 "jattr_criteria": ["pregnant status", "female sex"],
 "jattr_combinator": "all", "sql_jattr_combinator": "intersect"}
```

## Verification against gold (`pregnant_sam` non-null)

- Gold: 35,544. Generated: 31,711. Overlap: 17,773. Missed: 17,771. Extra: 13,938.

## Finding: "all" combinator over a redundant fact, the mirror image of q05

The translator required BOTH "pregnant status" AND "female sex" to match on the same sample
(`jattr_combinator="all"`). But "female sex" is not an independent fact here -- it's implied by
pregnancy, not a separate requirement the question actually asks for. Confirmed directly:
`pregnant_sam` alone matches 35,544 biosamples, but many of those don't ALSO carry a
separately-recorded sex-type field, so the "all" intersection with "female sex" wrongly
excludes genuinely pregnant samples. This is the inverse of q05's finding: there, independent
facts (adult AND healthy) were wrongly collapsed into "any" (too loose); here, a single fact
with a redundant restatement was wrongly required via "all" (too strict). Both point at the
same root cause: a flat `jattr_combinator` per source can't distinguish "these are alternate
phrasings of one fact" from "these are genuinely separate required facts" -- that judgment is
made per-question by the translator, and it got this one backwards.

## Judgment: PARTIAL

## needs_researcher_confirmation: yes

Same open question as q05: is this flat-combinator expressiveness/judgment issue worth a
translator-prompt-level guideline (e.g. don't require a redundant demographic fact alongside
a concept that already implies it), or an acceptable, occasional miscalibration?
