# Run: 2026-10-08_after-index-rebuild

**Context:** first recheck against a mirror where BOTH fixes are live:
PR #59 (`sql_jattr_combinator` intersect semantics) and PR #61 (deterministic,
sampling-free key eligibility -- `attribute_keys_index`/`attribute_values_index`
fully rebuilt 2026-10-07/08, job 32916510).

**Also fixed in this run:** `run_question.py`'s `write_sidecars` was re-executing
`query.sql` directly instead of using the resolved `Cohort` (`plan.discovered`),
silently recording the raw native-SQL bucket's row count instead of the real,
jattr-intersected answer. A first attempt at this recheck (discarded, not
recorded in index.csv) produced 6,567,905 rows this way, even though the real
resolved cohort for that plan was 0. Fixed in commit 764cef4 before this run.

## Translation

```json
{
  "sql": "SELECT biosample FROM sra_metadata WHERE librarysource = 'METAGENOMIC' AND (organism ILIKE '%fecal metagenome%' OR organism ILIKE '%human gut metagenome%' OR organism ILIKE '%gut metagenome%' OR organism ILIKE '%feces metagenome%' OR list_contains(biosamplemodel_sam, 'MIGS/MIMS/MIMARKS.human-gut'))",
  "jattr_criteria": ["IBD diagnosis", "calprotectin measurement"],
  "jattr_combinator": "all",
  "sql_jattr_combinator": "intersect"
}
```

Correct translation this time: native SQL narrows to fecal/gut metagenomes, jattr
criteria narrow further to IBD+calprotectin, combined via intersect. No repeat of
the original union-swamping bug.

## Verification against gold (134 rows, `fecalcalprotectin_run`, exclusive to PRJNA1265906)

- Generated cohort: **665** biosamples.
- Overlap with gold: **0**. Gold-only (missed): 134. Generated-only (extra): 665.

## Root cause: NOT the key-presence bug PR #61 fixed

Confirmed directly against the real `attribute_keys_index`:
- `fecalcalprotectin_run` **is present** in the rebuilt index (it was absent before
  PR #61) and its row carries all 134 correct biosamples.
- Querying the index for "calprotectin measurement" with `limit(50)` instead of the
  production `TOP_K=5`: `fecalcalprotectin_run` ranks **#27** (distance 0.817) among
  85,143 keys -- a real, close semantic match.
- Why it never surfaces in production: `TOP_K=5` (`src/cohortquery/jattr_concepts.py`)
  returns only the 5 nearest keys. Ranks #1-18 are all near-duplicate
  `calprotectin_*_sam`/`calprotectin*_run` naming variants (`calprotectin_sam`,
  `calprotectin_numeric_sam`, `calprotectin0_sam`, ... `fecal_calprotectin_sam`,
  `baseline_calprotectin_sam`), crowding the true answer out of the top 5 entirely.

This is a **distinct, still-open issue**: retrieval breadth (`TOP_K`), not key
eligibility/classification. The data is correct; the search returns too few
candidates for a vocabulary with this much naming duplication.

## Judgment: MISMATCH

Gold not found. Translator behavior is now correct (intersect fix holds); the
index now contains the right key with the right data; the failure is purely in
how many nearest neighbors get surfaced to the resolver.

## needs_researcher_confirmation: yes

What TOP_K (or a smarter dedup/rerank step) would reliably surface true matches
in naming-duplicate-heavy neighborhoods like this one, without blowing up
matching cost across the whole mirror? Flagging to the user rather than
picking a number unilaterally.
