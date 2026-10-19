-- SRA_METADATA
SELECT biosample FROM sra_metadata WHERE organism = 'Homo sapiens';

-- METALOG_METADATA
SELECT biosample, sample_alias FROM metalog_metadata WHERE (subject_disease_status ILIKE '%type 2 diabetes%' OR Comorbidities_1 IN ('Diabetes mellitus', 'Diabetes mellitus, hypertension, hyperlipidemia')) AND host = 'Homo sapiens';