"""The reviewable, re-runnable artifact. ask() builds it; run() materializes it.

One LLM hop lives on the ask edge. Every run() after it is LLM-free, so one plan
materializes many bioms -- a different family, a different metadata winner --
without re-asking anything.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable, Sequence

import biom

from askslm import runtime
from askslm.build import BuildReport, Materialization
from askslm.sources import Source
from askslm.translation import ResearchQuestion, SourceQuery, Translation


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
            metadata_winning_source: Source = Source.METALOG_METADATA,
            on_step: Callable[[str], None] | None = None
            ) -> tuple[biom.Table, BuildReport]:
        self._guard_runnable()
        request = Materialization(profile_sources=_as_tuple(profile_sources),
                                  metadata_winning_source=metadata_winning_source)
        return runtime.cohort_builder().build(self.translation.queries, request, out,
                                              on_step=on_step)

    def _guard_runnable(self) -> None:
        if self.error is not None:
            raise TranslationError(self.error)

    def __str__(self) -> str:
        return f'Plan · "{self.question.text}"\n{self.translation.interpretation}\n{self.preview}'

    def save(self, path: Path) -> Path:
        """Write the plan as JSON. Source enums become their names -- JSON keys are
        strings, and a Source that came back as the string "METALOG_METADATA" would
        silently match nothing."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(_as_json(self), indent=2))
        return path


def load_plan(path: Path) -> Plan:
    """Rebuild a Plan from disk. Never touches LlmBackend -- that is the point: one
    LLM hop lives on the ask edge, and every replay after it is free."""
    return _from_json(json.loads(Path(path).read_text()))


def _as_json(plan: Plan) -> dict:
    return {
        "question": plan.question.text,
        "interpretation": plan.translation.interpretation,
        "queries": [{"source": query.source.name, "sql": query.sql}
                    for query in plan.translation.queries],
        "failure": plan.translation.failure,
        "preview": {
            "by_metadata_source": _named(plan.preview.by_metadata_source),
            "by_profile_source": _named(plan.preview.by_profile_source),
            "shared": plan.preview.shared,
            "union": plan.preview.union,
        },
        "error": plan.error,
    }


def _named(counts: dict) -> dict:
    return {source.name: count for source, count in counts.items()}


def _sourced(counts: dict) -> dict:
    return {Source[name]: count for name, count in counts.items()}


def _from_json(payload: dict) -> Plan:
    preview = payload["preview"]
    return Plan(
        question=ResearchQuestion(payload["question"]),
        translation=Translation(
            interpretation=payload["interpretation"],
            queries=tuple(SourceQuery(Source[entry["source"]], entry["sql"])
                          for entry in payload["queries"]),
            failure=payload["failure"]),
        preview=CohortPreview(
            by_metadata_source=_sourced(preview["by_metadata_source"]),
            by_profile_source=_sourced(preview["by_profile_source"]),
            shared=preview["shared"], union=preview["union"]),
        error=payload["error"])


def _as_tuple(profile_sources: Source | Sequence[Source]) -> tuple[Source, ...]:
    if isinstance(profile_sources, Source):
        return (profile_sources,)
    return tuple(profile_sources)
