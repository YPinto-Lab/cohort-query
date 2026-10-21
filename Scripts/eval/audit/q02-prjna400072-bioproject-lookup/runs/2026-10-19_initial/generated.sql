-- SRA_METADATA
SELECT biosample FROM sra_metadata WHERE bioproject = 'PRJNA400072';

-- METALOG_METADATA
SELECT biosample, sample_alias FROM metalog_metadata WHERE study_accession = 'PRJNA400072';