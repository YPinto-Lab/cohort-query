"""READ-ONLY: which SRA attribute keys deserve to become real columns?

The useful SRA metadata -- host, disease, age, body site, isolation source -- is not
in a column. It is inside `attributes` (STRUCT(k,v)[]) and `jattr` (JSON), where an
LLM cannot see it and cannot write a WHERE clause against it. Flattening the keys
that matter into real columns is what makes the SRA side queryable at all.

But SRA attribute keys are unbounded submitter free-text: exploding ALL of them
yields thousands of mostly-null columns, which is worse than the JSON. This measures
which keys are common enough, and low-cardinality enough, to earn a column.

    # gauge the cost on 1% first -- the full pass unnests ~39M rows
    python Scripts/build_mirror/probe_attributes.py --db sra.duckdb --sample 1
    python Scripts/build_mirror/probe_attributes.py --db sra.duckdb

Writes nothing. Opens the database read_only=True.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

TABLE = "metadata_raw"
TOP_KEYS = 80


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--table", default=TABLE)
    parser.add_argument("--sample", type=float, default=None,
                        help="percent of rows to scan (e.g. 1 for a fast estimate)")
    parser.add_argument("--top", type=int, default=TOP_KEYS)
    parser.add_argument("--library-source", default=None,
                        help="restrict to e.g. METAGENOMIC to see the metagenome-only picture")
    args = parser.parse_args()

    con = duckdb.connect(str(args.db), read_only=True)
    probe = AttributeProbe(con, args.table, args.sample, args.library_source)
    probe.scale()
    probe.key_frequency(args.top)
    probe.candidate_columns(args.top)
    con.close()


class AttributeProbe:
    def __init__(self, con: duckdb.DuckDBPyConnection, table: str,
                 sample: float | None, library_source: str | None):
        self._con = con
        self._table = table
        self._sample = sample
        self._library_source = library_source

    def _from(self) -> str:
        source = f'"{self._table}"'
        if self._sample is not None:
            source += f" TABLESAMPLE {self._sample} PERCENT"
        if self._library_source is not None:
            source += f" WHERE librarysource = '{self._library_source}'"
        return source

    def scale(self) -> None:
        _heading("SCALE")
        total = self._con.execute(f'SELECT count(*) FROM "{self._table}"').fetchone()[0]
        print(f"  {self._table}: {total:,} rows")
        if self._sample is not None:
            print(f"  scanning a {self._sample}% sample -- counts below are of the SAMPLE")
        if self._library_source is not None:
            restricted = self._con.execute(
                f'SELECT count(*) FROM "{self._table}" '
                f"WHERE librarysource = '{self._library_source}'").fetchone()[0]
            print(f"  librarysource = {self._library_source}: {restricted:,} rows "
                  f"({restricted / total * 100:.2f}% of all SRA)")

    def key_frequency(self, top: int) -> None:
        """How often does each attribute key appear? Rare keys do not earn a column."""
        _heading(f"ATTRIBUTE KEYS BY FREQUENCY  (top {top})")
        rows = self._con.execute(f"""
            SELECT attribute.k AS key, count(*) AS runs
            FROM {self._from()}, unnest(attributes) AS t(attribute)
            GROUP BY 1 ORDER BY 2 DESC LIMIT {top}
        """).fetchall()
        for key, runs in rows:
            print(f"  {key:44} {runs:>14,}")

    def candidate_columns(self, top: int) -> None:
        """A key earns a column when it is common AND its values are a usable vocabulary.

        High distinct counts are not disqualifying on their own -- isolation_source is
        free text but still worth a column. What the report is for is deciding which,
        with the numbers visible instead of guessed.
        """
        _heading(f"CANDIDATE COLUMNS  (top {top} keys, with value cardinality)")
        print(f"  {'key':44} {'runs':>12} {'~distinct values':>18}   sample values")
        rows = self._con.execute(f"""
            SELECT attribute.k AS key,
                   count(*) AS runs,
                   approx_count_distinct(attribute.v) AS distinct_values,
                   min(attribute.v) AS lo,
                   max(attribute.v) AS hi
            FROM {self._from()}, unnest(attributes) AS t(attribute)
            GROUP BY 1 ORDER BY 2 DESC LIMIT {top}
        """).fetchall()
        for key, runs, distinct, lo, hi in rows:
            print(f"  {key:44} {runs:>12,} {distinct:>18,}   {_short(lo)} … {_short(hi)}")
        print("\n  -> propose a column for keys that are frequent and semantically useful")
        print("     (host, disease, age, body site, isolation source, env_*).")
        print("     Keep `jattr` in the table for the long tail: columns are an ADDITION.")


def _short(value, limit: int = 28) -> str:
    text = str(value).replace("\n", " ")
    return text if len(text) <= limit else text[:limit] + "…"


def _heading(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


if __name__ == "__main__":
    main()
