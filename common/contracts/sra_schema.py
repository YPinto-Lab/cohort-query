"""
Data contracts for the two SRA source files and their validated types.

SRAMetadataSchema  — one row per accession (acc), no taxonomy columns.
SRATaxonomySchema  — one row per taxon observed per accession.
"""
import pandera.pandas as pa
from pandera.typing import Series


class SRAMetadataSchema(pa.DataFrameModel):
    """
    Contract for metadata.csv — 1 row per acc.
    Contains all SRA run/sample/bioproject metadata fields.
    No taxonomy columns (tax_id, rank, name, counts, nested-set).
    """
    acc: Series[str] = pa.Field(nullable=False)
    assay_type: Series[str] = pa.Field(nullable=True)
    center_name: Series[str] = pa.Field(nullable=True)
    consent: Series[str] = pa.Field(nullable=True)
    experiment: Series[str] = pa.Field(nullable=True)
    sample_name: Series[str] = pa.Field(nullable=True)
    instrument: Series[str] = pa.Field(nullable=True)
    librarylayout: Series[str] = pa.Field(nullable=True)
    libraryselection: Series[str] = pa.Field(nullable=True)
    librarysource: Series[str] = pa.Field(nullable=True)
    platform: Series[str] = pa.Field(nullable=True)
    sample_acc: Series[str] = pa.Field(nullable=True)
    biosample: Series[str] = pa.Field(nullable=True)
    organism: Series[str] = pa.Field(nullable=True)
    sra_study: Series[str] = pa.Field(nullable=True)
    releasedate: Series[str] = pa.Field(nullable=True)
    mbytes: Series[int] = pa.Field(nullable=True)
    loaddate: Series[str] = pa.Field(nullable=True)
    avgspotlen: Series[int] = pa.Field(nullable=True)
    mbases: Series[int] = pa.Field(nullable=True)
    insertsize: Series[str] = pa.Field(nullable=True)
    library_name: Series[str] = pa.Field(nullable=True)
    biosamplemodel_sam: Series[str] = pa.Field(nullable=True)
    collection_date_sam: Series[str] = pa.Field(nullable=True)
    geo_loc_name_country_calc: Series[str] = pa.Field(nullable=True)
    geo_loc_name_country_continent_calc: Series[str] = pa.Field(nullable=True)
    geo_loc_name_sam: Series[str] = pa.Field(nullable=True)
    ena_first_public_run: Series[str] = pa.Field(nullable=True)
    ena_last_update_run: Series[str] = pa.Field(nullable=True)
    sample_name_sam: Series[str] = pa.Field(nullable=True)
    datastore_filetype: Series[str] = pa.Field(nullable=True)
    datastore_provider: Series[str] = pa.Field(nullable=True)
    datastore_region: Series[str] = pa.Field(nullable=True)
    attributes: Series[str] = pa.Field(nullable=True)
    jattr: Series[str] = pa.Field(nullable=True)
    run_file_version: Series[str] = pa.Field(nullable=True)
    bioproject: Series[str] = pa.Field(nullable=True)

    class Config:
        strict = "filter"
        coerce = True


class SRATaxonomySchema(pa.DataFrameModel):
    """
    Contract for taxonomy.csv — many rows per acc (one per detected taxon).
    Contains the nested-set taxonomy tree fields and read counts per taxon.
    bioproject is included to support per-project filtering without joining metadata.
    """
    acc: Series[str] = pa.Field(nullable=False)
    tax_id: Series[int] = pa.Field(nullable=True)
    rank: Series[str] = pa.Field(nullable=True)
    name: Series[str] = pa.Field(nullable=True)
    total_count: Series[int] = pa.Field(nullable=True)
    self_count: Series[int] = pa.Field(nullable=True)
    ilevel: Series[int] = pa.Field(nullable=True)
    ileft: Series[int] = pa.Field(nullable=True)
    iright: Series[int] = pa.Field(nullable=True)
    bioproject: Series[str] = pa.Field(nullable=True)

    class Config:
        strict = True
        coerce = True
