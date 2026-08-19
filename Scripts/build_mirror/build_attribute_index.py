"""Index every `jattr` key so a researcher can name a phenotype and have it found.

SRA hides its clinical fields in `jattr`, a JSON blob: 35,768 distinct keys in a
200,000-row sample. Flattening the frequent ones does not help -- they are technical
(`bytes`, `bases`, `primary_search`), while the interesting ones are rare by nature
(`calprotectin_sam` is in 2,342 of 39,100,115 runs). So we index them all and retrieve
per question instead. See the design doc for the measurements.

    python Scripts/build_mirror/build_attribute_index.py --db askslm_mirror.duckdb
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DEFAULT_SAMPLE_ROWS = 200_000
MAX_SAMPLES = 3


class AttributeIndexBuilder:
    """Two passes over sra_metadata.jattr: exact counts, sampled values.

    One pass would be simpler and is not affordable: extracting keys AND values together
    costs 36s per 20k rows (~19 hours for the table), against ~1s per 20k for keys alone
    (~32 min). Counts must be exact because a researcher acts on them; sample values only
    illustrate format, so a sample is honest.
    """

    def __init__(self, db_path: Path, sample_rows: int = DEFAULT_SAMPLE_ROWS):
        self.db_path = db_path
        self.sample_rows = sample_rows

    def build(self) -> None:
        con = duckdb.connect(str(self.db_path))
        con.execute("DROP TABLE IF EXISTS attribute_keys")
        con.execute("""
            CREATE TABLE attribute_keys (
                key TEXT,
                occurrences BIGINT,     -- exact, over every row
                samples_json TEXT       -- a few real values, from a sample
            )
        """)
        self._count_keys(con)
        self._attach_samples(con)
        self._report(con)
        con.close()

    def _count_keys(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("""
            INSERT INTO attribute_keys
            SELECT k, count(*), NULL
            FROM (SELECT unnest(json_keys(jattr)) AS k FROM sra_metadata)
            GROUP BY k
        """)

    def _attach_samples(self, con: duckdb.DuckDBPyConnection) -> None:
        """Values are extracted per (row, key), which is why this runs over a sample."""
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE sampled AS
            SELECT k, list(DISTINCT v)[1:{MAX_SAMPLES}] AS vs
            FROM (
                SELECT k, json_extract_string(jattr, '$.' || k) AS v
                FROM (SELECT jattr, unnest(json_keys(jattr)) AS k
                      FROM sra_metadata USING SAMPLE {self.sample_rows} ROWS)
                WHERE json_extract_string(jattr, '$.' || k) IS NOT NULL
            )
            GROUP BY k
        """)
        con.execute("""
            UPDATE attribute_keys a
            SET samples_json = to_json(s.vs)
            FROM sampled s WHERE s.k = a.key
        """)

    def _report(self, con: duckdb.DuckDBPyConnection) -> None:
        total, sampled = con.execute(
            "SELECT count(*), count(samples_json) FROM attribute_keys").fetchone()
        print(f"attribute_keys: {total} keys · {sampled} with sample values")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--sample-rows", type=int, default=DEFAULT_SAMPLE_ROWS)
    args = parser.parse_args()
    AttributeIndexBuilder(args.db, args.sample_rows).build()


if __name__ == "__main__":
    main()
