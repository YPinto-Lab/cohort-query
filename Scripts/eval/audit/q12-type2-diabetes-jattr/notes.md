# q12-type2-diabetes-jattr

**Question:** "samples from patients with type 2 diabetes"

**Why this question:** second disease concept (distinct from q03's tumor case) to broaden
disease-concept coverage.

## Run: 2026-10-19_initial

**Translation:**
```json
{"source": "SRA_METADATA", "sql": "SELECT biosample FROM sra_metadata WHERE organism = 'Homo sapiens'",
 "jattr_criteria": ["type 2 diabetes"], "sql_jattr_combinator": "intersect"}
```

## Gold correction (v1 -> v2), same pattern as q07

Initial gold had no host-organism filter: 46,271 biosamples. The translator's own SQL
intersected with `organism = 'Homo sapiens'` ("patients" implies human) -- checked directly:
`diabetes_sam` is overwhelmingly a MOUSE disease-model field in this mirror (45,736 total
occurrences, only 9,221 restricted to Homo sapiens). v1's naive gold was wrong in the same
direction as q07's mistake (conflating a jattr key's total reach with the human-only subset
the question actually implies). Corrected gold v2: 9,257 Homo sapiens biosamples.

## Verification against gold v2

- Gold: 9,257. Generated: 30,652. Overlap: 9,257 (100% recall). Extra: 21,395.

## Judgment: PARTIAL

Full recall against the corrected gold. Extra rows are the now-familiar, already-settled
pattern (real matches via other genuine diabetes-related keys/values my narrow 2-key gold
didn't enumerate -- consistent with q01/q06's precedent).
