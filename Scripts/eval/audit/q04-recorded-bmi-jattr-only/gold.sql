-- version: 1
-- date: 2026-10-19
-- reason: fresh question authored to cover the "jattr-only" gap (no native SQL column for
--   BMI exists anywhere in the mirror's schema -- this question can ONLY be answered via
--   jattr_criteria, sql=None is the only correct translation shape). Independently verified:
--   the two real, well-populated BMI-recording keys (bmi_sam, host_body_mass_index_sam_s_dpl230)
--   together cover 221,094 DISTINCT biosamples with a recorded BMI value (counting distinct
--   biosamples, not raw rows -- some biosamples carry multiple SRA runs).
SELECT biosample FROM sra_metadata
WHERE jattr IS NOT NULL
  AND (json_extract_string(jattr, '$.bmi_sam') IS NOT NULL
       OR json_extract_string(jattr, '$.host_body_mass_index_sam_s_dpl230') IS NOT NULL);
