from __future__ import annotations

import pandas as pd

MISSING_MARKERS = ("nan", "none")


def populated_mask(series: pd.Series) -> pd.Series:
    text = series.astype(str).str.strip()
    return series.notna() & (text != "") & (~text.str.lower().isin(list(MISSING_MARKERS)))
