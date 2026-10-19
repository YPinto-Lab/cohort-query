-- SRA_METADATA: jattr-only, no native SQL

-- METALOG_METADATA
SELECT biosample, sample_alias FROM metalog_metadata WHERE gestational_state = 'pregnant' AND sex = 'female';