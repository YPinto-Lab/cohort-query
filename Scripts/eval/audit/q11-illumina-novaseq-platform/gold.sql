-- version: 1
-- date: 2026-10-19
-- reason: fresh question covering sequencing-technology scoping via a real native column
--   (instrument) -- a clean exact-match baseline test, same shape as q02/q10. Independently
--   verified: 9,538,316 distinct biosamples across the three real NovaSeq instrument string
--   variants (Illumina NovaSeq 6000 / X / X Plus).
SELECT biosample FROM sra_metadata WHERE instrument ILIKE '%novaseq%';
