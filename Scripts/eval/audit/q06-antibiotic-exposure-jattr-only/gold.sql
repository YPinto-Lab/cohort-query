-- version: 1
-- date: 2026-10-19
-- reason: fresh question authored for a second jattr-only concept (antibiotic exposure has no
--   native SQL column), chosen because it has a large real naming-variant neighborhood
--   (antibiotic_exposure_sam, antibiotics_run, antibiotic_treatment_sam, ... 300+ real
--   variants scouted earlier this session) -- a good breadth/precision test distinct from
--   q04's BMI case. Gold deliberately narrow: the two most literal, unambiguous keys.
SELECT biosample FROM sra_metadata
WHERE jattr IS NOT NULL
  AND (json_extract_string(jattr, '$.antibiotic_exposure_sam') IS NOT NULL
       OR json_extract_string(jattr, '$.antibiotics_exposure_sam') IS NOT NULL);
