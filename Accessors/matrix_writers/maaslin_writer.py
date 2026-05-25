from __future__ import annotations

from pathlib import Path


class MaaslinWriter:
    def write(self, matrix, path: Path) -> Path:
        long_df = matrix.counts.reset_index().melt(
            id_vars=[matrix.counts.index.name or "index"], var_name="taxon_key", value_name="value"
        )
        long_df.to_csv(path, sep="\t", index=False)
        return path
