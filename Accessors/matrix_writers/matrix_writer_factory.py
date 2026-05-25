from __future__ import annotations

from .matrix_format_writer import MatrixFormatWriter
from .counts_writer import CountsWriter
from .relative_writer import RelativeWriter
from .maaslin_writer import MaaslinWriter
from .biom_writer import BiomWriter


class MatrixWriterFactory:
    """Returns the MatrixFormatWriter for a requested format."""

    _WRITERS = {
        "counts": CountsWriter,
        "relative": RelativeWriter,
        "maaslin": MaaslinWriter,
        "biom": BiomWriter,
    }

    def create(self, fmt: str) -> MatrixFormatWriter:
        writer_type = self._WRITERS.get(fmt)
        if writer_type is None:
            raise ValueError(f"Unknown matrix format: {fmt}")
        return writer_type()
