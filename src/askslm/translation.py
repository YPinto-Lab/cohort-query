"""Question -> one SQL per METADATA source.

The LLM writes metadata queries only -- two today. Every profile-side query is
mechanical and generated in code, parameterised by the cohort (HLD E.2).
"""
from __future__ import annotations

from dataclasses import dataclass

from askslm.attributes import render as render_attributes
from askslm.concept_search import ConceptIndex, render_values as render_concept_values
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

    Invalid SQL is NOT caught here: it surfaces when CohortDiscovery runs the
    queries (HLD H.1), where DuckDB's own error is caught and turned into
    Plan.error. A Translation may also come back carrying `failure` -- the model
    saying it could not translate at all -- which reaches the user as Plan.error
    too, but that is a separate condition raised earlier, on the ask() side.
    """

    def __init__(self, backend: LlmBackend, catalog, attributes,
                concepts: ConceptIndex | None = None):
        self._backend = backend
        self._catalog = catalog
        self._attributes = attributes
        self._concepts = concepts

    def translate(self, question: ResearchQuestion) -> Translation:
        return self._backend.translate(
            TranslationPrompt(question=question, schemas=self._schemas(question)))

    def _schemas(self, question: ResearchQuestion) -> str:
        blocks = [self._catalog.all(),
                  render_attributes(self._attributes.matching(question.text)),
                  self._concept_values_block(question)]
        return "\n\n".join(block for block in blocks if block)

    def _concept_values_block(self, question: ResearchQuestion) -> str:
        if self._concepts is None:
            return ""
        return render_concept_values(self._concepts.matching_values(question.text))
