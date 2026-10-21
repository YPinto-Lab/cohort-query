-- version: 1
-- date: 2026-10-19
-- reason: fresh question authored to cover the "non-metagenome" gap (per project memory
--   project_askslm_not_metagenomics_only.md: STAT profiles every SRA run, so human-tumour
--   cohorts are valid science and must never be filtered out by a metagenome-only bias).
--   Independently verified: `is_tumor_sam` is a clean boolean-ish jattr key stored as a
--   single-element JSON array (["Yes"]/["No"], no other values, no mid-ground). Counting
--   DISTINCT biosamples (some biosamples carry multiple SRA runs, so a raw row count
--   overstates this): 33,405 distinct Homo sapiens / TRANSCRIPTOMIC biosamples have
--   is_tumor_sam[0] = 'Yes'.
SELECT biosample FROM sra_metadata
WHERE organism = 'Homo sapiens'
  AND librarysource = 'TRANSCRIPTOMIC'
  AND json_extract_string(jattr, '$.is_tumor_sam[0]') = 'Yes';
