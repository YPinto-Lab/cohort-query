# q05-healthy-adult-gut-ambiguous

**Question:** "healthy adult gut microbiome samples"

**Why this question:** fresh question authored to cover the "ambiguous phrasing" benchmark
gap. Deliberately vague on three axes (see gold.sql): what counts as "healthy", what age
threshold is "adult", what counts as "gut microbiome". Scored by whether the translator's
chosen interpretation is defensible, not by exact-match overlap against one picked answer.

## Run: 2026-10-19_initial

**Plan:** `/private/pinto-lab/plans/20261019_123324_healthy-adult-gut-microbiome-samples/plan.json`

**Translation (SRA_METADATA):**
```json
{
  "sql": "SELECT biosample FROM sra_metadata WHERE librarysource = 'METAGENOMIC' AND (organism ILIKE '%gut metagenome%' OR array_to_string(biosamplemodel_sam, ' ') ILIKE '%human-gut%' OR array_to_string(biosamplemodel_sam, ' ') ILIKE '%metagenome%')",
  "jattr_criteria": ["adult age", "healthy status", "no disease"],
  "jattr_combinator": "any",
  "sql_jattr_combinator": "intersect"
}
```

**Translation (METALOG_METADATA):**
```sql
SELECT biosample, sample_alias FROM metalog_metadata
WHERE (environmental_package = 'human-gut' OR tissue_type = 'Stool')
  AND age_category IN ('adult', 'adolescent, adult')
  AND subject_disease_status = 'CTR'
```

Result: SRA_METADATA 255,474 biosamples; METALOG_METADATA 8,768.

## Interpretation chosen, per axis

- **Gut microbiome**: both sources used the standard metagenomic/fecal-sample native pattern
  (q01's own established pattern for SRA; Metalog's `environmental_package`/`tissue_type`).
  Defensible, the most common and least ambiguous reading.
- **Adult**: SRA folded "adult age" into the jattr_criteria list; Metalog used its native
  `age_category` column precisely (`'adult'` or `'adolescent, adult'`). Defensible on both sides.
- **Healthy**: SRA folded "healthy status" and "no disease" into the same jattr_criteria list;
  Metalog used `subject_disease_status = 'CTR'` (control) precisely. Metalog's choice is clean
  and defensible. SRA's is murkier -- see finding below.

## A real expressiveness gap, surfaced by this question

SRA_METADATA combined all three semantically distinct asks -- "adult age", "healthy status",
"no disease" -- into ONE flat `jattr_criteria` list with `jattr_combinator="any"`. That means a
biosample only needs to match **any one** of the three to count, not "adult AND (healthy OR
no-disease)" as the question actually implies. A sample matched purely via an age-type field,
with zero information about health/disease status, still counts as "healthy" under this
translation -- the "adult" and "healthy" requirements are independent, both-required facts, not
alternative phrasings of the same fact (contrast q01's calprotectin-key-synonym case, where
"any" correctly meant "any synonym of the same single fact").

This isn't a bug in the resolver (`jattr_combinator` behaves exactly as documented) -- it's a
genuine **expressiveness gap**: the current schema has one flat all-or-any combinator across an
entire jattr_criteria list, with no way to express "require axis A, and separately require (B or
C)". Flagging as an architecture observation, not something to fix now.

## Judgment: PARTIAL

Metalog's resolution is clean and fully defensible. SRA's resolution is defensible in its
native-SQL/gut-scoping half but structurally too loose in its age+health half, due to a real
schema expressiveness limit rather than a translator mistake per se.

## needs_researcher_confirmation: yes

Is this flat jattr_combinator expressiveness gap (can't require independent sub-conditions
within one SourceQuery) worth a future design pass, or is the current one-flat-list-per-source
shape an intentional simplicity tradeoff?
