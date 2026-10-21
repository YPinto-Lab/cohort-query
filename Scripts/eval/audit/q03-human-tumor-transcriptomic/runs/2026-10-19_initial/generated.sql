-- SRA_METADATA
SELECT biosample FROM sra_metadata WHERE organism = 'Homo sapiens' AND (assay_type = 'RNA-Seq' OR librarysource IN ('TRANSCRIPTOMIC', 'METATRANSCRIPTOMIC'));