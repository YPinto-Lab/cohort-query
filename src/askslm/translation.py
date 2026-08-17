"""Question -> one SQL per METADATA source.

The LLM writes metadata queries only -- two today. Every profile-side query is
mechanical and generated in code, parameterised by the cohort (HLD E.2).
"""
from __future__ import annotations

from dataclasses import dataclass

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
