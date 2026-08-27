"""Retrieval for the cases substring search structurally cannot reach: a question's
wording sharing no characters with the field or value that means the same thing.

"IBD" (3 chars) is dropped by attributes.py's MIN_TERM floor before substring search
even runs, and even found, it shares no substring with ibd_sam or "Crohn's disease".
Embedding search finds these by meaning: vectors for the field names and low-cardinality
column values are computed once at mirror-build time
(Scripts/build_mirror/build_concept_embeddings.py); this module embeds the question and
does nearest-neighbor lookup against them. See the design doc for what was measured.
"""
from __future__ import annotations

from typing import Protocol

import pandas as pd

from askslm.ports import Database


class Embedder(Protocol):
    def embed(self, terms: list[str]) -> list[list[float]]:
        ...

EMBED_DIM = 768          # native output width of LocalEmbedder's model
                          # (cambridgeltl/SapBERT-from-PubMedBERT-fulltext, see
                          # adapters.py) -- build-time and query-time MUST use the
                          # same model and this same width, or a query vector of the
                          # wrong shape is a DuckDB error (or worse, silently wrong).

TOP_K_KEYS = 5              # nearest keys per question term
TOP_K_VALUES = 2            # nearest values per question term -- kept tight because this
                             # is a plain top-N with no distance cutoff (see module notes
                             # below): a wide K would let an unrelated value ride in on a
                             # question with few true semantic neighbors. Revisit once a
                             # real embedding corpus exists to calibrate a distance
                             # threshold instead of a fixed count.

MIN_TERM = 3                # floor is 2 chars lower than attributes.py's MIN_TERM=5 --
                             # this is the mechanism that exists specifically to reach
                             # short acronyms (IBD, TB, UC) substring search drops.


class ConceptIndex:
    """Question -> candidate keys and candidate values, by embedding similarity.

    Two Database ports because the two embedding tables are unrelated shapes (one
    keyed by jattr key, one keyed by table.column.value) -- matches the "each
    accessor reads one source" convention the rest of the package follows. Both are
    typically the SAME underlying DuckDbConnection at the composition root; they are
    separate constructor arguments so a test can fake either independently.
    """

    def __init__(self, key_embeddings: Database, value_embeddings: Database, embedder: Embedder):
        self._key_embeddings = key_embeddings
        self._value_embeddings = value_embeddings
        self._embedder = embedder
        self._cached_question: str | None = None
        self._cached_term_vectors: list[tuple[str, list[float]]] = []

    def matching_keys(self, question: str) -> dict[str, tuple[int, str | None]]:
        """key -> (occurrences, samples_json), same shape as AttributeIndex.matching()
        so the two can be unioned before the MAX_KEYS budget is applied."""
        found: dict[str, tuple[int, str | None]] = {}
        for term, vector in self._term_vectors(question):
            for row in self._nearest_keys(vector=vector).itertuples(index=False):
                found.setdefault(row.key, (row.occurrences, row.samples_json))
        return found

    def matching_values(self, question: str) -> dict[str, list[str]]:
        """Maps "table.column" -> matched values, in nearest-first order, de-duplicated."""
        found: dict[str, list[str]] = {}
        for term, vector in self._term_vectors(question):
            for row in self._nearest_values(vector=vector).itertuples(index=False):
                _add_value(found=found, row=row)
        return found

    def _term_vectors(self, question: str) -> list[tuple[str, list[float]]]:
        """One embed() call for every term at once -- the "one live call per ask()"
        the design commits to. Cached by question so matching_keys() and
        matching_values() called with the same question (as ask() does) don't
        double the embedding calls."""
        if question == self._cached_question:
            return self._cached_term_vectors
        self._cached_question = question
        self._cached_term_vectors = self._compute_term_vectors(question)
        return self._cached_term_vectors

    def _compute_term_vectors(self, question: str) -> list[tuple[str, list[float]]]:
        terms = _terms(question)
        if not terms:
            return []
        vectors = self._embedder.embed(terms)
        if not vectors:
            return []
        return list(zip(terms, vectors))

    def _nearest_keys(self, vector: list[float]) -> pd.DataFrame:
        return self._key_embeddings.query(
            "SELECT k.key, k.occurrences, k.samples_json "
            "FROM attribute_key_embeddings e JOIN attribute_keys k USING (key) "
            f"ORDER BY array_cosine_distance(e.vector, ?::FLOAT[{EMBED_DIM}]) LIMIT ?",
            [vector, TOP_K_KEYS])

    def _nearest_values(self, vector: list[float]) -> pd.DataFrame:
        return self._value_embeddings.query(
            "SELECT table_name, column_name, value FROM column_value_embeddings "
            f"ORDER BY array_cosine_distance(vector, ?::FLOAT[{EMBED_DIM}]) LIMIT ?",
            [vector, TOP_K_VALUES])


def _add_value(found: dict[str, list[str]], row) -> None:
    key = f"{row.table_name}.{row.column_name}"
    values = found.setdefault(key, [])
    if row.value not in values:
        values.append(row.value)


def _terms(question: str) -> list[str]:
    """General concept-embedding search, not acronym-only: "shotgun"/"mgx" matching
    librarysource = 'METAGENOMIC' is an ordinary lowercase word with the same
    zero-shared-characters problem as "IBD" finding ibd_sam. MIN_TERM is 2 lower
    than attributes.py's floor of 5 so short acronyms (IBD, TB, UC) still clear it."""
    words = "".join(character if character.isalnum() else " "
                    for character in question).split()
    return sorted({word for word in words if len(word) >= MIN_TERM})


def render_values(matches: dict[str, list[str]]) -> str:
    """The prompt block for value-level concept matches. Empty when nothing matched,
    same convention as attributes.py's render()."""
    if not matches:
        return ""
    lines = ["CONCEPT MATCHES (values found by meaning, not literal wording)",
             "  These are REAL values of the named column -- OR them together with =",
             "  when the question names the broader concept they all belong to."]
    for column, values in matches.items():
        quoted = ", ".join(f'"{value}"' for value in values)
        lines.append(f"  {column}: {quoted}")
    return "\n".join(lines)
