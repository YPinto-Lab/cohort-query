"""Load a .biom and return a windowed slice of one of its three views.

Counts  = features (rows) x samples (cols) count matrix.
Samples = per-sample metadata table (sample id x metadata fields).
Lineage = per-feature metadata table (feature id x taxonomy fields).

Feature and sample metadata are kept as SEPARATE views — never merged.
Tables are large (tens of thousands of features), so callers always page;
the loaded table is cached by (path, mtime) to make paging cheap.
"""
from __future__ import annotations
import json
from dataclasses import dataclass
from pathlib import Path

from biom import Table, load_table

ROW_PAGE = 100
COL_PAGE = 60

_CACHE: dict[tuple[str, float], Table] = {}


@dataclass(frozen=True)
class TableWindow:
    index: list[str]          # row labels (feature or sample ids)
    columns: list[str]        # column labels
    rows: list[list]          # cell values, row-major, aligned to columns
    total_rows: int
    total_cols: int
    row_offset: int
    col_offset: int
    row_page: int
    col_page: int


def _load(path: Path) -> Table:
    key = (str(path), path.stat().st_mtime)
    table = _CACHE.get(key)
    if table is None:
        for stale in [k for k in _CACHE if k[0] == str(path)]:
            del _CACHE[stale]
        table = load_table(str(path))
        _CACHE[key] = table
    return table


def counts_window(path: Path, row_off: int = 0, col_off: int = 0,
                  row_page: int = ROW_PAGE, col_page: int = COL_PAGE) -> TableWindow:
    table = _load(path)
    obs_ids = [str(i) for i in table.ids(axis="observation")]
    sample_ids = [str(i) for i in table.ids(axis="sample")]
    row_ids = obs_ids[row_off:row_off + row_page]
    col_ids = sample_ids[col_off:col_off + col_page]

    # Subset to the window (sparse) BEFORE densifying, so we never materialize the
    # full dense matrix. filter() doesn't preserve caller order, so reindex() restores it.
    sub = (table.filter(row_ids, axis="observation", inplace=False)
                .filter(col_ids, axis="sample", inplace=False))
    frame = sub.to_dataframe(dense=True).reindex(index=row_ids, columns=col_ids)

    return TableWindow(
        index=row_ids,
        columns=col_ids,
        rows=[[_num(v) for v in row] for row in frame.to_numpy().tolist()],
        total_rows=len(obs_ids),
        total_cols=len(sample_ids),
        row_offset=row_off,
        col_offset=col_off,
        row_page=row_page,
        col_page=col_page,
    )


def samples_window(path: Path, row_off: int = 0, row_page: int = ROW_PAGE) -> TableWindow:
    return _metadata_window(path, "sample", row_off, row_page)


def lineage_window(path: Path, row_off: int = 0, row_page: int = ROW_PAGE) -> TableWindow:
    return _metadata_window(path, "observation", row_off, row_page)


def _metadata_window(path: Path, axis: str, row_off: int, row_page: int) -> TableWindow:
    table = _load(path)
    all_ids = [str(i) for i in table.ids(axis=axis)]
    metadata = table.metadata(axis=axis)
    window_ids = all_ids[row_off:row_off + row_page]

    records: list[dict] = []
    columns: list[str] = []
    for pos in range(row_off, min(row_off + row_page, len(all_ids))):
        record = {} if metadata is None else {k: _scalar(v) for k, v in dict(metadata[pos]).items()}
        records.append(record)
        for key in record:
            if key not in columns:
                columns.append(key)

    rows = [[rec.get(col, "") for col in columns] for rec in records]
    return TableWindow(
        index=window_ids,
        columns=columns,
        rows=rows,
        total_rows=len(all_ids),
        total_cols=len(columns),
        row_offset=row_off,
        col_offset=0,
        row_page=row_page,
        col_page=len(columns),
    )


def _num(value):
    number = float(value)
    return int(number) if number.is_integer() else number


def _scalar(value):
    if isinstance(value, (list, dict, tuple)):
        return json.dumps(value, default=str)
    return value
