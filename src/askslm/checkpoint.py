"""Resumable checkpoints for a cohort build.

Discovery (~10 min) and the profile scan (~1 hour) are the expensive stages;
`build.py` used to hold both in memory with one write at the very end, so a
crash after either stage meant replaying it from scratch. These functions
persist each stage's result under `<plan_dir>/checkpoint/` and key it to a
hash of the translation SQL (and, for the matrix, the chosen profile sources)
so a changed plan can't silently reuse stale data.

Parquet is written through DuckDB itself (`duckdb.from_df(...).write_parquet`)
rather than `DataFrame.to_parquet`, which needs pyarrow -- not installed in
the cluster env, and not worth adding when the already-installed dependency
does the same job.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import duckdb
import pandas as pd

from askslm.cohort import Accession, Cohort
from askslm.profiles import ProfileMatrix
from askslm.sources import Source
from askslm.translation import SourceQuery

_DIR_NAME = "checkpoint"


def cohort_key(queries: tuple[SourceQuery, ...]) -> str:
    payload = sorted((query.source.name, query.sql) for query in queries)
    return hashlib.sha256(json.dumps(payload).encode()).hexdigest()[:16]


def matrix_key(discovery_key: str, profile_sources: tuple[Source, ...]) -> str:
    payload = f"{discovery_key}:{sorted(source.name for source in profile_sources)}"
    return hashlib.sha256(payload.encode()).hexdigest()[:16]


def save_cohort(plan_dir: Path, cohort: Cohort, key: str) -> None:
    directory = _mkdir(plan_dir)
    payload = {"key": key,
              "by_source": {source.name: sorted(accessions)
                           for source, accessions in cohort.by_source.items()}}
    (directory / "cohort.json").write_text(json.dumps(payload))


def load_cohort(plan_dir: Path, key: str) -> Cohort | None:
    path = _dir(plan_dir) / "cohort.json"
    if not path.exists():
        return None
    payload = json.loads(path.read_text())
    if payload["key"] != key:
        return None
    return Cohort({Source[name]: frozenset(Accession(value) for value in accessions)
                  for name, accessions in payload["by_source"].items()})


def save_matrix(plan_dir: Path, matrix: ProfileMatrix, key: str) -> None:
    """Writes counts/lineage AS-IS, with no reset_index() copy: at this point in the
    build the process is already near its memory ceiling (a 645GB-scan result plus the
    pivoted matrix), and reset_index() forces pandas to rebuild the whole block manager
    -- an avoidable multi-GB spike at the worst possible moment. duckdb.from_df ignores
    the pandas index entirely, so the feature ids are persisted separately, as plain
    JSON, and reattached on load instead."""
    directory = _mkdir(plan_dir)
    duckdb.from_df(matrix.counts).write_parquet(str(directory / "matrix_counts.parquet"))
    duckdb.from_df(matrix.lineage).write_parquet(str(directory / "matrix_lineage.parquet"))
    payload = {"key": key,
              "counts_dtype": str(matrix.counts.values.dtype),
              "counts_index_name": matrix.counts.index.name,
              "counts_index": matrix.counts.index.tolist(),
              "lineage_index_name": matrix.lineage.index.name,
              "lineage_index": matrix.lineage.index.tolist(),
              "column_biosample": dict(matrix.column_biosample)}
    (directory / "matrix_columns.json").write_text(json.dumps(payload))


def load_matrix(plan_dir: Path, key: str) -> ProfileMatrix | None:
    directory = _dir(plan_dir)
    columns_path = directory / "matrix_columns.json"
    counts_path = directory / "matrix_counts.parquet"
    lineage_path = directory / "matrix_lineage.parquet"
    if not (columns_path.exists() and counts_path.exists() and lineage_path.exists()):
        return None
    payload = json.loads(columns_path.read_text())
    if payload["key"] != key:
        return None
    counts = _indexed(duckdb.read_parquet(str(counts_path)).df(),
                      payload["counts_index"], payload["counts_index_name"]
                      ).astype(payload["counts_dtype"])
    lineage = _indexed(duckdb.read_parquet(str(lineage_path)).df(),
                       payload["lineage_index"], payload["lineage_index_name"])
    column_biosample = {column: Accession(biosample)
                       for column, biosample in payload["column_biosample"].items()}
    return ProfileMatrix(counts, lineage, column_biosample)


def _indexed(frame: pd.DataFrame, index_values: list, index_name: str | None) -> pd.DataFrame:
    frame.index = pd.Index(index_values, name=index_name)
    return frame


def clear(plan_dir: Path) -> None:
    """Checkpoints exist only to survive a crash mid-build; once a biom is
    written they are dead weight on a nearly-full disk."""
    directory = _dir(plan_dir)
    if not directory.exists():
        return
    for path in directory.iterdir():
        path.unlink()
    directory.rmdir()


def _dir(plan_dir: Path) -> Path:
    return Path(plan_dir) / _DIR_NAME


def _mkdir(plan_dir: Path) -> Path:
    directory = _dir(plan_dir)
    directory.mkdir(parents=True, exist_ok=True)
    return directory
