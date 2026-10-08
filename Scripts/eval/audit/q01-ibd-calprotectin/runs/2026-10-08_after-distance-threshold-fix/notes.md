# Run: 2026-10-08_after-distance-threshold-fix

**Context:** recheck against a mirror where all three fixes are live: PR #59 (intersect
semantics), PR #61 (deterministic key eligibility), and PR #62 (distance-threshold +
capped-candidate retrieval, replacing fixed `TOP_K=5`).

## Translation

```json
{
  "sql": "SELECT biosample FROM sra_metadata WHERE librarysource = 'METAGENOMIC' OR organism ILIKE '%gut metagenome%' OR organism ILIKE '%feces metagenome%' OR organism ILIKE '%metagenome%' OR array_to_string(biosamplemodel_sam, ' ') ILIKE '%human-gut%' OR array_to_string(biosamplemodel_sam, ' ') ILIKE '%metagenome%'",
  "jattr_criteria": ["IBD diagnosis", "calprotectin measurement"],
  "jattr_combinator": "all",
  "sql_jattr_combinator": "intersect"
}
```

## PR #62 confirmed working

"calprotectin measurement" now matches 77 keys/values, **including `fecalcalprotectin_run`**
(the key PR #61's rebuild restored, that the old `TOP_K=5` still couldn't surface). The
distance-threshold retrieval fix is directly verified: the correct key is now actually used.

## But: gold v1 was wrong, not the pipeline

Generated cohort: 1,197 biosamples. Overlap with **gold v1** (134, `PRJNA1265906`): 0. Dug in:
none of the 52,980 biosamples matched by "IBD diagnosis" overlap `PRJNA1265906` at all -- that
bioproject genuinely has no explicit IBD-type jattr field, confirmed directly against the
real mirror. Gold v1's premise ("calprotectin implies IBD by clinical convention, even with
no literal IBD field") was put to the researcher and explicitly **rejected** 2026-10-08: gold
must require an explicit IBD-type field, not an inferred one.

Re-derived gold independently under that stricter rule (see `gold.sql` v2): biosamples with
BOTH an explicit IBD-type jattr key AND an explicit calprotectin-type jattr key, non-null, on
the same sample. Result: **665 biosamples, all in bioproject PRJEB18471** -- a different
bioproject entirely from v1's guess.

## Verification against gold v2

- Overlap: **665 / 665** -- full recall, zero missed.
- Generated-only (extra): 532 (precision 665/1197 = 55.6%).

## Judgment: PARTIAL

100% recall, 55.6% precision. The extra 532 rows are the native-SQL bucket's breadth
(`librarysource = 'METAGENOMIC' OR organism ILIKE ...`, a wide net) intersected with
jattr matches that are real but not as tightly scoped as gold's two-key-co-occurrence
rule -- e.g. a sample might match "IBD diagnosis" via a loosely-related value and
"calprotectin measurement" via a different real calprotectin key than gold's own list,
both genuinely jattr-relevant but not meeting gold v2's stricter definition.

This is a precision question, not a correctness bug: the translator's native-SQL bucket is
intentionally broad (any metagenomic/gut sample) and intersected with two independently
resolved jattr concepts -- reasonable behavior. Whether gold v2's narrow co-occurrence
rule or the system's broader jattr-concept-based reach is the "right" granularity for this
kind of question is itself a judgment call, flagged below.

## needs_researcher_confirmation: yes

Is 55.6% precision (665/1197) an acceptable outcome for this kind of broad jattr-criteria
question, or should gold v2's narrow co-occurrence definition be treated as the target
precision bar going forward?
