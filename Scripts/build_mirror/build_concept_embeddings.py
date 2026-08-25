"""Embed attribute_keys and low-cardinality schema_catalog values, so a question can
find a field or value that means the same thing without sharing its spelling.

Run AFTER build_attribute_index.py and build_schema_catalog.py -- this reads both of
their output tables. Batches every text into as few embed() calls as the batch size
allows: one call per BATCH_SIZE items, not one call per item, because the real mirror
has ~36,000 keys plus however many low-cardinality column values.

    python Scripts/build_mirror/build_concept_embeddings.py --db askslm_mirror.duckdb --api-key $ASKSLM_LLM_KEY
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from askslm.concept_search import EMBED_DIM, Embedder

DEFAULT_BATCH_SIZE = 100    # measured against the real free-tier embedding endpoint
                            # 2026-08-25: a single 100-item batch is accepted, but the
                            # account's embed_content_free_tier_requests quota is
                            # ~100 requests/MINUTE -- see MAX_RETRIES/BATCH_PACING_SECONDS.

MAX_RETRIES = 5             # a 429 RESOURCE_EXHAUSTED mid-run is expected, not
                            # exceptional, against ~945 batches (94,450 real keys /
                            # batch_size=100) on a free-tier per-minute quota.
INITIAL_BACKOFF_SECONDS = 5
BATCH_PACING_SECONDS = 0.7  # stays under the ~100 req/min free-tier ceiling with margin.


class ConceptEmbeddingBuilder:
    """Two tables: attribute_key_embeddings (every jattr key) and
    column_value_embeddings (every value of every low-cardinality metadata column)."""

    def __init__(self, db_path: Path, embedder: Embedder, dim: int = EMBED_DIM,
                batch_size: int = DEFAULT_BATCH_SIZE):
        self.db_path = db_path
        self.embedder = embedder
        self.dim = dim
        self.batch_size = batch_size

    def build(self) -> None:
        con = duckdb.connect(str(self.db_path))
        self._build_key_embeddings(con=con)
        self._build_value_embeddings(con=con)
        self._report(con=con)
        con.close()

    def _build_key_embeddings(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("DROP TABLE IF EXISTS attribute_key_embeddings")
        con.execute(f"CREATE TABLE attribute_key_embeddings (key TEXT, vector FLOAT[{self.dim}])")
        keys = [row[0] for row in con.execute("SELECT key FROM attribute_keys").fetchall()]
        vectors = self._embed_in_batches(texts=keys)
        con.executemany("INSERT INTO attribute_key_embeddings VALUES (?, ?)",
                        list(zip(keys, vectors)))
        self._create_hnsw_index(con=con, table="attribute_key_embeddings")

    def _build_value_embeddings(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("DROP TABLE IF EXISTS column_value_embeddings")
        con.execute(f"""CREATE TABLE column_value_embeddings (
            table_name TEXT, column_name TEXT, value TEXT, vector FLOAT[{self.dim}])""")
        columns = self._qualifying_columns(con=con)
        vectors = self._embed_in_batches(texts=[value for _, _, value in columns])
        rows = [(table, column, value, vector)
                for (table, column, value), vector in zip(columns, vectors)]
        con.executemany("INSERT INTO column_value_embeddings VALUES (?, ?, ?, ?)", rows)
        self._create_hnsw_index(con=con, table="column_value_embeddings")

    def _embed_in_batches(self, texts: list[str]) -> list[list[float]]:
        """Shared by both tables: same batching, same embedder, different callers.
        Not premature abstraction -- both call sites need it right now, unchanged.
        Paced between batches to stay under the free-tier per-minute quota; a 429
        mid-run is expected at this volume, not exceptional (see MAX_RETRIES)."""
        vectors: list[list[float]] = []
        for index, batch in enumerate(_chunks(items=texts, size=self.batch_size)):
            vectors.extend(self._embed_batch(batch=batch, index=index))
            time.sleep(BATCH_PACING_SECONDS)
        return vectors

    def _embed_batch(self, batch: list[str], index: int) -> list[list[float]]:
        """Retries a short/empty result (embed()'s documented degrade-on-failure
        contract, e.g. a transient 429) before treating it as unrecoverable.
        Still fails loudly after exhausting retries -- a silently short batch
        would misalign every subsequent (key, vector) pair via zip(), with no
        way to detect the corruption downstream."""
        backoff = INITIAL_BACKOFF_SECONDS
        for attempt in range(MAX_RETRIES):
            embedded = self.embedder.embed(batch)
            if len(embedded) == len(batch):
                return embedded
            print(f"batch {index}: got {len(embedded)}/{len(batch)} vectors "
                  f"(attempt {attempt + 1}/{MAX_RETRIES}), retrying in {backoff}s")
            time.sleep(backoff)
            backoff *= 2
        raise RuntimeError(
            f"batch {index}: embed() still short after {MAX_RETRIES} retries "
            "-- aborting to avoid corrupting the index")

    def _create_hnsw_index(self, con: duckdb.DuckDBPyConnection, table: str) -> None:
        con.execute("INSTALL vss")
        con.execute("LOAD vss")
        con.execute("SET hnsw_enable_experimental_persistence = true")
        con.execute(f"CREATE INDEX {table}_idx ON {table} USING HNSW (vector) "
                    "WITH (metric = 'cosine')")

    def _qualifying_columns(self, con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
        """Only columns schema_catalog already shows a COMPLETE vocabulary for --
        truncated or NULL-valued columns are identifiers or free text, not vocabulary
        (see build_schema_catalog.py's _is_identifier)."""
        rows = con.execute(
            "SELECT table_name, column_name, values_json FROM schema_catalog "
            "WHERE truncated = false AND values_json IS NOT NULL").fetchall()
        return [(table_name, column_name, value)
                for table_name, column_name, values_json in rows
                for value in json.loads(values_json)]

    def _report(self, con: duckdb.DuckDBPyConnection) -> None:
        keys, values = con.execute(
            "SELECT (SELECT count(*) FROM attribute_key_embeddings), "
            "       (SELECT count(*) FROM column_value_embeddings)").fetchone()
        print(f"attribute_key_embeddings: {keys} keys · "
              f"column_value_embeddings: {values} values")


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--dim", type=int, default=EMBED_DIM)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()

    from askslm.adapters import open_gemini

    embedder = open_gemini(args.api_key, "gemini-2.5-flash")  # model unused by embed()
    ConceptEmbeddingBuilder(args.db, embedder, args.dim, args.batch_size).build()


if __name__ == "__main__":
    main()
