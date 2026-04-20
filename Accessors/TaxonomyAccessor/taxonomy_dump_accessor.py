"""Accessors for taxonomy dump resources such as NCBI ``merged.dmp``."""

from __future__ import annotations

from pathlib import Path
from typing import Dict


class TaxonomyDumpAccessor:
    """Loader for NCBI ``merged.dmp`` mapping files.

    The expected format per line is:
        old_taxid\t|\tnew_taxid\t|
    """

    def __init__(self, merged_dump_path: Path):
        self._merged_dump_path = Path(merged_dump_path)

    @property
    def merged_dump_path(self) -> Path:
        """Return the source path used by this accessor."""
        return self._merged_dump_path

    def load_merged_taxid_map(self) -> Dict[int, int]:
        """Parse ``merged.dmp`` into an ``old_taxid -> new_taxid`` dictionary."""
        merged_map: Dict[int, int] = {}

        with self._merged_dump_path.open("r", encoding="utf-8") as handle:
            for line in handle:
                stripped = line.strip()
                if not stripped:
                    continue

                parts = stripped.split("\t|\t")
                if len(parts) < 2:
                    continue

                old_taxid_raw = parts[0].strip()
                new_taxid_raw = parts[1].replace("\t|", "").strip()

                try:
                    old_taxid = int(old_taxid_raw)
                    new_taxid = int(new_taxid_raw)
                except ValueError:
                    continue

                merged_map[old_taxid] = new_taxid

        return merged_map
