-- SRA_METADATA: jattr-only, no native SQL

-- METALOG_METADATA
SELECT biosample, sample_alias FROM metalog_metadata WHERE age_category IN ('baby', 'baby, child');