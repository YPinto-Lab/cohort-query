# q09-no-antibiotic-exposure-negation

**Question:** "samples not exposed to antibiotics"

**Why this question:** capability-boundary test -- does the pipeline have any way to express
negation of a jattr concept?

## Run: 2026-10-19_initial

**Translation:**
```json
[
  {"source": "SRA_METADATA", "sql": null,
   "jattr_criteria": ["antibiotic exposure", "antibiotic treatment", "antibiotic administration"]},
  {"source": "METALOG_METADATA",
   "sql": "SELECT biosample, sample_alias FROM metalog_metadata WHERE antibiotic IS NULL AND (intervention IS NULL OR (intervention NOT ILIKE '%antibiotic%' AND intervention NOT ILIKE '%ABX%')) AND (Drug_antibiotic_last3y IS NULL OR Drug_antibiotic_last3y = 'No') AND days_since_antibiotics IS NULL AND range_days_since_ABXs IS NULL AND range_days_since_antibiotics IS NULL"}
]
```

**Metalog correctly inverted the logic** via real native SQL negation (`IS NULL`, `NOT ILIKE`,
`= 'No'`) -- a genuinely well-constructed negated query, because native SQL naturally supports
NOT/IS NULL semantics.

## Confirmed bug: SRA's jattr_criteria for "NOT exposed" is byte-for-byte IDENTICAL to q06's "exposed" query

Compared directly against q06 ("samples with antibiotic exposure"): the SRA_METADATA
`jattr_criteria` list -- `["antibiotic exposure", "antibiotic treatment", "antibiotic
administration"]` -- is exactly the same for both questions. The translator completely failed
to invert the SRA-side semantics for negation; it reused the same positive-match concepts
regardless of "not" in the question. **The SRA half of this answer is factually wrong**: it
returns antibiotic-EXPOSED samples for a question asking for antibiotic-NOT-exposed samples
(confirmed: SRA_METADATA row count for q09 is identical to q06's, 75,172 in both).

This is distinct from q01's "value-polarity-agnostic by design" finding (which was about a
field existing regardless of its recorded value, confirmed intentional). This is a different,
more serious problem: JattrConceptIndex has no negation mechanism at all -- "matching" only
ever returns things CLOSE to a concept's embedding, with no way to ask for the opposite. When
the translator has no native column to fall back on (unlike Metalog here), it silently
produces the wrong-polarity answer instead of recognizing the limitation.

**Downstream risk, worth flagging explicitly:** `sql_jattr_combinator="union"` for both source
queries means the final combined cohort (`Cohort.union()`) would merge Metalog's correctly
negated samples WITH SRA's incorrectly positive-matched samples under one "this means NOT
exposed" result set -- actively misleading if taken at face value, not merely imprecise.

## Judgment: MISMATCH (confirmed defect)

## needs_researcher_confirmation: yes

Is this worth a translator-prompt-level fix (explicitly instruct: jattr_criteria has no
negation -- either decline negated jattr-only questions, or require a native column path), or
is it acceptable as a known limitation given Metalog already covers the common cases where
negation matters?
