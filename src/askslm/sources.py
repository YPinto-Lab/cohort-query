"""The flat source model: one DuckDB table is one Source.

Adding a database, metadata set, or profiler means adding one member here and
nothing else. Table names are the mirror's, verified against
Scripts/build_mirror/build_duckdb.py.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SourceKind(Enum):
    METADATA = "metadata"          # reconcilable across sources, per field
    PROFILE = "profile"            # feeds counts; lives in a ProfilerFamily


class ProfilerFamily(Enum):
    """Sources sharing BOTH a feature namespace and an abundance estimator.

    That is what makes their values comparable, and why STAT (read-count) and
    METAPHLAN (coverage) never share a biom even though both use NCBI taxonomy.
    """
    STAT = "stat"                  # NCBI tax_id, read count -- sequence abundance
    METAPHLAN = "metaphlan"        # NCBI clade, coverage -- cell abundance
    MOTUS = "motus"                # mOTU id, coverage -- cell abundance


class Unit(Enum):
    COUNTS = "counts"
    RELATIVE = "relative"


@dataclass(frozen=True)
class SourceSpec:
    database: str                          # provenance: "sra" | "metalog"
    table: str
    kind: SourceKind
    family: ProfilerFamily | None = None
    unit: Unit | None = None
    feature_column: str | None = None      # the feature id in the table
    value_column: str | None = None        # the abundance, at its native meaning
    lineage_column: str | None = None      # None on STAT: its lineage is DERIVED from tax_id
    column_id: str = "biosample"           # what ONE BIOM COLUMN is for this source (B.3)


class Source(Enum):
    SRA_METADATA = SourceSpec("sra", "sra_metadata", SourceKind.METADATA)
    METALOG_METADATA = SourceSpec("metalog", "metalog_metadata", SourceKind.METADATA)

    # STAT profiles are computed per RUN, so a STAT biom column is a run (B.3).
    SRA_TAXONOMY = SourceSpec("sra", "sra_taxonomy", SourceKind.PROFILE,
                              ProfilerFamily.STAT, Unit.COUNTS,
                              feature_column="tax_id", value_column="self_count",
                              lineage_column=None, column_id="acc")
    METALOG_METAPHLAN4_ALL = SourceSpec("metalog", "metalog_metaphlan4", SourceKind.PROFILE,
                                        ProfilerFamily.METAPHLAN, Unit.RELATIVE,
                                        feature_column="clade_name", value_column="rel_abund",
                                        lineage_column="clade_name")
    METALOG_MOTUS3 = SourceSpec("metalog", "metalog_motus3", SourceKind.PROFILE,
                                ProfilerFamily.MOTUS, Unit.RELATIVE,
                                feature_column="species", value_column="rel_abund",
                                lineage_column="species")
    METALOG_SPIRE_MOTUS = SourceSpec("metalog", "metalog_spire_motus", SourceKind.PROFILE,
                                     ProfilerFamily.MOTUS, Unit.RELATIVE,
                                     feature_column="species", value_column="rel_abund",
                                     lineage_column="species")

    def spec(self) -> SourceSpec:
        return self.value

    def kind(self) -> SourceKind:
        return self.value.kind

    def family(self) -> ProfilerFamily | None:
        return self.value.family


def metadata_sources() -> tuple[Source, ...]:
    return tuple(source for source in Source if source.kind() is SourceKind.METADATA)
