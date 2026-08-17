"""Named same-family sources -> one matrix, by unioning their columns.

The family is what makes the union valid: same feature namespace and same
abundance estimator, so whole columns are interchangeable. Values are read at
NATIVE granularity -- no roll-up, no normalization anywhere in the build.
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from askslm.cohort import Accession, key_column
from askslm.ports import Database
from askslm.sources import ProfilerFamily, Source


@dataclass(frozen=True)
class ProfileMatrix:
    counts: pd.DataFrame                       # features x biom columns
    lineage: pd.DataFrame                      # feature -> lineage. NEVER merged with metadata.
    column_biosample: dict[str, Accession]     # which biosample each column belongs to (B.3)

    def columns(self) -> list[str]:
        return list(self.counts.columns)

    def biosamples(self) -> frozenset[Accession]:
        return frozenset(self.column_biosample.values())


class ProfileReader:
    """Pulls ONE profile source, restricted to the cohort. Columns are its profiling unit."""

    def __init__(self, database: Database):
        self._database = database

    def read(self, source: Source, accessions: frozenset[Accession]) -> ProfileMatrix:
        rows = self._database.query(self._sql(source), [sorted(accessions)])
        if rows.empty:
            return ProfileMatrix(pd.DataFrame(), pd.DataFrame(), {})
        return _matrix_of(source, rows)

    def _sql(self, source: Source) -> str:
        spec = source.spec()
        return (f"SELECT * FROM {spec.table} "
                f"WHERE {_key_expression(spec.table)} IN (SELECT unnest(?::VARCHAR[]))")

    def coverage(self, source: Source, accessions: frozenset[Accession]) -> frozenset[Accession]:
        """Cheap preview count: which cohort biosamples does this source profile at all?"""
        rows = self._database.query(
            f"SELECT DISTINCT biosample FROM {source.spec().table} "
            f"WHERE biosample IN (SELECT unnest(?::VARCHAR[]))", [sorted(accessions)])
        return frozenset(Accession(key) for key in rows["biosample"].dropna())


class ProfileReconciler:
    """Folds the named same-family sources: head wins overlap, others add their own."""

    def __init__(self, reader: ProfileReader):
        self._reader = reader

    def read(self, profile_sources: tuple[Source, ...],
             accessions: frozenset[Accession]) -> ProfileMatrix:
        matrices = [self._reader.read(source, accessions) for source in profile_sources]
        return fold_by_column(matrices)


def fold_by_column(matrices: list[ProfileMatrix]) -> ProfileMatrix:
    """List order IS the precedence. The head keeps its columns; later sources add only
    the columns nobody before them had. A column is never a blend of two sources."""
    present = [matrix for matrix in matrices if not matrix.counts.empty]
    if not present:
        return ProfileMatrix(pd.DataFrame(), pd.DataFrame(), {})

    counts = present[0].counts
    mapping = dict(present[0].column_biosample)
    for matrix in present[1:]:
        new_columns = [column for column in matrix.columns() if column not in counts.columns]
        counts = counts.join(matrix.counts[new_columns], how="outer")
        mapping.update({column: matrix.column_biosample[column] for column in new_columns})

    return ProfileMatrix(counts.fillna(0), _union_lineage(present), mapping)


def _union_lineage(matrices: list[ProfileMatrix]) -> pd.DataFrame:
    """Same family means the same namespace, so lineages are compatible by construction.
    A feature carrying two different lineages is a broken assumption, not a tie to break."""
    combined = pd.concat([matrix.lineage for matrix in matrices])
    conflicts = combined[combined.index.duplicated(keep=False)].drop_duplicates()
    duplicated_features = conflicts.index[conflicts.index.duplicated()]
    if len(duplicated_features):
        raise ValueError(f"conflicting lineage for features: {sorted(set(duplicated_features))}")
    return combined[~combined.index.duplicated()]


def one_family(profile_sources: tuple[Source, ...]) -> ProfilerFamily:
    families = {source.family() for source in profile_sources}
    if len(families) != 1:
        raise ValueError(f"all profile_sources must share one ProfilerFamily, got {families}")
    return families.pop()


def _matrix_of(source: Source, rows: pd.DataFrame) -> ProfileMatrix:
    spec = source.spec()
    rows = rows.copy()
    rows["_biosample"] = key_column(rows)
    rows["_column"] = _column_ids(spec, rows)

    counts = rows.pivot_table(index=spec.feature_column, columns="_column",
                              values=spec.value_column, aggfunc="sum", fill_value=0)
    counts.index = counts.index.astype(str)
    mapping = dict(zip(rows["_column"].astype(str), rows["_biosample"]))
    return ProfileMatrix(counts, _lineage_of(source, rows), mapping)


def _lineage_of(source: Source, rows: pd.DataFrame) -> pd.DataFrame:
    """Metalog sources carry their lineage as a string. STAT's must be DERIVED from tax_id.

    ponytail: STAT lineage here is the table's own rank+name, not the full NCBI ancestry.
    Full ancestry is askslm.taxonomy.lineage_table, which needs the ~300 MB ete3 database --
    swap it in at this one call site when that is available on the build machine.
    """
    spec = source.spec()
    features = rows[spec.feature_column].astype(str)
    if spec.lineage_column is not None:
        lineage = pd.DataFrame({"lineage": rows[spec.lineage_column].astype(str)})
    else:
        lineage = pd.DataFrame({"name": rows["name"], "rank": rows["rank"]})
    lineage.index = features
    return lineage[~lineage.index.duplicated()]


def _column_ids(spec, rows: pd.DataFrame) -> pd.Series:
    """The column-id rule: a column is the unit that was profiled. For a sample-keyed
    source that is the biosample, falling back to sample_alias for the orphan tail; for
    a run-keyed source (STAT) it is the run accession itself."""
    if spec.column_id == "biosample":
        return rows["_biosample"]
    return rows[spec.column_id]


def _key_expression(table: str) -> str:
    return "coalesce(biosample, sample_alias)" if table.startswith("metalog_") else "biosample"
