-- version: 1
-- date: 2026-10-19
-- reason: fresh question authored to cover geography (per CLAUDE.md's own motivating example:
--   "fecal metagenomes from adults with IBD, Western countries"). Discovered the translator
--   uses a real native SQL column, geo_loc_name_country_calc, not a jattr concept at all --
--   simpler than expected, but still worth having in the suite as a geography baseline.
--   Independently verified: exact match, 7,776,499 distinct biosamples -- consistent with the
--   US historically dominating SRA submission volume across all library/assay types (not
--   metagenome-specific).
SELECT biosample FROM sra_metadata WHERE geo_loc_name_country_calc = 'USA';
