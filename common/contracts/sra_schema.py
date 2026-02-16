"""
This module defines the data contract for SRA metadata using pandera.
It ensures that any DataFrame representing SRA metadata conforms to a strict,
pre-defined structure, which is a key principle of the iDesign architecture
for maintaining data quality and preventing schema drift in a data science pipeline.
"""
import pandera.pandas as pa
from pandera.typing import Series

class SRAMetadataSchema(pa.DataFrameModel):
    """
    A pandera schema to validate the structure and types of the SRA metadata DataFrame.

    This schema acts as a formal "contract" for the data that flows from the
    SRA accessor. By enforcing this contract, we ensure that downstream
    components can rely on the data's structure, which is crucial for
    maintaining a robust and scalable data science system.
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
    releasedate: Series[str] = pa.Field(nullable=True) # Could be datetime
    mbytes: Series[int] = pa.Field(nullable=True)
    loaddate: Series[str] = pa.Field(nullable=True) # Could be datetime
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
        """
        Configuration for the schema.
        `strict=True` ensures that no undefined columns are present in the DataFrame.
        """
        strict = True
        coerce = True
