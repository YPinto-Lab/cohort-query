DROP TABLE sra.abx_PRJNA974858_metadata;
DROP TABLE sra.abx_PRJNA974858_taxonomy;


-- ── Query A: Metadata ───────────────────────────────────────

CREATE TABLE sra.abx_PRJNA974858_metadata
WITH (
  format = 'PARQUET',
  external_location = 's3://yarin-athena-results/projects/blood_wgs_metadata/',
  partitioned_by = ARRAY['bioproject']
) AS
SELECT
    M.acc,
    M.assay_type,
    M.center_name,
    M.consent,
    M.experiment,
    M.sample_name,
    M.instrument,
    M.librarylayout,
    M.libraryselection,
    M.librarysource,
    M.platform,
    M.sample_acc,
    M.biosample,
    M.organism,
    M.sra_study,
    M.releasedate,
    M.mbytes,
    M.loaddate,
    M.avgspotlen,
    M.mbases,
    M.insertsize,
    M.library_name,
    M.biosamplemodel_sam,
    M.collection_date_sam,
    M.geo_loc_name_country_calc,
    M.geo_loc_name_country_continent_calc,
    M.geo_loc_name_sam,
    M.ena_first_public_run,
    M.ena_last_update_run,
    M.sample_name_sam,
    M.datastore_filetype,
    M.datastore_provider,
    M.datastore_region,
    M.attributes,
    M.jattr,
    M.run_file_version,
    M.bioproject
FROM sra.metadata AS M
WHERE M.bioproject IN ('PRJNA974858');


-- ── Query B: Taxonomy ───────────────────────────────────────

CREATE TABLE sra.abx_PRJNA974858_taxonomy
WITH (
  format = 'PARQUET',
  external_location = 's3://yarin-athena-results/projects/blood_wgs_taxonomy/',
  partitioned_by = ARRAY['bioproject']
) AS
SELECT
    TAX.acc,
    TAX.tax_id,
    TAX.rank,
    TAX.name,
    TAX.total_count,
    TAX.self_count,
    TAX.ilevel,
    TAX.ileft,
    TAX.iright,
    M.bioproject
FROM sra.tax_analysis AS TAX
JOIN sra.metadata AS M
    ON TAX.acc = M.acc
WHERE M.bioproject IN ('PRJNA974858');


select * from sra.abx_PRJNA974858_metadata
select * from sra.abx_PRJNA974858_taxonomy
