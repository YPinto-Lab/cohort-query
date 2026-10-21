# q02-prjna400072-bioproject-lookup

**Question:** "samples from bioproject PRJNA400072"

**Why this question:** mined from a historical pre-pivot `ask()` run
(`Workspaces/PRJNA400072/PRJNA400072/0_inputs/plan.json`). Deliberately the opposite case
from q01: a pure exact-match bioproject lookup with zero jattr ambiguity -- a control/baseline
contrast to q01's fuzzy-search-heavy case, exercising the simple native-SQL path end to end.

## Run: 2026-10-19_initial

**Plan:** `/private/pinto-lab/plans/20261019_115247_samples-from-bioproject-prjna400072/plan.json`

**Translation:**
```json
[
  {"source": "SRA_METADATA", "sql": "SELECT biosample FROM sra_metadata WHERE bioproject = 'PRJNA400072'"},
  {"source": "METALOG_METADATA", "sql": "SELECT biosample, sample_alias FROM metalog_metadata WHERE study_accession = 'PRJNA400072'"}
]
```

No jattr_criteria on either source -- correctly recognized as a pure native-column lookup.

## Independent verification (live mirror, 2026-10-19)

- `bioproject = 'PRJNA400072'` -> **220 biosamples**, matching the historical plan's own
  discovered count exactly.
- Checked whether the native `bioproject` column misses anything the historical plan's jattr
  fallback keys (`bioproject_accession_sam_s_dpl219`, `bioproject_id_sam`, etc.) would catch:
  **zero** extra biosamples found via fallback-only. The native column fully covers this
  bioproject; the historical plan's jattr hedge was unnecessary defensive breadth, not a real gap.
- Set comparison: generated (220) == gold (220) exactly. Overlap 220, missed 0, extra 0.

## Judgment: MATCH

Exact match, 100% recall and precision. Confirms the simple native-SQL exact-match path works
correctly end to end on the current pipeline (PR #59 + #61 + #62), independent of all the
jattr-search machinery q01 exercised.
