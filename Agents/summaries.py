from __future__ import annotations
from typing import Any, Callable
import pandas as pd

from Engines.MetadataEngine.metadata import Metadata
from Engines.TaxonomyEngine.abundance_matrix import AbundanceMatrix
from Engines.TaxonomyEngine.cohort import Cohort
from Common.contracts.taxonomy_results import ResolvedTaxonomy
from Common.contracts.metadata_results import MetadataOverview


def _metadata(md: Metadata) -> dict:
    return {
        "type": "Metadata",
        "n_samples": int(len(md.df)),
        "columns": list(md.df.columns)[:30],
    }


def _abundance_matrix(m: AbundanceMatrix) -> dict:
    return {
        "type": "AbundanceMatrix",
        "shape": list(m.counts.shape),
        "samples_preview": list(m.counts.index[:5]),
        "taxa_preview": list(m.counts.columns[:5]),
    }


def _cohort(c: Cohort) -> dict:
    return {
        "type": "Cohort",
        "n_samples": int(len(c.matrix.counts)),
        "n_taxa": int(c.matrix.counts.shape[1]),
        "metadata_columns": list(c.metadata.df.columns)[:30],
    }


def _resolved_taxonomy(r: ResolvedTaxonomy) -> dict:
    return {
        "type": "ResolvedTaxonomy",
        "input_rows": r.summary.input_rows,
        "rows_updated": r.summary.rows_updated,
    }


def _metadata_overview(o: MetadataOverview) -> dict:
    return {"type": "MetadataOverview", "summary_available": True}


def _dataframe(df: pd.DataFrame) -> dict:
    return {
        "type": "DataFrame",
        "shape": list(df.shape),
        "columns": list(df.columns)[:30],
    }


_SUMMARIZERS: list[tuple[type, Callable[[Any], dict]]] = [
    (Metadata, _metadata),
    (AbundanceMatrix, _abundance_matrix),
    (Cohort, _cohort),
    (ResolvedTaxonomy, _resolved_taxonomy),
    (MetadataOverview, _metadata_overview),
    (pd.DataFrame, _dataframe),
]


def summarize_object(obj: Any) -> dict:
    for typ, fn in _SUMMARIZERS:
        if isinstance(obj, typ):
            return fn(obj)
    return {"type": "object", "repr": repr(obj)[:200]}
