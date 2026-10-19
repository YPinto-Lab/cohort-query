-- version: 1
-- date: 2026-10-19
-- reason: fresh age-concept question at the opposite extreme from q08 ("over 65 years old")
--   -- infants. Unlike q08, there is no single "age_years" numeric column cleanly applicable
--   here (infant age is usually recorded in weeks/days, not years), so this tests whether the
--   jattr concept search handles a young-age concept as well as it (partially) handled an old-
--   age one. Independently verified: 32,039 distinct biosamples via the three most literal
--   infant-age keys (infant_age_sam, host_age_infant_sam, fed_as_infant_sam).
SELECT biosample FROM sra_metadata
WHERE jattr IS NOT NULL
  AND (json_extract_string(jattr, '$.infant_age_sam') IS NOT NULL
       OR json_extract_string(jattr, '$.host_age_infant_sam') IS NOT NULL
       OR json_extract_string(jattr, '$.fed_as_infant_sam') IS NOT NULL);
