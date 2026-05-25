"""
This module contains the SRAAccessor class, responsible for ingesting SRA metadata.
It follows the iDesign architecture pattern where the accessor's role is to fetch
data and ensure it conforms to a predefined contract (schema) before passing it
to other layers. This approach promotes type safety and data consistency
throughout the application.
"""
import pandas as pd
import pandera as pa
from pathlib import Path

from Common.contracts.sra_schema import SRAMetadataSchema

class SRAAccessor:
    """
    Accessor for fetching and validating SRA metadata from a local CSV file.
    """

    @staticmethod
    @pa.check_types
    def get_sra_metadata(file_path: Path) -> pa.typing.DataFrame[SRAMetadataSchema]:
        """
        Reads SRA metadata from a CSV, validates it against the SRAMetadataSchema,
        and returns a validated DataFrame.

        This method is a core component of the iDesign pattern, where data is
        validated at the entry point to the system. This ensures that any data
        passed to downstream services is clean and structured according to the
        SRAMetadataSchema contract.

        Args:
            file_path: The path to the CSV file containing SRA metadata.

        Returns:
            A pandas DataFrame validated against the SRAMetadataSchema.
        """
        df = pd.read_csv(file_path)
        validated_df = SRAMetadataSchema.validate(df)

        return validated_df
