-- version: 1
-- date: 2026-10-19
-- reason: fresh health-state jattr concept with an unusually clean, literal, well-populated
--   single key (pregnant_sam) -- a good "should be easy" control case for the jattr-only
--   family, contrasting with q04/q06/q12/q13's messier multi-key neighborhoods.
--   Independently verified: 35,544 distinct biosamples.
SELECT biosample FROM sra_metadata
WHERE jattr IS NOT NULL AND json_extract_string(jattr, '$.pregnant_sam') IS NOT NULL;
