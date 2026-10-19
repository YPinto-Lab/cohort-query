-- SRA_METADATA: jattr-only, no native SQL

-- METALOG_METADATA
SELECT biosample, sample_alias FROM metalog_metadata WHERE antibiotic IS NULL AND (intervention IS NULL OR (intervention NOT ILIKE '%antibiotic%' AND intervention NOT ILIKE '%ABX%')) AND (Drug_antibiotic_last3y IS NULL OR Drug_antibiotic_last3y = 'No') AND days_since_antibiotics IS NULL AND range_days_since_ABXs IS NULL AND range_days_since_antibiotics IS NULL;