from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable

import pandas as pd

from Common.contracts.selectors import SampleSelector


@dataclass(frozen=True, eq=False)
class Metadata:
    df: pd.DataFrame

    def __post_init__(self) -> None:
        if "acc" not in self.df.columns:
            raise ValueError("Metadata df must contain an 'acc' column")
        if self.df["acc"].duplicated().any():
            raise ValueError("Metadata df has duplicate 'acc' values")

    def reindex_to(self, sample_ids: Iterable[str]) -> Metadata:
        wanted = list(sample_ids)
        indexed = self.df.set_index("acc")
        present = [acc for acc in wanted if acc in indexed.index]
        reordered = indexed.reindex(present).reset_index()
        return Metadata(df=reordered)

    def filter(self, selector: SampleSelector) -> Metadata:
        mask = self.df[selector.column].isin(selector.values)
        kept = self.df[~mask if selector.exclude else mask].reset_index(drop=True)
        return Metadata(df=kept)

    def write(self, path: Path) -> Path:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        self.df.to_csv(path, index=False)
        return path
