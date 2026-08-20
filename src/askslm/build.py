"""discover -> reconcile -> assemble. What run() drives."""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import biom
import pandas as pd

from askslm.cohort import Accession, Cohort, CohortDiscovery
from askslm.metadata import MetadataReconciler, ReconciledMetadata
from askslm.profiles import ProfileMatrix, ProfileReconciler, one_family
from askslm.sources import ProfilerFamily, Source, SourceKind


@dataclass(frozen=True)
class Materialization:
    """The run() choices, grouped and validated on construction."""
    profile_sources: tuple[Source, ...]        # head first; all one ProfilerFamily
    metadata_winning_source: Source

    def __post_init__(self):
        if not self.profile_sources:
            raise ValueError("profile_sources must name at least one source")
        if any(source.kind() is not SourceKind.PROFILE for source in self.profile_sources):
            raise ValueError("every profile source must be a PROFILE source")
        if self.metadata_winning_source.kind() is not SourceKind.METADATA:
            raise ValueError("metadata winner must be a METADATA source")
        one_family(self.profile_sources)       # raises on a cross-family list

    def head(self) -> Source:
        return self.profile_sources[0]

    def family(self) -> ProfilerFamily:
        return one_family(self.profile_sources)


@dataclass(frozen=True)
class BuildReport:
    """What run() actually built. Emitted as a value so nothing writes to stdout."""
    family: ProfilerFamily
    columns: int
    biosamples: int
    features: int
    dropped: frozenset[Accession]

    def __str__(self) -> str:
        return (f"family {self.family.value} · {self.features} features × {self.columns} columns "
                f"({self.biosamples} biosamples) · {len(self.dropped)} dropped")


def dropped(requested: frozenset[Accession], present: frozenset[Accession]) -> frozenset[Accession]:
    return requested - present


def _json_safe(frame: pd.DataFrame) -> pd.DataFrame:
    """Missing values become null, not NaN.

    `NaN` is not valid JSON. Python and biom both emit it happily and read it back, so
    this is invisible from Python -- but a strict parser (R's jsonlite, most non-Python
    tooling) rejects the file. Since a .biom is the product's entire output, and metadata
    is sparse by nature (a sample missing `bmi`, a mOTUs feature having no rank), this
    would have hit almost every real file.
    """
    return frame.astype(object).where(frame.notna(), None)


def _noop_step(label: str) -> None:
    pass


class BiomFactory:
    """Assembles the biom: counts, lineage on the feature axis, metadata on the sample axis.

    Written fresh -- the pre-pivot package never built a biom.Table. Serialization is
    biom JSON because HDF5 cannot round-trip nested lineage metadata.
    """

    def build(self, matrix: ProfileMatrix, metadata: ReconciledMetadata) -> biom.Table:
        table = biom.Table(matrix.counts.values,
                           observation_ids=[str(feature) for feature in matrix.counts.index],
                           sample_ids=[str(column) for column in matrix.counts.columns])
        table.add_metadata(self._feature_metadata(matrix), axis="observation")
        table.add_metadata(self._sample_metadata(matrix, metadata), axis="sample")
        return table

    def _feature_metadata(self, matrix: ProfileMatrix) -> dict:
        return {str(feature): row
                for feature, row in _json_safe(matrix.lineage).to_dict("index").items()}

    def _sample_metadata(self, matrix: ProfileMatrix, metadata: ReconciledMetadata) -> dict:
        """Each column carries its own id AND its biosample, so a STAT biom's run columns
        stay groupable by sample without the tool having grouped them (B.3)."""
        rows = _json_safe(metadata.frame).to_dict("index")
        return {column: {**rows.get(biosample, {}), "biosample": biosample, "column_id": column}
                for column, biosample in matrix.column_biosample.items()}


class CohortBuilder:
    def __init__(self, discovery: CohortDiscovery, profiles: ProfileReconciler,
                 metadata: MetadataReconciler, factory: BiomFactory):
        self._discovery = discovery
        self._profiles = profiles
        self._metadata = metadata
        self._factory = factory

    def build(self, queries, request: Materialization, out: Path | None,
              on_step: Callable[[str], None] | None = None) -> tuple[biom.Table, BuildReport]:
        step = on_step or _noop_step
        step("discovering cohort")
        cohort = self._discovery.discover(queries)
        step("reading profile matrix")
        matrix = self._profiles.read(request.profile_sources, cohort.union())
        step("assembling and writing biom")
        metadata = self._metadata.reconciled(cohort, request.metadata_winning_source)
        table = self._factory.build(matrix, metadata.restricted_to(matrix.biosamples()))
        return self._written(table, out), self._report(request, cohort, matrix)

    def _written(self, table: biom.Table, out: Path | None) -> biom.Table:
        if out is not None:
            Path(out).write_text(table.to_json("askslm"))
        return table

    def _report(self, request: Materialization, cohort: Cohort,
                matrix: ProfileMatrix) -> BuildReport:
        return BuildReport(family=request.family(),
                           columns=len(matrix.columns()),
                           biosamples=len(matrix.biosamples()),
                           features=len(matrix.counts.index),
                           dropped=dropped(cohort.union(), matrix.biosamples()))
