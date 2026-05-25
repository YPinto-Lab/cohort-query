from __future__ import annotations

from dataclasses import dataclass

import pandas as pd


@dataclass(frozen=True)
class ResolutionSummary:
    input_rows: int
    rows_updated: int
    unique_old_tax_ids_updated: int


@dataclass(frozen=True)
class ResolvedTaxonomy:
    df: pd.DataFrame
    changes_df: pd.DataFrame
    summary: ResolutionSummary
