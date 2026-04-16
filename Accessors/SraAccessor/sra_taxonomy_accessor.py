"""
Accessor for the taxonomy source file (taxonomy.csv).

Reads and validates a single CSV file where each row represents one taxon
detected in one SRA accession run. Many rows per acc.

Note: This is distinct from TaxonomyAccessor (in Accessors/TaxonomyAccessor/),
which builds an in-memory lineage database from an existing DataFrame.
This accessor is only responsible for reading and validating the raw file.
"""
import pandas as pd
from pathlib import Path

from Common.contracts.sra_schema import SRATaxonomySchema


class SRATaxonomyAccessor:
    """
    Reads taxonomy.csv and validates it against SRATaxonomySchema.
    Returns a clean DataFrame with many rows per acc (one per detected taxon).
    """

    @staticmethod
    def get(path: Path) -> pd.DataFrame:
        """
        Args:
            path: Path to taxonomy.csv.

        Returns:
            Validated DataFrame conforming to SRATaxonomySchema (many rows per acc).
        """
        df = pd.read_csv(path)
        return SRATaxonomySchema.validate(df)
