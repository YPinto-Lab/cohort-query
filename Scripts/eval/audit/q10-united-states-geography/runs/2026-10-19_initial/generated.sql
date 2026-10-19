-- SRA_METADATA
SELECT biosample FROM sra_metadata WHERE geo_loc_name_country_calc = 'USA';

-- METALOG_METADATA
SELECT biosample, sample_alias FROM metalog_metadata WHERE geographic_location = 'USA';