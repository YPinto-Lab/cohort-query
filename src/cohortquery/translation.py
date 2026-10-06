"""Question -> one SourceQuery per METADATA source.

The LLM writes metadata queries only -- two today. Every profile-side query is
mechanical and generated in code, parameterised by the cohort (HLD E.2).

jattr-touching criteria are no longer SQL the LLM writes: it states them as
English concepts (JattrCriterion), and CriterionResolver dispatches each one to
a nearest-neighbor lookup against attribute_keys_index/attribute_values_index at
cohort-discovery time. This means the LLM never needs to be shown candidate
jattr key names to pick from -- the concept it states IS the query.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Literal

from cohortquery.concept_search import ConceptIndex, render_values as render_concept_values
from cohortquery.ports import LlmBackend
from cohortquery.sources import Source


@dataclass(frozen=True)
class ResearchQuestion:
    text: str                              # the whole question; source-agnostic


@dataclass(frozen=True)
class JattrCriterion:
    concept: str                           # e.g. "IBD diagnosis", "calprotectin measurement"


@dataclass(frozen=True)
class SourceQuery:
    source: Source                                     # always a METADATA source
    sql: str | None                                     # bucket 1/2's native-column SQL
    jattr_criteria: tuple[JattrCriterion, ...] = ()     # bucket 2/3's jattr-touching criteria
    jattr_combinator: Literal["all", "any"] = "any"     # how jattr_criteria combine with EACH OTHER
    # how sql's result combines with jattr_criteria's combined result:
    # "union" -- bucket 2, the same fact recorded twice (e.g. collection_date_sam
    #   sometimes only in jattr) -- a sample either channel recognizes counts.
    # "intersect" -- sql and jattr_criteria are genuinely distinct, simultaneous
    #   requirements (e.g. native "fecal metagenomic" AND jattr "IBD diagnosis")
    #   that must all hold on the same sample.
    sql_jattr_combinator: Literal["union", "intersect"] = "union"


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

    Invalid SQL is NOT caught here: it surfaces when CriterionResolver runs the
    queries (HLD H.1), where DuckDB's own error is caught and turned into
    Plan.error. A Translation may also come back carrying `failure` -- the model
    saying it could not translate at all -- which reaches the user as Plan.error
    too, but that is a separate condition raised earlier, on the ask() side.
    """

    def __init__(self, backend: LlmBackend, catalog, concepts: ConceptIndex | None = None):
        self._backend = backend
        self._catalog = catalog
        self._concepts = concepts

    def translate(self, question: ResearchQuestion) -> Translation:
        return self._backend.translate(
            TranslationPrompt(question=question, schemas=self._schemas(question)))

    def _schemas(self, question: ResearchQuestion) -> str:
        blocks = [self._catalog.all(), self._concept_values_block(question)]
        return "\n\n".join(block for block in blocks if block)

    def _concept_values_block(self, question: ResearchQuestion) -> str:
        if self._concepts is None:
            return ""
        return render_concept_values(self._concepts.matching_values(question.text))
