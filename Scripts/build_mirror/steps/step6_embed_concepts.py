"""Embed low-cardinality schema_catalog values, so a question can find a NATIVE
column value that means the same thing without sharing its spelling
("shotgun" -> librarysource = 'METAGENOMIC'). jattr key/value concept search is a
separate mechanism now (step7_build_attribute_indexes.py) -- this step used to
also embed every jattr key into attribute_key_embeddings, superseded by that
step's attribute_keys_index.

Run AFTER step5_catalog_schema.py -- this reads its output table. Runs entirely
locally (sentence-transformers on CPU) -- no API key, no quota, no cost. Switched
from a hosted embeddings API after its free-tier per-minute AND per-day quotas
both proved too restrictive to finish the build, hitting sustained 429s even
right after a fresh daily reset; a local model finishes the same build in minutes.

    python Scripts/build_mirror/steps/step6_embed_concepts.py --db cohortquery_mirror.duckdb
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from cohortquery.concept_search import EMBED_DIM, Embedder


class ConceptEmbeddingBuilder:
    """column_value_embeddings: every value of every low-cardinality native
    metadata column."""

    def __init__(self, db_path: Path, embedder: Embedder, dim: int = EMBED_DIM):
        self.db_path = db_path
        self.embedder = embedder
        self.dim = dim

    def build(self) -> None:
        con = duckdb.connect(str(self.db_path))
        self._build_value_embeddings(con=con)
        self._report(con=con)
        con.close()

    def _build_value_embeddings(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("DROP TABLE IF EXISTS column_value_embeddings")
        con.execute(f"""CREATE TABLE column_value_embeddings (
            table_name TEXT, column_name TEXT, value TEXT, vector FLOAT[{self.dim}])""")
        columns = self._qualifying_columns(con=con)
        vectors = self.embedder.embed([value for _, _, value in columns])
        rows = [(table, column, value, vector)
                for (table, column, value), vector in zip(columns, vectors)]
        con.executemany("INSERT INTO column_value_embeddings VALUES (?, ?, ?, ?)", rows)
        self._create_hnsw_index(con=con, table="column_value_embeddings")

    def _create_hnsw_index(self, con: duckdb.DuckDBPyConnection, table: str) -> None:
        con.execute("INSTALL vss")
        con.execute("LOAD vss")
        con.execute("SET hnsw_enable_experimental_persistence = true")
        con.execute(f"CREATE INDEX {table}_idx ON {table} USING HNSW (vector) "
                    "WITH (metric = 'cosine')")

    def _qualifying_columns(self, con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
        """Only columns schema_catalog already shows a COMPLETE vocabulary for --
        truncated or NULL-valued columns are identifiers or free text, not vocabulary
        (see step5_catalog_schema.py's _is_identifier)."""
        rows = con.execute(
            "SELECT table_name, column_name, values_json FROM schema_catalog "
            "WHERE truncated = false AND values_json IS NOT NULL").fetchall()
        return [(table_name, column_name, value)
                for table_name, column_name, values_json in rows
                for value in json.loads(values_json)]

    def _report(self, con: duckdb.DuckDBPyConnection) -> None:
        values = con.execute("SELECT count(*) FROM column_value_embeddings").fetchone()[0]
        print(f"column_value_embeddings: {values} values")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--dim", type=int, default=EMBED_DIM)
    args = parser.parse_args()

    from cohortquery.adapters import open_local_embedder

    ConceptEmbeddingBuilder(args.db, open_local_embedder(), args.dim).build()


if __name__ == "__main__":
    main()
