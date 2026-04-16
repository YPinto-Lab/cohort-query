"""Pure ENVO metadata resolution logic."""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Callable, Dict, List, Set

import pandas as pd


ENVO_PATTERN = re.compile(r"\bENVO:\d{7,}\b", re.IGNORECASE)


@dataclass
class EnvoResolutionResult:
    enriched_df: pd.DataFrame
    report_df: pd.DataFrame
    envo_cache: Dict[str, Dict[str, str]]
    found_ids: Set[str]
    used_columns: List[str]


def resolve_envo_columns(
    metadata_df: pd.DataFrame,
    envo_cache: Dict[str, Dict[str, str]],
    candidate_columns: List[str],
    fetch_term: Callable[[str], Dict[str, str]],
) -> EnvoResolutionResult:
    """Resolve ENVO IDs in metadata columns and add label/definition columns."""
    enriched = metadata_df.copy()

    found_ids: Set[str] = set()
    used_columns: List[str] = []

    for col in candidate_columns:
        if col not in enriched.columns:
            continue

        values = enriched[col].dropna().astype(str)
        ids = sorted({match.group(0).upper() for value in values for match in ENVO_PATTERN.finditer(value)})
        if not ids:
            continue

        used_columns.append(col)
        found_ids.update(ids)

        label_map: Dict[str, str] = {}
        definition_map: Dict[str, str] = {}

        for term in ids:
            if term not in envo_cache:
                envo_cache[term] = fetch_term(term)
            label_map[term] = envo_cache[term].get("label", term)
            definition_map[term] = envo_cache[term].get("definition", "")

        normalized_col = enriched[col].astype(str).str.upper()
        enriched[f"{col}_label"] = normalized_col.map(label_map).where(normalized_col.isin(label_map), enriched[col])
        enriched[f"{col}_definition"] = normalized_col.map(definition_map).fillna("")

    if not found_ids:
        report_df = pd.DataFrame(columns=["envo_id", "label", "definition", "source"])
        return EnvoResolutionResult(
            enriched_df=enriched,
            report_df=report_df,
            envo_cache=envo_cache,
            found_ids=found_ids,
            used_columns=used_columns,
        )

    rows = []
    for term in sorted(found_ids):
        item = envo_cache.get(term, {})
        rows.append(
            {
                "envo_id": term,
                "label": item.get("label", term),
                "definition": item.get("definition", ""),
                "source": item.get("source", "cache"),
            }
        )
    report_df = pd.DataFrame(rows)

    return EnvoResolutionResult(
        enriched_df=enriched,
        report_df=report_df,
        envo_cache=envo_cache,
        found_ids=found_ids,
        used_columns=used_columns,
    )
