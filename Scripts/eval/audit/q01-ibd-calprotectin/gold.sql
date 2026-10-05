-- version: 1
-- date: 2026-10-05
-- reason: initial authoring. Seeded from the translator's 2026-10-05_initial run (which
--   recognized "IBD diagnosis" and "calprotectin measurement" as jattr concepts but then
--   also wrote an overly broad native-SQL bucket that swamped them via UNION semantics --
--   see notes.md). Independently verified against real mirror values: the jattr key
--   fecalcalprotectin_run exists on exactly 134 rows mirror-wide, ALL of them in bioproject
--   PRJNA1265906 -- confirmed via two independent counts that agree (134 == 134).
--   Fecal calprotectin is a standard clinical biomarker used almost exclusively to monitor
--   IBD (Crohn's disease / ulcerative colitis) activity, so a dataset recording it is IBD
--   research by biological convention even though no literal "IBD" text appears anywhere
--   in this mirror's study/sample_name/attributes for this bioproject (confirmed by a prior
--   session, 2026-08-25).
SELECT biosample FROM sra_metadata
WHERE bioproject = 'PRJNA1265906'
  AND json_extract_string(jattr, '$.fecalcalprotectin_run') IS NOT NULL;
