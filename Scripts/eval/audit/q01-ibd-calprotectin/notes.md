# q01-ibd-calprotectin

**Question:** "IBD fecal metagenomic with calprotectin"

## Run: 2026-10-05_initial

**Plan:** `/private/pinto-lab/plans/20261005_184918_ibd-fecal-metagenomic-with-calprotectin/plan.json`

**Translation:** the translator correctly identified "IBD diagnosis" and "calprotectin measurement"
as `jattr_criteria` (combinator `"all"`), but *also* wrote a native-SQL bucket matching any
feces/gut-metagenome sample (`librarysource = 'METAGENOMIC' AND (organism ILIKE '%feces
metagenome%' OR organism ILIKE '%human gut metagenome%' OR biosamplemodel 'human-gut')`), with
no disease/biomarker constraint at all.

**Why this produced 996,410 rows despite "correct" jattr concepts:** `CriterionResolver._resolve`
(`src/cohortquery/cohort.py`) combines the native-SQL bucket and the jattr-criteria bucket via set
**union**, by design (documented: "bucket 2's same-fact-recorded-twice case"). Union can only add
matches, never remove them. Since the native bucket alone already covers virtually every
feces/gut-metagenome sample in the mirror, the jattr narrowing became invisible in the final count
— confirmed: **no pipeline bug**, this is the correct, documented behavior; it's the translator's
bucket assignment that's wrong for this question. The native bucket should have stayed empty/narrow
(or been omitted, `sql=None`) and let `jattr_criteria` alone carry the IBD+calprotectin matching.

## Independent verification (live mirror queries, 2026-10-05)

- `bioproject = 'PRJNA1265906' AND json_extract_string(jattr, '$.fecalcalprotectin_run') IS NOT NULL`
  → **134 rows**
- `json_extract_string(jattr, '$.fecalcalprotectin_run') IS NOT NULL` (no bioproject filter, mirror-wide)
  → **134 rows** — identical count confirms this jattr key is exclusive to PRJNA1265906.
- Fecal calprotectin is a standard clinical biomarker used almost exclusively to monitor IBD
  (Crohn's disease / ulcerative colitis) disease activity — a dataset recording it is IBD research
  by biological/clinical convention, even though no literal "IBD" text appears anywhere in this
  bioproject's study/sample_name/attributes (confirmed by a prior session, 2026-08-25, recorded in
  `Scripts/eval/questions.jsonl`'s own history for a related, narrower-worded question).
- Set comparison: generated (996,410) ⊇ gold (134) exactly — **overlap = 134, gold-only (missed) = 0**.
  The translator's result is not wrong by omission; every correct answer is in there, buried among
  ~996,276 false positives.

## Judgment: PARTIAL

Recall = 100% (0 correct answers missed). Precision ≈ 0.0134% (134 / 996,410). Under the existing
`run_eval.py` scorer (exact set equality), this would score as a hard 0/MISMATCH — which is the
right call for that binary metric, but loses the nuance that the translator's jattr-concept
recognition itself worked; the failure is specifically in how the native-SQL bucket was scoped
alongside it.

## needs_researcher_confirmation: yes

**What to confirm:** is `fecalcalprotectin_run` (134 rows, exclusively PRJNA1265906) the complete,
correct ground truth for "calprotectin measured," or should it also include adjacent jattr keys
seen in an older, pre-concept-search plan for a similarly-worded question
(`Workspaces/IBD_calprotectin/0_inputs/plan.json`, 1,261 rows via a broad OR of ~30 jattr key names
including `calprotectin_sam`, `calprotectin_numeric_sam`, `host_fecal_calprotectin_mgpergdryweight_sam`,
etc.) — those additional keys were NOT independently re-verified in this session (their real presence/
semantics on the current mirror is unconfirmed), so gold here is deliberately the narrow, fully-verified
134-row set rather than the broader, partially-unverified 1,261-row set. A researcher should say
whether the broader set's extra keys are genuine synonyms worth folding into gold v2.

## Why missed (translator)

Not a literal terminology gap — the translator *did* recognize the right concepts as jattr
criteria. The gap is architectural/prompt-level: the translator doesn't appear to understand that
the native-SQL bucket and jattr_criteria combine via union (additive), so writing a broad native
bucket "just in case" actively defeats the jattr narrowing instead of being a harmless redundant
check. Worth flagging to whoever owns `prompt.py`: the system prompt may need to state explicitly
that the native-SQL bucket is unioned in, not intersected, so an LLM's instinct to "also match
broadly for safety" needs to be suppressed for this field.
