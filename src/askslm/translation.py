"""Question -> one SQL per METADATA source.

The LLM writes metadata queries only -- two today. Every profile-side query is
mechanical and generated in code, parameterised by the cohort (HLD E.2).
"""
from __future__ import annotations

from dataclasses import dataclass

from askslm.ports import LlmBackend
from askslm.sources import Source


@dataclass(frozen=True)
class ResearchQuestion:
    text: str                              # the whole question; source-agnostic


@dataclass(frozen=True)
class SourceQuery:
    source: Source                         # always a METADATA source
    sql: str


@dataclass(frozen=True)
class TranslationPrompt:
    question: ResearchQuestion
    schemas: str                           # columns AND value vocabularies, from SchemaCatalog


@dataclass(frozen=True)
class Translation:
    """LlmBackend output, before any DB hit."""
    interpretation: str                    # the English restatement shown as show-your-work
    queries: tuple[SourceQuery, ...]       # one per METADATA source
    failure: str | None = None             # the model could not translate; a sentence, not a trace


class Translator:
    """Question + schemas -> Translation. The one network step, kept pure.

    Invalid SQL is NOT caught here: it surfaces when CohortPreviewBuilder runs the
    counts (HLD F.3). A Translation may come back carrying `failure` -- the model
    saying it could not translate at all -- which reaches the user as Plan.error.
    """

    def __init__(self, backend: LlmBackend, catalog):
        self._backend = backend
        self._catalog = catalog

    def translate(self, question: ResearchQuestion) -> Translation:
        return self._backend.translate(
            TranslationPrompt(question=question, schemas=self._catalog.all()))
