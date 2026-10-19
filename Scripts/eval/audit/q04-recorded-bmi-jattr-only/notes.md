# q04-recorded-bmi-jattr-only

**Question:** "samples with recorded body mass index"

**Why this question:** fresh question authored to cover the "jattr-only" benchmark gap --
no native SQL column for BMI exists anywhere in the SRA metadata schema, so `sql=None` with
a pure jattr_criteria is the only correct translation shape for SRA_METADATA.

## Run: 2026-10-19_initial

**Plan:** `/private/pinto-lab/plans/20261019_123227_samples-with-recorded-body-mass-index/plan.json`

**Translation:**
```json
[
  {"source": "SRA_METADATA", "sql": null, "jattr_criteria": ["body mass index"], "jattr_combinator": "any", "sql_jattr_combinator": "union"},
  {"source": "METALOG_METADATA", "sql": "SELECT biosample, sample_alias FROM metalog_metadata WHERE bmi IS NOT NULL", "jattr_criteria": [], "jattr_combinator": "any", "sql_jattr_combinator": "union"}
]
```

Correctly recognized `sql=None` for SRA_METADATA (no native BMI column exists -- pure jattr
concept) and correctly used Metalog's own native `bmi` column where one DOES exist. Good
cross-source behavior: the same underlying concept resolved differently per source, each
correctly.

## Verification against gold (distinct biosamples; see gold.sql)

- Gold: 221,094 (`bmi_sam` OR `host_body_mass_index_sam_s_dpl230` non-null)
- Generated (SRA_METADATA only): 104,346
- Overlap: 88,458. Missed: 132,636. Extra: 15,888.

## Confirmed bug: `host_body_mass_index_sam_s_dpl230` is entirely absent from the rebuilt keys index

Checked `discovered.jattr_matches`: `bmi_sam` WAS matched (87,298 biosamples) but
`host_body_mass_index_sam_s_dpl230` was not among any matched key. Queried the real
`attribute_keys_index` directly for this exact key -- **zero rows**. It was excluded at
build time, not a retrieval-ranking miss (unlike q01's case).

**Root cause, confirmed:** `ID_NAME_RE` in `step7_build_attribute_indexes.py` includes a bare,
unanchored `index` alternative (meant to catch generic numeric index/position fields like
`sample_index`), but it matches as a **substring** anywhere in the key name -- so it also
silently excludes any biologically meaningful key that happens to contain "index" as part of
a compound word, like `body_mass_index`. Same severity class as the original
`fecalcalprotectin_run` incident (PR #61): a real, biologically important key silently dropped
regardless of its value. This is a build-time exclusion bug, not a retrieval-tuning question --
confirmed, reproducible, root-caused. **Not yet fixed** (deferred per 2026-10-19 decision: flag
now, continue authoring Task 10 questions, fix later as its own bug branch).

## Judgment: PARTIAL (confirmed defect, not yet fixed)

## needs_researcher_confirmation: no -- root cause is confirmed, not a judgment call.
Action needed: fix `ID_NAME_RE`'s `index` pattern. Note a word-boundary/token fix alone won't
separate the two cases cleanly -- `sample_index` and `body_mass_index` have the identical
`_index` suffix shape, so no regex can tell "generic row/position index" from "a named
biological index" by shape alone. The realistic fix is removing `index` from the denylist
entirely: presence-only matching is already value-agnostic and cheap, so a few harmless generic
index/position keys slipping into the search space costs far less than silently dropping a real
biological key like BMI. Then rebuild/patch the keys index and recheck this question.
