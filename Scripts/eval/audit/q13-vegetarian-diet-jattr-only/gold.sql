-- version: 1
-- date: 2026-10-19
-- reason: fresh jattr-only question in a new domain (diet, distinct from BMI/antibiotics) --
--   no native diet column exists. Independently verified: 599 distinct biosamples with a
--   non-null vegetarian_sam value.
SELECT biosample FROM sra_metadata
WHERE jattr IS NOT NULL AND json_extract_string(jattr, '$.vegetarian_sam') IS NOT NULL;
