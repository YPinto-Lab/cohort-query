# q01-ibd-calprotectin — recheck after sql_jattr_combinator fix

**Trigger:** code_change (PR #59 merged — `sql_jattr_combinator: "union"|"intersect"` on `SourceQuery`)

**Plan:** `/private/pinto-lab/plans/20261006_113117_ibd-fecal-metagenomic-with-calprotectin/plan.json`

## What changed vs. the initial run

The LLM now correctly emits `sql_jattr_combinator: "intersect"` for this question, with:
- native bucket: `librarysource = 'METAGENOMIC' AND (biosamplemodel_sam ILIKE '%fecal%' OR '%gut%')`
- jattr: `["IBD diagnosis", "calprotectin measurement"]`, combinator `"all"`

Result: **436 rows** (down from 996,410 — the intersect mechanism works exactly as designed).

## But: zero overlap with gold (134 rows)

Checked directly: the native bucket alone *does* correctly match all 134 gold
(PRJNA1265906) samples (134/134, confirmed by query). The loss happens entirely on the
jattr side. The plan's own standalone per-concept counts show why:

- `"IBD diagnosis"` standalone: 97,987 biosamples matched
- `"calprotectin measurement"` standalone: 2,625 biosamples matched, across 10 distinct
  jattr keys: `calprotectin_sam`, `calprotectin_units_sam`, `calprotectin_numeric_sam`,
  `calprotectin_ave_sam`, `value_calprotectin_sam`, `Calprotectin`, `calprotectin`,
  `inhibitory calprotectin`, `subinhibitory calprotectin`, `calprotectin buffer`

**`fecalcalprotectin_run` — the exact key all 134 gold samples use — is not among the
matched keys.** The nearest-neighbor embedding lookup against `attribute_values_index`/
`attribute_keys_index` simply never surfaced it as similar enough to "calprotectin
measurement," despite ten other, more loosely-named calprotectin keys matching fine.

Since `jattr_combinator="all"` requires a sample to match BOTH concepts, and these 134
samples are entirely absent from the "calprotectin measurement" match set, they're
excluded regardless of what "IBD diagnosis" found for them.

## This is a separate, pre-existing bug, not a regression from the sql_jattr_combinator fix

Under the old (broken) union behavior this gap was invisible — the broad native-SQL
bucket swallowed everything into the result regardless of what jattr found, so a
concept-search miss never surfaced. The fix made the pipeline *correctly* depend on
jattr matching for this kind of question, which is exactly what exposed the miss.
**Fixing the union bug was necessary to even see this one.**

## Judgment: MISMATCH (recall 0% against this specific gold set)

The 436-row result is *precision-plausible* (10 real calprotectin jattr keys, properly
intersected with IBD-diagnosis concept matches) but misses the one bioproject
independently verified as ground truth entirely, due to the embedding gap above.

## needs_researcher_confirmation: yes

Two separate things to confirm:
1. Is the jattr concept-search embedding gap for `fecalcalprotectin_run` worth
   investigating/fixing (likely scope: LanceDB attribute_values_index re-embedding, or
   a key-name normalization step — concatenated `fecalcalprotectin_run` may embed
   poorly compared to the more conventional `calprotectin_*_sam` naming pattern)?
2. Is `jattr_combinator="all"` the right choice for "IBD diagnosis" + "calprotectin
   measurement" at all, given IBD context for a calprotectin study may be implicit at
   the study/publication level rather than recorded per-sample? If so, "any" (with a
   post-hoc researcher review of the union) might be the more honest default for this
   kind of compound clinical-context question — a separate, prompt-level decision from
   today's sql_jattr_combinator fix.
