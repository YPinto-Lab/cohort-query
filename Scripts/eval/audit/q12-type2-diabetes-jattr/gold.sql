-- version: 1 (SUPERSEDED by version 2 below -- kept for history, not executed)
-- date: 2026-10-19
-- reason: fresh question covering a second disease concept (distinct from q03's tumor case)
--   to broaden disease-concept coverage. Initially verified without a host-organism filter:
--   46,271 distinct biosamples via the two most literal diabetes keys.
--
-- SELECT biosample FROM sra_metadata
-- WHERE jattr IS NOT NULL
--   AND (json_extract_string(jattr, '$.diabetes_sam') IS NOT NULL
--        OR json_extract_string(jattr, '$.diabetes_type_sam_s_dpl165') IS NOT NULL);

-- version: 2 (current)
-- date: 2026-10-19
-- reason: v1 missed that "patients" implies human -- diabetes_sam is overwhelmingly a MOUSE
--   disease-model field (45,736 total occurrences vs. only 9,221 when restricted to Homo
--   sapiens). The translator's own SQL correctly intersected with organism = 'Homo sapiens';
--   v1's naive gold, with no host filter, was wrong in the same direction as q07's mistake.
--   Corrected: 9,221 distinct Homo sapiens biosamples with diabetes_sam present.
SELECT biosample FROM sra_metadata
WHERE organism = 'Homo sapiens'
  AND jattr IS NOT NULL
  AND (json_extract_string(jattr, '$.diabetes_sam') IS NOT NULL
       OR json_extract_string(jattr, '$.diabetes_type_sam_s_dpl165') IS NOT NULL);
