"""Add a `schema_catalog` table to an existing mirror: columns + value vocabularies.

Separate from step3_assemble_mirror.py on purpose. This reads an already-built mirror and
adds one table -- it needs no raw TSVs, so it runs in seconds rather than hours,
and the cardinality cutoff can be re-tuned against the translation eval set
without rebuilding anything.

Why it exists (HLD F.1): the LLM cannot know that "IBD" is written in this data as
whatever literal strings occupy `subject_disease_status`. Given only column names it
invents plausible values and the query returns zero rows -- which reads as an empty
cohort, not a bug. So the prompt ships the real values for every low-cardinality
column.

METADATA tables only: the LLM writes one query per METADATA source and never touches
the profile tables (HLD E.2). That is also what keeps this cheap -- the profile
tables are the big ones.

    python Scripts/build_mirror/steps/step5_catalog_schema.py --db cohortquery_mirror.duckdb
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import duckdb

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[3] / "src"))
from cohortquery.adapters import attach_sidecars          # noqa: E402


METADATA_TABLES = ("sra_metadata", "metalog_metadata")
DEFAULT_MAX_DISTINCT = 200

# Two budgets, both added after MEASURING the real prompt at ~138,000 tokens per ask()
# (2026-08-18). Schema linking exists to NARROW what the model sees; a prompt that size
# does the opposite, and 41% of it was columns that teach the model nothing.
#
# IDENTIFIER_RATIO -- a column whose distinct count approaches its row count is a KEY or
# free text, not a vocabulary. `jattr` had 39,065,549 distinct values in 39,100,115 rows
# and shipped 119,263 chars, 21% of the whole prompt, to say nothing at all. Worse, it
# carried a "Prefer ILIKE" hint, which invites `biosample ILIKE '%SAMN%'`.
#
# MAX_VALUE_CHARS -- a per-column cap, because cardinality alone does not bound size:
# 200 long free-text values are as expensive as 20,000 short ones.
DEFAULT_IDENTIFIER_RATIO = 0.4
DEFAULT_MAX_VALUE_CHARS = 1200

# Below this the ratio is noise, not evidence: in a 20-row table a perfectly good
# 14-value vocabulary looks exactly like a primary key. The real tables are 39,100,115
# and 157,483 rows, so this only ever exempts fixtures and toy mirrors.
MIN_ROWS_FOR_RATIO = 10_000


class SchemaCatalogBuilder:
    """Writes one row per column of every metadata table, with values when few enough."""

    def __init__(self, db_path: Path, max_distinct: int = DEFAULT_MAX_DISTINCT,
                 identifier_ratio: float = DEFAULT_IDENTIFIER_RATIO,
                 max_value_chars: int = DEFAULT_MAX_VALUE_CHARS):
        self.db_path = db_path
        self.max_distinct = max_distinct
        self.identifier_ratio = identifier_ratio
        self.max_value_chars = max_value_chars

    def build(self) -> None:
        con = duckdb.connect(str(self.db_path))
        attach_sidecars(con)
        self._create_table(con)
        for table in METADATA_TABLES:
            self._catalog_table(con, table)
        self._report(con)
        con.close()

    def _create_table(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("DROP TABLE IF EXISTS schema_catalog")
        con.execute("""
            CREATE TABLE schema_catalog (
                table_name TEXT,
                column_name TEXT,
                data_type TEXT,           -- VARCHAR[] means list_contains(), not =
                distinct_count BIGINT,
                truncated BOOLEAN,        -- true: values_json is the top-N, not the whole set
                values_json TEXT          -- JSON array of the REAL values, never cleaned
            )
        """)

    def _catalog_table(self, con: duckdb.DuckDBPyConnection, table: str) -> None:
        rows = con.execute(f"SELECT count(*) FROM {table}").fetchone()[0]
        for column, data_type in self._columns(con, table):
            distinct_count = self._distinct_count(con, table, column)
            truncated = distinct_count > self.max_distinct
            if self._is_identifier(distinct_count, rows):
                values = None
            else:
                values = self._values(con, table, column, data_type, truncated)
            con.execute(
                "INSERT INTO schema_catalog VALUES (?, ?, ?, ?, ?, ?)",
                [table, column, data_type, distinct_count, truncated, values],
            )

    def _is_identifier(self, distinct_count: int, rows: int) -> bool:
        """A key or free text, not a vocabulary -- ship the column name and type, no values.

        The model still sees the column and can still filter on it; what it loses is a
        list of 200 accessions that taught it nothing and cost a fifth of the prompt.
        """
        if rows < MIN_ROWS_FOR_RATIO:
            return False
        return distinct_count / rows > self.identifier_ratio

    def _columns(self, con: duckdb.DuckDBPyConnection, table: str) -> list[tuple[str, str]]:
        rows = con.execute(f"DESCRIBE {table}").fetchall()
        return [(row[0], row[1]) for row in rows]

    def _distinct_count(self, con: duckdb.DuckDBPyConnection, table: str, column: str) -> int:
        return con.execute(f'SELECT count(DISTINCT "{column}") FROM {table}').fetchone()[0]

    def _values(self, con: duckdb.DuckDBPyConnection, table: str, column: str,
                data_type: str, truncated: bool) -> str | None:
        """Low cardinality ships the COMPLETE set; high cardinality ships the top-N.

        A high-cardinality column used to ship nothing, which left the model guessing at
        `organism` (~247k distinct in real SRA). The top-N plus an explicit `truncated`
        flag is enough: the model is told to prefer ILIKE patterns, and
        `organism ILIKE '%gut metagenome%'` needs no complete enumeration.

        Values are shipped RAW. Real SRA has both 'WGS' and '\\n\\t\\t\\t\\tWGS\\n\\t\\t\\t'
        in assay_type -- cleaning them here would hide that `= 'WGS'` silently drops rows.
        """
        if data_type.endswith("[]"):
            return self._list_values(con, table, column, truncated)
        if truncated:
            rows = con.execute(
                f'SELECT "{column}" FROM {table} WHERE "{column}" IS NOT NULL '
                f'GROUP BY 1 ORDER BY count(*) DESC LIMIT {self.max_distinct}').fetchall()
        else:
            rows = con.execute(
                f'SELECT DISTINCT "{column}" FROM {table} '
                f'WHERE "{column}" IS NOT NULL ORDER BY 1').fetchall()
        return self._within_budget([str(row[0]) for row in rows])

    def _within_budget(self, values: list[str]) -> str:
        """Drop values from the tail until the JSON fits the per-column cap.

        Values are ordered by frequency (or alphabetically when complete), so the tail is
        the least useful. Dropping is silent by design: `truncated` already tells the model
        the list is partial, and that is the only fact it needs to prefer ILIKE over IN.
        """
        while len(values) > 1 and len(json.dumps(values)) > self.max_value_chars:
            values.pop()
        return json.dumps(values)

    def _list_values(self, con: duckdb.DuckDBPyConnection, table: str,
                     column: str, truncated: bool) -> str:
        """An array column's vocabulary is its ELEMENTS, not its distinct arrays.

        geo_loc_name_sam is VARCHAR[]; the useful values are the countries inside it,
        and the predicate is list_contains(geo_loc_name_sam, 'Israel').
        """
        rows = con.execute(
            f'SELECT element FROM {table}, unnest("{column}") AS t(element) '
            f'WHERE element IS NOT NULL GROUP BY 1 ORDER BY count(*) DESC '
            f'LIMIT {self.max_distinct}').fetchall()
        return json.dumps([str(row[0]) for row in rows])

    def _report(self, con: duckdb.DuckDBPyConnection) -> None:
        total, complete, truncated, arrays = con.execute("""
            SELECT count(*),
                   count(*) FILTER (WHERE values_json IS NOT NULL AND NOT truncated),
                   count(*) FILTER (WHERE truncated),
                   count(*) FILTER (WHERE data_type LIKE '%[]')
            FROM schema_catalog
        """).fetchone()
        print(f"schema_catalog: {total} columns · {complete} with a COMPLETE vocabulary · "
              f"{truncated} truncated to the top {self.max_distinct} · {arrays} array-typed")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--max-distinct", type=int, default=DEFAULT_MAX_DISTINCT,
                        help="columns with more distinct values ship the top-N, not all")
    parser.add_argument("--identifier-ratio", type=float, default=DEFAULT_IDENTIFIER_RATIO,
                        help="distinct/rows above this means a key or free text: no values")
    parser.add_argument("--max-value-chars", type=int, default=DEFAULT_MAX_VALUE_CHARS,
                        help="per-column cap on the rendered values")
    args = parser.parse_args()
    SchemaCatalogBuilder(args.db, args.max_distinct,
                         args.identifier_ratio, args.max_value_chars).build()


if __name__ == "__main__":
    main()
