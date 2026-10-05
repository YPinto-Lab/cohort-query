"""The mirror's schema, rendered for a prompt: columns, types, and REAL values.

Columns alone are not enough. Nothing in a column list tells a model that IBD is
written in this data as whatever literal occupies `subject_disease_status`, so given
only names it invents a plausible spelling and the query returns zero rows -- which
looks like an empty cohort, not a bug. Shipping the vocabularies is the standard
text-to-SQL fix (schema linking + value retrieval), not an invention. HLD F.1.
"""
from __future__ import annotations

import json

import pandas as pd

from cohortquery.ports import Database
from cohortquery.sources import Source, metadata_sources

_ARRAY_HINT = ("  -- ARRAY: exact -> list_contains(col, 'v'); "
               "pattern -> array_to_string(col, ' ') ILIKE '%v%'. "
               "Plain = AND plain ILIKE both raise a Binder Error.")


class SchemaCatalog:
    """Reads the `schema_catalog` table the ETL wrote into the mirror.

    Built at ETL time rather than here: a runtime SELECT DISTINCT across 108 Metalog
    columns on every connect is the rejected alternative, and the cardinality cutoff can
    be re-tuned in seconds against the eval set instead of hours.
    """

    def __init__(self, database: Database):
        self._database = database

    def all(self) -> str:
        """Every METADATA source, in one block. The profile tables are deliberately
        absent -- the LLM never writes their SQL (HLD E.2)."""
        return "\n\n".join(self._render(source) for source in metadata_sources())

    def _render(self, source: Source) -> str:
        table = source.spec().table
        rows = self._database.query(
            "SELECT column_name, data_type, distinct_count, truncated, values_json "
            "FROM schema_catalog WHERE table_name = ? ORDER BY column_name", [table])
        lines = [f"TABLE {table}   (source: {source.name})"]
        lines.extend(_column_line(row) for _, row in rows.iterrows())
        return "\n".join(lines)


def _column_line(row: pd.Series) -> str:
    line = f"  {row['column_name']}  {row['data_type']}"
    if str(row["data_type"]).endswith("[]"):
        line += _ARRAY_HINT
    return line + _values_suffix(row)


def _values_suffix(row: pd.Series) -> str:
    """Values are rendered RAW. A vocabulary that quietly strips the whitespace out of
    '\\n\\t\\t\\t\\tWGS\\n\\t\\t\\t' teaches the model a literal that is not in the data."""
    values_json = row["values_json"]
    if pd.isna(values_json):
        return ""
    values = json.dumps(json.loads(values_json), ensure_ascii=False)
    if bool(row["truncated"]):
        return (f"\n      {row['distinct_count']} distinct values, showing the most common."
                f" {_predicate_advice(row['data_type'])} Sample: {values}")
    return f"\n      values: {values}"


def _predicate_advice(data_type: str) -> str:
    """DuckDB's ILIKE binds VARCHAR only -- `age_years ILIKE '%18%'` against a DOUBLE
    column raises BinderException. A truncated numeric or date/time column needs a
    range predicate instead; the sample values still show the unit and scale."""
    if _is_text_type(data_type):
        return "Prefer ILIKE '%pattern%' over =."
    return "Prefer a range predicate (>=, <=, BETWEEN) over =."


def _is_text_type(data_type: str) -> bool:
    return str(data_type).startswith("VARCHAR")
