from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class TaxaSelector:
    rank: str
    names: tuple[str, ...]


@dataclass(frozen=True)
class SampleSelector:
    column: str
    values: tuple[str, ...]


@dataclass(frozen=True)
class FilterCriteria:
    taxa: TaxaSelector | None = None
    samples: SampleSelector | None = None
    sample_filters: tuple[SampleSelector, ...] = ()
