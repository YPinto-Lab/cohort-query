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

from common.contracts.sra_schema import SRAMetadataSchema

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
        # Read the data from the CSV file
        df = pd.read_csv(file_path)

        # --- Data Cleaning Step ---
        # The 'insertsize' column may contain non-numeric values.
        # We'll convert it to a numeric type, coercing errors to NaN (Not a Number).
        # Then, we fill any NaN values with 0 and cast the column to an integer type.
        # This makes the data cleaning robust before validation.
        df['insertsize'] = pd.to_numeric(df['insertsize'], errors='coerce').fillna(0).astype(int)

        # No column renaming is necessary if the CSV columns match the schema.
        # If they were different, we would rename them here.
        # For example:
        # df = df.rename(columns={"old_name": "new_name"})

        # Validate the DataFrame against the schema
        validated_df = SRAMetadataSchema.validate(df)

        return validated_df
