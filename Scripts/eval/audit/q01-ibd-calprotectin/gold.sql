-- version: 1 (SUPERSEDED by version 2 below -- kept for history, not executed)
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
--
-- SELECT biosample FROM sra_metadata
-- WHERE bioproject = 'PRJNA1265906'
--   AND json_extract_string(jattr, '$.fecalcalprotectin_run') IS NOT NULL;

-- version: 2 (current)
-- date: 2026-10-08
-- reason: v1's "calprotectin implies IBD by clinical convention" assumption was explicitly
--   rejected by the researcher (2026-10-08) -- gold requires an EXPLICIT IBD-type jattr key
--   on the SAME sample as an explicit calprotectin-type jattr key, not an inferred link.
--   Re-derived independently (not via the translator/pipeline under test): any of the real
--   IBD-naming variants AND any of the real calprotectin-naming variants (found via the
--   rebuilt attribute_keys_index) must both be present, non-null, on one biosample.
--   Result: 665 biosamples, ALL in bioproject PRJEB18471 -- a DIFFERENT bioproject than v1's
--   PRJNA1265906, which has no explicit IBD field at all and is correctly excluded under v2.
SELECT biosample FROM sra_metadata
WHERE jattr IS NOT NULL
  AND list_filter(json_extract_string(jattr, [
        '$.ibd_diagnosis_sam', '$.ibd_disease_sam', '$.ibd_sam', '$.ibd_diagnosis_refined_sam',
        '$.ibd_or_not_sam', '$.ibd_type_sam', '$.ibd_subtype_sam', '$.ibd_history_sam',
        '$.inflam_bowel_disease_sam', '$.inflammatory_bowel_disease_sam',
        '$.ibd___0_no__1_yes_sam', '$.ibd_case_control_sam', '$.crohns_disease_sam', '$.ibdstatus_sam'
      ]), x -> x IS NOT NULL) != []
  AND list_filter(json_extract_string(jattr, [
        '$.calprotectin_sam', '$.calprotectin_numeric_sam', '$.calprotectin0_sam',
        '$.calprotectin_ms_sam', '$.value_calprotectin_sam', '$.calprotectin_units_sam',
        '$.feacal_calprotectin_sam', '$.fecal_calprotectin_sam', '$.fecalcalprotectin_run',
        '$.host_fecal_calprotectin_mgpergdryweight_sam', '$.baseline_calprotectin_sam'
      ]), x -> x IS NOT NULL) != [];
