"""Retrieve the handful of jattr keys a question is actually about.

Schema linking is supposed to hand the model the RELEVANT schema, not all of it. There
are ~35,768 attribute keys; naming them all would cost more than the entire rest of the
prompt and bury the one that matters. So the question selects them.
"""
from __future__ import annotations

import json

from askslm.ports import Database

MIN_TERM = 5           # "with", "and", "the" match half the index and teach nothing
MAX_KEYS = 25           # a question about one phenotype should not import a hundred


class AttributeIndex:
    """Looks up `attribute_keys`, the ETL-built census of every jattr key."""

    def __init__(self, database: Database):
        self._database = database

    def matching(self, question: str) -> dict[str, tuple[int, str | None]]:
        """key -> (occurrences, samples_json), for keys a term of the question names."""
        terms = _terms(question)
        if not terms:
            return {}
        patterns = [f"%{term}%" for term in terms]
        rows = self._database.query(
            "SELECT key, occurrences, samples_json FROM attribute_keys "
            "WHERE list_bool_or(list_transform(?::VARCHAR[], "
            "                   x -> lower(key) LIKE x)) "
            "ORDER BY occurrences DESC LIMIT ?", [patterns, MAX_KEYS])
        return {row.key: (row.occurrences, row.samples_json)
                for row in rows.itertuples(index=False)}


def _terms(question: str) -> list[str]:
    words = "".join(character if character.isalnum() else " "
                    for character in question.lower()).split()
    return sorted({word for word in words if len(word) >= MIN_TERM})


def render(matches: dict[str, tuple[int, str | None]]) -> str:
    """The prompt block. Empty when nothing matched -- silence is correct, an empty
    heading would imply the model should have used something."""
    if not matches:
        return ""
    lines = ["SRA PER-SAMPLE ATTRIBUTES matching this question",
             "  These live in the sra_metadata.jattr JSON column, not as real columns.",
             "  Read one with json_extract_string(jattr, '$.<key>').",
             "  Values are STRINGS -- wrap numbers in TRY_CAST(... AS DOUBLE)."]
    for key, (occurrences, samples) in matches.items():
        shown = f"  e.g. {json.loads(samples)}" if samples else ""
        lines.append(f"  {key}   ({occurrences} runs){shown}")
    return "\n".join(lines)
