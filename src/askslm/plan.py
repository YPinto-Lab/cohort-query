"""The reviewable, re-runnable artifact. ask() builds it; run() materializes it.

One LLM hop lives on the ask edge. Every run() after it is LLM-free, so one plan
materializes many bioms -- a different family, a different metadata winner --
without re-asking anything.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Sequence

import biom

from askslm import runtime
from askslm.build import BuildReport, Materialization
from askslm.sources import Source
from askslm.translation import ResearchQuestion, Translation


class TranslationError(RuntimeError):
    pass


@dataclass(frozen=True)
class CohortPreview:
    """The show-your-work numbers. Ints only, so a persisted plan stays small."""
    by_metadata_source: dict[Source, int] = field(default_factory=dict)
    shared: int = 0
    union: int = 0
    by_profile_source: dict[Source, int] = field(default_factory=dict)

    def __str__(self) -> str:
        lines = [f"Cohort  {self.union} biosamples  ({self.shared} shared)"]
        lines += [f"    {source.name:26} {count}"
                  for source, count in self.by_profile_source.items()]
        return "\n".join(lines)


@dataclass(frozen=True)
class Plan:
    question: ResearchQuestion
    translation: Translation
    preview: CohortPreview
    error: str | None = None

    def run(self, profile_sources: Source | Sequence[Source],
            out: Path | None = None,
            metadata_winning_source: Source = Source.METALOG_METADATA
            ) -> tuple[biom.Table, BuildReport]:
        self._guard_runnable()
        request = Materialization(profile_sources=_as_tuple(profile_sources),
                                  metadata_winning_source=metadata_winning_source)
        return runtime.cohort_builder().build(self.translation.queries, request, out)

    def _guard_runnable(self) -> None:
        if self.error is not None:
            raise TranslationError(self.error)

    def __str__(self) -> str:
        return f'Plan · "{self.question.text}"\n{self.translation.interpretation}\n{self.preview}'


def _as_tuple(profile_sources: Source | Sequence[Source]) -> tuple[Source, ...]:
    if isinstance(profile_sources, Source):
        return (profile_sources,)
    return tuple(profile_sources)
