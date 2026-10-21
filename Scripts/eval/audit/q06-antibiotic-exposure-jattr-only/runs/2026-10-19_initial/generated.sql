-- SRA_METADATA: jattr-only, no native SQL

-- METALOG_METADATA
SELECT biosample, sample_alias FROM metalog_metadata WHERE antibiotic IS NOT NULL OR Drug_antibiotic_last3y IS NOT NULL OR days_since_antibiotics IS NOT NULL OR range_days_since_antibiotics IS NOT NULL OR medication ILIKE '%antibiotic%' OR medication_full ILIKE '%antibiotic%' OR medication_with_parents ILIKE '%antibiotic%';