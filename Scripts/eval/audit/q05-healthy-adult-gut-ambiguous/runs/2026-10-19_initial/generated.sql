-- SRA_METADATA
SELECT biosample FROM sra_metadata WHERE librarysource = 'METAGENOMIC' AND (organism ILIKE '%gut metagenome%' OR array_to_string(biosamplemodel_sam, ' ') ILIKE '%human-gut%' OR array_to_string(biosamplemodel_sam, ' ') ILIKE '%metagenome%');

-- METALOG_METADATA
SELECT biosample, sample_alias FROM metalog_metadata WHERE (environmental_package = 'human-gut' OR tissue_type = 'Stool') AND age_category IN ('adult', 'adolescent, adult') AND subject_disease_status = 'CTR';