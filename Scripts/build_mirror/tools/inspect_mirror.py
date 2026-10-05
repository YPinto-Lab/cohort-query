"""READ-ONLY report on a DuckDB. Writes nothing, changes nothing.

Describes whatever tables are actually present -- it does not assume the cohortquery
mirror has been built -- and answers the design questions only real data can settle.

    python Scripts/build_mirror/inspect_mirror.py --db /path/to/sra.duckdb

Scale-aware by design. The SRA taxonomy table is ~13.6 BILLION rows, so this never
scans it: schemas come from DESCRIBE, samples from LIMIT, and the runs-per-biosample
question is answered from the metadata table alone. Column cardinality is probed with
approx_count_distinct first and only counted exactly when it is plausibly small.

Nothing sample-level leaves the machine except distinct values of low-cardinality
metadata columns -- exactly what the LLM prompt will contain anyway.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))
from cohortquery.adapters import attach_sidecars          # noqa: E402


MAX_DISTINCT = 200
HUGE_TABLE_ROWS = 100_000_000        # never aggregate over a table above this

# Widening ladder for "what counts as a metagenome". Submitter labels are unreliable,
# so the organism convention catches runs whose librarysource is mislabelled.
_SCOPING_FILTERS = [
    ("librarysource = METAGENOMIC",
     "librarysource = 'METAGENOMIC'"),
    ("+ METATRANSCRIPTOMIC",
     "librarysource IN ('METAGENOMIC', 'METATRANSCRIPTOMIC')"),
    ("+ organism like '%metagenome%'",
     "librarysource IN ('METAGENOMIC', 'METATRANSCRIPTOMIC') "
     "OR organism ILIKE '%metagenome%'"),
    ("+ organism like '%microbiom%' (widest)",
     "librarysource IN ('METAGENOMIC', 'METATRANSCRIPTOMIC') "
     "OR organism ILIKE '%metagenome%' OR organism ILIKE '%microbiom%'"),
]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--max-distinct", type=int, default=MAX_DISTINCT)
    parser.add_argument("--metadata-table", default=None,
                        help="the SRA/Metalog metadata table (auto-detected if omitted)")
    args = parser.parse_args()

    con = duckdb.connect(str(args.db), read_only=True)

    attach_sidecars(con)
    report = MirrorReport(con, args.max_distinct)
    report.tables()
    report.schemas()
    report.samples()
    report.runs_per_biosample(args.metadata_table or report.metadata_table())
    report.scoping_filters(args.metadata_table or report.metadata_table())
    report.value_vocabularies(args.metadata_table or report.metadata_table())
    con.close()


class MirrorReport:
    def __init__(self, con: duckdb.DuckDBPyConnection, max_distinct: int):
        self._con = con
        self._max_distinct = max_distinct
        self._rows: dict[str, int] = {}

    def tables(self) -> None:
        _heading("TABLES PRESENT")
        for table in self._table_names():
            count = self._scalar(f"SELECT count(*) FROM {_q(table)}")
            self._rows[table] = count
            print(f"  {table:32} {count:>18,} rows")

    def schemas(self) -> None:
        _heading("SCHEMAS")
        for table in self._table_names():
            columns = self._con.execute(f"DESCRIBE {_q(table)}").fetchall()
            print(f"\n  {table}  ({len(columns)} columns, {self._rows.get(table, 0):,} rows)")
            for name, dtype, *_ in columns:
                print(f"      {name:40} {dtype}")

    def samples(self) -> None:
        """Three rows per table. LIMIT never scans, so this is safe on a 13.6B-row table."""
        _heading("SAMPLE ROWS  (LIMIT 3 -- no scan)")
        for table in self._table_names():
            print(f"\n  --- {table} ---")
            rows = self._con.execute(f"SELECT * FROM {_q(table)} LIMIT 3").fetchall()
            columns = [row[0] for row in self._con.execute(f"DESCRIBE {_q(table)}").fetchall()]
            for row in rows:
                pairs = ", ".join(f"{c}={_short(v)}" for c, v in zip(columns, row))
                print(f"      {pairs}")

    def metadata_table(self) -> str | None:
        """The table that maps run -> biosample. Named metadata_raw on the SRA-side DB."""
        for candidate in ("sra_metadata", "metadata_raw", "metalog_metadata"):
            if candidate in self._rows:
                return candidate
        return None

    def runs_per_biosample(self, table: str | None) -> None:
        """HLD B.3: how much does one-biom-column-per-run actually matter here?

        Answered from the METADATA table only -- the taxonomy table is never touched.
        """
        _heading(f"RUNS PER BIOSAMPLE  (HLD B.3)  -- from {table}")
        if table is None or "biosample" not in self._columns(table):
            print("  no metadata table with a biosample column found")
            return

        totals = self._con.execute(f"""
            SELECT count(*), sum(runs), sum(CASE WHEN runs > 1 THEN 1 ELSE 0 END), max(runs)
            FROM (SELECT biosample, count(DISTINCT acc) AS runs FROM {_q(table)}
                  WHERE biosample IS NOT NULL GROUP BY 1)
        """).fetchone()
        biosamples, runs, multi, most = totals
        share = (multi / biosamples * 100) if biosamples else 0
        print(f"  distinct biosamples        : {biosamples:,}")
        print(f"  runs                       : {runs:,}")
        print(f"  biosamples with >1 run     : {multi:,}   ({share:.1f}%)")
        print(f"  most runs on one biosample : {most:,}")
        print("\n  -> near 0% means the decision is moot for this data;")
        print("     a large share means STAT bioms are materially wider than the biosample count.")

        if "assay_type" not in self._columns(table):
            return
        print("\n  assay_type mix ACROSS multi-run biosamples")
        print("  (>1 distinct assay on one biosample is the hard evidence against summing runs):")
        mixed = self._con.execute(f"""
            SELECT count(*) FROM (
                SELECT biosample FROM {_q(table)} WHERE biosample IS NOT NULL
                GROUP BY 1 HAVING count(DISTINCT acc) > 1 AND count(DISTINCT assay_type) > 1)
        """).fetchone()[0]
        print(f"      biosamples whose runs span >1 assay_type: {mixed:,}")
        for assay, count in self._con.execute(f"""
            SELECT assay_type, count(*) FROM {_q(table)} GROUP BY 1 ORDER BY 2 DESC LIMIT 12
        """).fetchall():
            print(f"      {str(assay):28} {count:,}")

    def scoping_filters(self, table: str | None) -> None:
        """How much of SRA is actually metagenomic?

        The cohortquery mirror is a DERIVED working set -- the full SRA database stays on
        the server untouched -- so narrowing it discards nothing and can be widened by
        a rebuild. The gain is not only speed: restricting collapses `organism` from
        ~247k mostly-irrelevant values to a vocabulary the LLM can actually match a
        research question against.

        Reported as a ladder of widening filters, because submitter labels are
        unreliable and NCBI's convention (organism ending in "metagenome") catches
        runs whose librarysource is mislabelled.
        """
        _heading(f"SCOPING: HOW MUCH OF SRA IS METAGENOMIC?  -- from {table}")
        if table is None:
            print("  no metadata table found")
            return
        columns = self._columns(table)
        if "librarysource" not in columns or "organism" not in columns:
            print("  needs librarysource and organism columns")
            return

        total = self._rows.get(table, 0)
        for label, predicate in _SCOPING_FILTERS:
            runs = self._scalar(f'SELECT count(*) FROM {_q(table)} WHERE {predicate}')
            biosamples = self._scalar(
                f'SELECT count(DISTINCT biosample) FROM {_q(table)} WHERE {predicate}')
            share = (runs / total * 100) if total else 0
            print(f"  {label:52} {runs:>13,} runs  {share:5.2f}%  "
                  f"{biosamples:>12,} biosamples")

        print("\n  organism vocabulary under the widest filter (what the LLM would see):")
        widest = _SCOPING_FILTERS[-1][1]
        distinct = self._scalar(
            f'SELECT approx_count_distinct(organism) FROM {_q(table)} WHERE {widest}')
        print(f"      ~{distinct:,} distinct organisms  (unrestricted: see VALUE VOCABULARIES)")
        for organism, runs in self._con.execute(f"""
            SELECT organism, count(*) FROM {_q(table)} WHERE {widest}
            GROUP BY 1 ORDER BY 2 DESC LIMIT 25
        """).fetchall():
            print(f"      {str(organism):48} {runs:>12,}")

    def value_vocabularies(self, table: str | None) -> None:
        """The payload the LLM prompt needs: what the metadata columns actually CONTAIN."""
        _heading(f"VALUE VOCABULARIES  (<= {self._max_distinct} distinct)  -- from {table}")
        if table is None:
            print("  no metadata table found")
            return
        if self._rows.get(table, 0) > HUGE_TABLE_ROWS:
            print(f"  {table} has {self._rows[table]:,} rows -- probing with approx_count_distinct")

        for column in self._columns(table):
            approx = self._scalar(
                f'SELECT approx_count_distinct("{column}") FROM {_q(table)}')
            if approx > self._max_distinct * 2:
                print(f"    {column:40} ~{approx:>10,} distinct   (too many)")
                continue
            values = [row[0] for row in self._con.execute(
                f'SELECT DISTINCT "{column}" FROM {_q(table)} '
                f'WHERE "{column}" IS NOT NULL ORDER BY 1 LIMIT {self._max_distinct + 1}'
            ).fetchall()]
            marker = "  (truncated)" if len(values) > self._max_distinct else ""
            print(f"    {column:40} {len(values):>10,} distinct   {values}{marker}")

    def _table_names(self) -> list[str]:
        return [row[0] for row in self._con.execute("SHOW TABLES").fetchall()]

    def _columns(self, table: str) -> list[str]:
        return [row[0] for row in self._con.execute(f"DESCRIBE {_q(table)}").fetchall()]

    def _scalar(self, sql: str):
        return self._con.execute(sql).fetchone()[0]


def _q(table: str) -> str:
    return f'"{table}"'


def _short(value, limit: int = 40) -> str:
    text = str(value)
    return text if len(text) <= limit else text[:limit] + "…"


def _heading(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


if __name__ == "__main__":
    main()
