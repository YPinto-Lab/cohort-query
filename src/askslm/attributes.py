"""Retrieve the handful of jattr keys a question is actually about.

Schema linking is supposed to hand the model the RELEVANT schema, not all of it. There
are ~35,768 attribute keys; naming them all would cost more than the entire rest of the
prompt and bury the one that matters. So the question selects them.
"""
from __future__ import annotations

import json

import pandas as pd

from askslm.ports import Database

MIN_TERM = 5           # "with", "and", "the" match half the index and teach nothing
PER_TERM = 12          # each term gets its OWN slots -- see matching()
MAX_KEYS = 60          # ~1,100 tokens against a ~40,000-token prompt
GENERIC_KEYS = 120     # a term matching more keys than this describes everything


class AttributeIndex:
    """Looks up `attribute_keys`, the ETL-built census of every jattr key."""

    def __init__(self, database: Database, expander=None):
        self._database = database
        self._expander = expander

    def matching(self, question: str) -> dict[str, tuple[int, str | None]]:
        """key -> (occurrences, samples_json), for keys a term of the question names.

        The budget is per TERM, not global, and that is the whole point. Ranking every
        match together by frequency lets a broad term evict a precise one: "IBD fecal
        metagenomic with calprotectin" filled all 25 slots with fecal_color2_sam,
        fecal_date_sam, fecal_donor_id_sam ... and dropped fecalcalprotectin_run, the key
        the researcher actually meant. Per-term slots mean a rare exact match cannot be
        crowded out by a common vague one.
        """
        found: dict[str, tuple[int, str | None]] = {}
        for term in self._search_terms(question):
            for key, row in self._for_term(term).items():
                found.setdefault(key, row)
        return dict(sorted(found.items(), key=_by_occurrences)[:MAX_KEYS])

    def _search_terms(self, question: str) -> list[str]:
        """The question's own words, plus whatever the model says a field name for this
        might be called -- `calpro` and `s100a8` for calprotectin, which a substring
        search on the literal word never reaches.

        Generic terms are dropped by MEASUREMENT, not by trusting the instruction not to
        emit them: `dna` matches 698 keys across 1,067,427 runs and would fill the whole
        budget with noise. A term that matches nothing costs nothing, so over-generation
        of SPECIFIC terms is harmless.
        """
        expanded = self._expander.expand(question) if self._expander else []
        candidates = sorted(set(_terms(question)) | set(expanded))
        return [term for term in candidates if not self._is_generic(term)]

    def _is_generic(self, term: str) -> bool:
        matched = self._database.query(
            "SELECT count(*) AS n FROM attribute_keys WHERE lower(key) LIKE ?",
            [f"%{term}%"])
        return int(matched["n"][0]) > GENERIC_KEYS

    def _for_term(self, term: str) -> dict[str, tuple[int, str | None]]:
        rows = self._database.query(
            "SELECT key, occurrences, samples_json FROM attribute_keys "
            "WHERE lower(key) LIKE ? ORDER BY occurrences DESC LIMIT ?",
            [f"%{term}%", PER_TERM])
        return {row.key: (row.occurrences, row.samples_json)
                for row in rows.itertuples(index=False)}


def _by_occurrences(item: tuple[str, tuple[int, str | None]]) -> int:
    """Named, because the house style forbids lambda."""
    return -item[1][0]


def _terms(question: str) -> list[str]:
    words = "".join(character if character.isalnum() else " "
                    for character in question.lower()).split()
    return sorted({word for word in words if len(word) >= MIN_TERM})


def render(matches: dict[str, tuple[int, str | None]]) -> str:
    """The prompt block. Empty when nothing matched -- silence is correct, an empty
    heading would imply the model should have used something.

    `samples` is checked with pd.isna, not truthiness: a NULL from DuckDB arrives as a
    float NaN, and NaN is TRUTHY. 58,196 of the real mirror's 94,450 keys have no sampled
    value, so `if samples` sent NaN into json.loads and crashed on the first real query.
    """
    if not matches:
        return ""
    lines = ["SRA PER-SAMPLE ATTRIBUTES matching this question",
             "  These live in the sra_metadata.jattr JSON column, not as real columns.",
             "  Read one with json_extract_string(jattr, '$.<key>').",
             "  Values are STRINGS -- wrap numbers in TRY_CAST(... AS DOUBLE)."]
    for key, (occurrences, samples) in matches.items():
        shown = "" if pd.isna(samples) else f"  e.g. {json.loads(samples)}"
        lines.append(f"  {key}   ({occurrences} runs){shown}")
    return "\n".join(lines)
