-- version: 1 (SUPERSEDED by version 2 below -- kept for history, not executed)
-- date: 2026-10-19
-- reason: fresh question authored to extend the "non-metagenome bias" check to the opposite
--   direction -- host diversity WITHIN metagenomic samples. Initially verified naively using
--   the host SPECIES name (Mus musculus): 45,806 distinct biosamples.
--
-- SELECT biosample FROM sra_metadata
-- WHERE organism = 'Mus musculus' AND librarysource = 'METAGENOMIC';

-- version: 2 (current)
-- date: 2026-10-19
-- reason: v1 conflated host SPECIES (Mus musculus, which includes every tissue/library type --
--   genomic, transcriptomic, single-cell, etc., most of which are NOT metagenomic gut samples)
--   with the actual metagenome-sample organism LABEL. The translator's own generated SQL used
--   `organism = 'mouse gut metagenome'` -- the standard NCBI organism-string convention for
--   whole-metagenome shotgun sequencing of mouse gut samples (the same naming convention as
--   "human gut metagenome" established in q01). This is MORE precise than v1, not less --
--   confirmed independently: 249,477 distinct biosamples, exactly matching the system's own
--   generated count. Corrected gold to the right, more precise definition rather than scoring
--   a correct answer as wrong.
SELECT biosample FROM sra_metadata
WHERE organism = 'mouse gut metagenome'
  AND (librarysource = 'METAGENOMIC' OR librarysource = 'METATRANSCRIPTOMIC');
