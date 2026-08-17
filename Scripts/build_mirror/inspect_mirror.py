"""READ-ONLY report on a built mirror. Writes nothing, changes nothing.

Answers the questions the design left open that only the real data can settle, and
prints the value vocabularies needed to write the translation eval set's gold SQL.

    python Scripts/build_mirror/inspect_mirror.py --db /path/to/askslm_mirror.duckdb

Everything it prints is schema and aggregate counts -- no sample-level rows leave
the machine except distinct values of low-cardinality metadata columns, which is
exactly what the LLM prompt will contain anyway.
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

EXPECTED_TABLES = ("sra_metadata", "sra_taxonomy", "metalog_metadata",
                   "metalog_metaphlan4", "metalog_metaphlan4_species",
                   "metalog_motus3", "metalog_spire_motus")
MAX_DISTINCT = 200


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--max-distinct", type=int, default=MAX_DISTINCT)
    args = parser.parse_args()

    con = duckdb.connect(str(args.db), read_only=True)
    report = MirrorReport(con, args.max_distinct)
    report.tables()
    report.schemas()
    report.stat_runs()
    report.metaphlan_species()
    report.value_vocabularies()
    con.close()


class MirrorReport:
    def __init__(self, con: duckdb.DuckDBPyConnection, max_distinct: int):
        self._con = con
        self._max_distinct = max_distinct

    def tables(self) -> None:
        _heading("TABLES PRESENT")
        present = {row[0] for row in self._con.execute("SHOW TABLES").fetchall()}
        for table in sorted(present):
            count = self._scalar(f"SELECT count(*) FROM {table}")
            print(f"  {table:32} {count:>14,} rows")
        missing = [t for t in EXPECTED_TABLES if t not in present]
        extra = [t for t in sorted(present) if t not in EXPECTED_TABLES]
        print(f"  expected but MISSING: {missing or 'none'}")
        print(f"  present but unexpected: {extra or 'none'}")

    def schemas(self) -> None:
        _heading("SCHEMAS  (confirms the Source enum's table/column names)")
        for table in EXPECTED_TABLES:
            if not self._exists(table):
                continue
            columns = self._con.execute(f"DESCRIBE {table}").fetchall()
            print(f"\n  {table}  ({len(columns)} columns)")
            for name, dtype, *_ in columns:
                print(f"      {name:36} {dtype}")

    def stat_runs(self) -> None:
        """How much does the one-biom-column-per-run decision (HLD B.3) affect this data?

        Joins acc -> sra_metadata at query time, so it works whether or not the mirror
        has been rebuilt with the biosample stamping.
        """
        _heading("STAT: RUNS PER BIOSAMPLE  (HLD B.3)")
        if not self._exists("sra_taxonomy"):
            print("  sra_taxonomy absent")
            return
        stamped = "biosample" in self._columns("sra_taxonomy")
        print(f"  sra_taxonomy already has a biosample column: {stamped}")

        runs_per_biosample = """
            SELECT s.biosample AS biosample, count(DISTINCT t.acc) AS runs
            FROM sra_taxonomy t JOIN sra_metadata s ON t.acc = s.acc
            WHERE s.biosample IS NOT NULL GROUP BY 1
        """
        totals = self._con.execute(f"""
            SELECT count(*), sum(runs), sum(CASE WHEN runs > 1 THEN 1 ELSE 0 END), max(runs)
            FROM ({runs_per_biosample})
        """).fetchone()
        biosamples, runs, multi, most = totals
        print(f"  biosamples with a STAT profile : {biosamples:,}")
        print(f"  runs                           : {runs:,}")
        print(f"  biosamples with >1 run         : {multi:,}"
              f"   ({(multi / biosamples * 100 if biosamples else 0):.1f}%)")
        print(f"  most runs on one biosample     : {most}")
        print("\n  -> if the >1 figure is ~0 the decision is moot for this data;")
        print("     if it is large, STAT bioms are materially wider than the biosample count.")

        print("\n  assay types among multi-run biosamples (why summing was rejected):")
        for assay, count in self._con.execute(f"""
            SELECT s.assay_type, count(DISTINCT s.acc)
            FROM sra_metadata s
            WHERE s.biosample IN (SELECT biosample FROM ({runs_per_biosample}) WHERE runs > 1)
            GROUP BY 1 ORDER BY 2 DESC LIMIT 10
        """).fetchall():
            print(f"      {str(assay):24} {count:,}")

    def metaphlan_species(self) -> None:
        """Does metalog_metaphlan4_species cover SAMPLES the all-levels table lacks?

        If non-zero it is not redundant and earns a Source in the package (HLD E.3).
        """
        _heading("METAPHLAN: species table vs all-levels  (HLD E.3)")
        if not (self._exists("metalog_metaphlan4_species") and self._exists("metalog_metaphlan4")):
            print("  one of the two tables is absent")
            return
        species = self._scalar("SELECT count(DISTINCT sample_alias) FROM metalog_metaphlan4_species")
        all_levels = self._scalar("SELECT count(DISTINCT sample_alias) FROM metalog_metaphlan4")
        only_species = self._scalar("""
            SELECT count(*) FROM (SELECT DISTINCT sample_alias FROM metalog_metaphlan4_species)
            ANTI JOIN (SELECT DISTINCT sample_alias FROM metalog_metaphlan4) USING (sample_alias)
        """)
        print(f"  samples in metaphlan4_species : {species:,}")
        print(f"  samples in metaphlan4 (all)   : {all_levels:,}")
        print(f"  samples ONLY in species       : {only_species:,}")
        print("  -> 0 means redundant, as assumed. Non-zero means it needs its own Source.")

    def value_vocabularies(self) -> None:
        """The payload the LLM prompt needs: what the metadata columns actually CONTAIN."""
        _heading(f"VALUE VOCABULARIES  (metadata columns with <= {self._max_distinct} distinct)")
        for table in ("metalog_metadata", "sra_metadata"):
            if not self._exists(table):
                continue
            print(f"\n  --- {table} ---")
            for column in self._columns(table):
                distinct = self._scalar(f'SELECT count(DISTINCT "{column}") FROM {table}')
                if distinct == 0 or distinct > self._max_distinct:
                    print(f"    {column:36} {distinct:>8,} distinct   (too many / empty)")
                    continue
                values = [row[0] for row in self._con.execute(
                    f'SELECT DISTINCT "{column}" FROM {table} '
                    f'WHERE "{column}" IS NOT NULL ORDER BY 1').fetchall()]
                print(f"    {column:36} {distinct:>8,} distinct   {values}")

    def _exists(self, table: str) -> bool:
        return bool(self._con.execute(
            "SELECT count(*) FROM information_schema.tables WHERE table_name = ?",
            [table]).fetchone()[0])

    def _columns(self, table: str) -> list[str]:
        return [row[0] for row in self._con.execute(f"DESCRIBE {table}").fetchall()]

    def _scalar(self, sql: str):
        return self._con.execute(sql).fetchone()[0]


def _heading(text: str) -> None:
    print(f"\n{'=' * 78}\n{text}\n{'=' * 78}")


if __name__ == "__main__":
    main()
