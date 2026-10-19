-- SRA_METADATA
SELECT biosample FROM sra_metadata WHERE organism = 'mouse gut metagenome' AND (librarysource = 'METAGENOMIC' OR librarysource = 'METATRANSCRIPTOMIC');

-- METALOG_METADATA
SELECT biosample, sample_alias FROM metalog_metadata WHERE (host_common_name = 'Mouse' OR host_scientific_name = 'Mus musculus') AND (environment_feature ILIKE '%intestine%' OR environment_material ILIKE '%fecal%' OR environment_material ILIKE '%feces%' OR tissue_type = 'Stool') AND sample_description ILIKE '%metagenome%';