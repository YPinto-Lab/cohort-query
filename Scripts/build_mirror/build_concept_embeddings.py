"""Embed attribute_keys and low-cardinality schema_catalog values, so a question can
find a field or value that means the same thing without sharing its spelling.

Run AFTER build_attribute_index.py and build_schema_catalog.py -- this reads both of
their output tables. Batches every text into as few embed() calls as the batch size
allows: one call per BATCH_SIZE items, not one call per item. Measured against the
real mirror 2026-08-25: 94,450 keys + 4,416 qualifying values, ~2.17M characters
total -- a projected cost of well under $1 at gemini-embedding-001 pricing, enforced
by --max-cost-usd so a bug can't run past that regardless of what the estimate says.

    python Scripts/build_mirror/build_concept_embeddings.py --db askslm_mirror.duckdb --api-key $ASKSLM_LLM_KEY
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import time
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from askslm.concept_search import EMBED_DIM, Embedder

DEFAULT_BATCH_SIZE = 100    # measured against the real free-tier embedding endpoint
                            # 2026-08-25: a single 100-item batch is accepted.

MAX_RETRIES = 5             # a 429 RESOURCE_EXHAUSTED mid-run is expected, not
                            # exceptional, against ~945 batches (94,450 real keys /
                            # batch_size=100) on a free-tier per-minute quota.
INITIAL_BACKOFF_SECONDS = 5
# 2026-08-25 real run: 0.7s pacing (~85 req/min against a stated ~100/min quota) still
# hit sustained 429s from batch 1 onward, for the entire 10-minute run -- not a brief
# blip a short backoff could ride out. Slowed to a real sustained rate of ~20 req/min,
# leaving headroom for retries to also fit inside the quota rather than compounding it.
BATCH_PACING_SECONDS = 3.0

# Cost safeguard -- enforced by this script, not just a Google Cloud budget alert
# (which only notifies, it doesn't stop spend). Deliberately conservative so the
# estimate never falls BELOW the real bill: gemini-embedding-001 standard pricing
# is $0.20/1M tokens (2026-05), and 3 chars/token undercounts English's real ~4
# chars/token, so the projected cost is always >= what Google will actually charge.
PRICE_PER_1M_TOKENS_USD = 0.20
CONSERVATIVE_CHARS_PER_TOKEN = 3
DEFAULT_MAX_COST_USD = 5.0


class ConceptEmbeddingBuilder:
    """Two tables: attribute_key_embeddings (every jattr key) and
    column_value_embeddings (every value of every low-cardinality metadata column)."""

    def __init__(self, db_path: Path, embedder: Embedder, dim: int = EMBED_DIM,
                batch_size: int = DEFAULT_BATCH_SIZE, max_cost_usd: float = DEFAULT_MAX_COST_USD):
        self.db_path = db_path
        self.embedder = embedder
        self.dim = dim
        self.batch_size = batch_size
        self.max_cost_usd = max_cost_usd
        self._spent_usd = 0.0

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
            self._charge_for(batch=batch)
            vectors.extend(self._embed_batch(batch=batch, index=index))
            time.sleep(BATCH_PACING_SECONDS)
        return vectors

    def _charge_for(self, batch: list[str]) -> None:
        """Enforced BEFORE the call it would pay for, not after -- a cap checked
        post-hoc could still let one over-budget call through. Aborts the whole
        run rather than skipping the batch: a partially-embedded key set is a
        worse outcome than stopping and re-running once the cap is raised."""
        chars = sum(len(text) for text in batch)
        projected = chars / CONSERVATIVE_CHARS_PER_TOKEN / 1_000_000 * PRICE_PER_1M_TOKENS_USD
        if self._spent_usd + projected > self.max_cost_usd:
            raise RuntimeError(
                f"aborting before spending more: ${self._spent_usd:.4f} spent so far, "
                f"this batch would add ~${projected:.4f}, cap is ${self.max_cost_usd:.2f}")
        self._spent_usd += projected
        print(f"running cost estimate: ${self._spent_usd:.4f} / ${self.max_cost_usd:.2f}")

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
    logging.basicConfig(level=logging.INFO, format="%(message)s")  # surface embed()'s
    # own failure reason -- adapters.py logs it via `logging`, not print()

    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--dim", type=int, default=EMBED_DIM)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    parser.add_argument("--max-cost-usd", type=float, default=DEFAULT_MAX_COST_USD,
                        help="abort before spending more than this (conservative estimate)")
    args = parser.parse_args()

    from askslm.adapters import open_gemini

    embedder = open_gemini(args.api_key, "gemini-2.5-flash")  # model unused by embed()
    ConceptEmbeddingBuilder(args.db, embedder, args.dim, args.batch_size,
                            args.max_cost_usd).build()


if __name__ == "__main__":
    main()
