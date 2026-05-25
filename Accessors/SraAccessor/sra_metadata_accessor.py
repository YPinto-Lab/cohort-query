"""
Accessor for the metadata source file (metadata.csv).

Reads and validates a single CSV file where each row represents one SRA accession.
No taxonomy columns — only run/sample/bioproject metadata fields.
"""
import pandas as pd
from pathlib import Path

from Common.contracts.sra_schema import SRAMetadataSchema


class SRAMetadataAccessor:
    """
    Reads metadata.csv and validates it against SRAMetadataSchema.
    Returns a clean DataFrame with 1 row per acc.
    """

    @staticmethod
    def get(path: Path) -> pd.DataFrame:
        """
        Args:
            path: Path to metadata.csv.

        Returns:
            Validated DataFrame conforming to SRAMetadataSchema (1 row per acc).
        """
        df = pd.read_csv(path)

        return SRAMetadataSchema.validate(df)
