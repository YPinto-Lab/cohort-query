"""Named same-family sources -> one matrix, by unioning their columns.

The family is what makes the union valid: same feature namespace and same
abundance estimator, so whole columns are interchangeable. Values are read at
NATIVE granularity -- no roll-up, no normalization anywhere in the build.
"""
from __future__ import annotations

import re
from dataclasses import dataclass

import pandas as pd

from askslm.cohort import Accession, key_column
from askslm.ports import Database
from askslm.sources import ProfilerFamily, Source
from askslm.taxonomy import lineage_table


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
    """Pulls ONE profile source, restricted to the cohort. Columns are its profiling unit.

    STAT is read differently from the Metalog sources, and deliberately. Its table has
    13.6 BILLION rows and no biosample column, so it is only ever filtered by `acc` --
    its own key. `duckdb_indexes()` shows the table has no index at all, so this filter
    is a full scan; the cohort's biosamples are resolved to
    run accessions through sra_metadata first, which is small by comparison (39M rows).
    That works precisely because a STAT biom column is a run (HLD B.3); nothing needs
    the huge table to know about biosamples.
    """

    def __init__(self, database: Database):
        self._database = database

    def read(self, source: Source, accessions: frozenset[Accession]) -> ProfileMatrix:
        rows = self._database.query(*self._query(source, accessions))
        if rows.empty:
            return ProfileMatrix(pd.DataFrame(), pd.DataFrame(), {})
        return _matrix_of(source, self._with_biosample(source, rows))

    def _query(self, source: Source, accessions: frozenset[Accession]) -> tuple[str, list]:
        spec = source.spec()
        if spec.column_id == "acc":
            return (f"SELECT t.* FROM {spec.table} t WHERE t.acc IN "
                    f"({_RUNS_OF_BIOSAMPLES})", [sorted(accessions)])
        return (f"SELECT * FROM {spec.table} "
                f"WHERE {_key_expression(spec.table)} IN (SELECT unnest(?::VARCHAR[]))",
                [sorted(accessions)])

    def _with_biosample(self, source: Source, rows: pd.DataFrame) -> pd.DataFrame:
        """A run-keyed source carries no biosample of its own -- attach it from the runs."""
        if source.spec().column_id != "acc":
            return rows
        runs = self._database.query(
            "SELECT acc, biosample FROM sra_metadata WHERE acc IN (SELECT unnest(?::VARCHAR[]))",
            [sorted(rows["acc"].dropna().unique().tolist())])
        return rows.merge(runs, on="acc", how="left")

    def coverage(self, source: Source, accessions: frozenset[Accession]) -> frozenset[Accession]:
        """Preview count: which cohort biosamples does this source profile at all?

        For STAT this reads `stat_coverage` -- one row per profiled run, precomputed at
        build -- rather than the 13.6B-row table it summarises.
        """
        if source.spec().column_id == "acc":
            rows = self._database.query(
                "SELECT DISTINCT m.biosample FROM sra_metadata m "
                "JOIN stat_coverage c ON c.acc = m.acc "
                "WHERE m.biosample IN (SELECT unnest(?::VARCHAR[]))", [sorted(accessions)])
        else:
            rows = self._database.query(
                f"SELECT DISTINCT biosample FROM {source.spec().table} "
                f"WHERE biosample IN (SELECT unnest(?::VARCHAR[]))", [sorted(accessions)])
        return frozenset(Accession(key) for key in rows["biosample"].dropna())


# Cohort biosamples -> their run accessions. The only bridge STAT needs.
_RUNS_OF_BIOSAMPLES = ("SELECT acc FROM sra_metadata "
                       "WHERE biosample IN (SELECT unnest(?::VARCHAR[]))")


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


# MetaPhlAn / mOTUs rank prefixes. Verified against the real Metalog files: clade_name
# holds ONE rank per row (k__Bacteria, c__Actinomycetia, s__…, t__SGB1871) with no
# ancestry and no pipe separator -- the design's "full lineage phylum→strain" is wrong
# for this table. So rank and name are parsed out, exactly as STAT reads its own columns.
_RANK_PREFIXES = {
    "k": "kingdom", "p": "phylum", "c": "class", "o": "order",
    "f": "family", "g": "genus", "s": "species", "t": "strain",
}
_PREFIXED_CLADE = re.compile(r"^([kpcofgst])__(.*)$")


def _lineage_of(source: Source, rows: pd.DataFrame) -> pd.DataFrame:
    """Feature metadata: name + rank per feature. Never merged with sample metadata.

    STAT gets full ancestry from ete3 (see _ncbi_lineage). MetaPhlAn/mOTUs still get one
    rank per row without parents -- their `clade_name` carries no ancestry, and the
    metaphlan_clades crosswalk that would supply it is roadmap, not built.
    """
    spec = source.spec()
    if spec.lineage_column is None:
        return _ncbi_lineage(rows[spec.feature_column])
    lineage = _parsed_clades(rows[spec.lineage_column].astype(str))
    lineage.index = rows[spec.feature_column].astype(str)
    return lineage[~lineage.index.duplicated()]


def _ncbi_lineage(tax_ids: pd.Series) -> pd.DataFrame:
    """STAT features ARE NCBI tax_ids, so every label is re-derived from ete3's CURRENT
    taxonomy -- name, rank, and the full ancestry the table cannot give us.

    Deliberately NOT sra_taxonomy's own `name`/`rank` columns. STAT's taxonomy is a
    snapshot that lags NCBI, which renames and restructures between releases
    (Firmicutes -> Bacillota, Bacteroides -> Phocaeicola, and the nested-set bounds shift
    with it). Reading those columns shipped outdated names into the biom. The tax_id is
    the stable key; nothing else in that table is trustworthy.
    """
    lineage = lineage_table(tax_ids.unique())
    lineage.index = lineage.index.astype(str)
    return lineage


def _parsed_clades(clades: pd.Series) -> pd.DataFrame:
    """`c__Actinomycetia` -> name Actinomycetia, rank class. Unprefixed names pass through.

    mOTUs species strings carry no rank prefix, so they keep the whole string as the name
    and get no rank -- which is honest: every mOTUs row IS a species-level mOTU.
    """
    parsed = clades.str.extract(_PREFIXED_CLADE)
    names = parsed[1].fillna(clades)
    ranks = parsed[0].map(_RANK_PREFIXES).astype(object)
    ranks = ranks.where(ranks.notna(), None)      # None, not NaN -- this lands in biom JSON
    return pd.DataFrame({"name": names.values, "rank": ranks.values, "clade": clades.values})


def _column_ids(spec, rows: pd.DataFrame) -> pd.Series:
    """The column-id rule: a column is the unit that was profiled. For a sample-keyed
    source that is the biosample, falling back to sample_alias for the orphan tail; for
    a run-keyed source (STAT) it is the run accession itself."""
    if spec.column_id == "biosample":
        return rows["_biosample"]
    return rows[spec.column_id]


def _key_expression(table: str) -> str:
    return "coalesce(biosample, sample_alias)" if table.startswith("metalog_") else "biosample"
