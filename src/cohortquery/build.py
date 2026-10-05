"""discover -> reconcile -> assemble. What run() drives."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import biom
import pandas as pd

from cohortquery import checkpoint
from cohortquery.cohort import Accession, Cohort, CriterionResolver
from cohortquery.metadata import MetadataReconciler, ReconciledMetadata
from cohortquery.profiles import ProfileMatrix, ProfileReconciler, one_family
from cohortquery.sources import ProfilerFamily, Source, SourceKind


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
    """Missing values become null, not NaN; timestamps become ISO strings.

    `NaN` is not valid JSON. Python and biom both emit it happily and read it back, so
    this is invisible from Python -- but a strict parser (R's jsonlite, most non-Python
    tooling) rejects the file. Since a .biom is the product's entire output, and metadata
    is sparse by nature (a sample missing `bmi`, a mOTUs feature having no rank), this
    would have hit almost every real file. Likewise, biom's own JSON encoder has no
    special case for `pd.Timestamp` -- some sra_metadata columns carry real datetimes,
    not just date-like strings, and to_json() dies on the first one it meets.
    """
    mask = frame.notna()
    safe = frame.astype(object).map(_json_safe_value).astype(object)
    return safe.where(mask, None)


def _json_safe_value(value):
    return value.isoformat() if isinstance(value, pd.Timestamp) else value


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
        stay groupable by sample without the tool having grouped them (B.3).

        `combine_first` unions both metadata sources' columns onto every row, so a
        biosample that only one source ever matched would otherwise carry the OTHER
        source's entire schema as explicit nulls -- not missing data, a foreign schema
        that was never looked up for this sample. `_restricted_to` drops exactly those.
        """
        rows = _json_safe(metadata.frame).to_dict("index")
        return {column: {**_resolved_by_visit(_flattened(
                             _restricted_to(rows.get(biosample, {}), metadata.columns_for(biosample)))),
                         "biosample": biosample, "column_id": column}
                for column, biosample in matrix.column_biosample.items()}


def _restricted_to(row: dict, columns: frozenset[str] | None) -> dict:
    if columns is None:
        return row
    return {key: value for key, value in row.items() if key in columns}


def _flattened(row: dict) -> dict:
    """SRA's per-run `attributes` (a list of {k, v} pairs) becomes real named fields
    instead of a JSON blob the consumer has to parse themselves. `jattr` carries the
    same data but silently collapses a key with more than one raw value down to just
    the first -- verified against 20,000 real rows, it diverges from `attributes` on
    every row that has `primary_search` -- so `attributes`, the lossless form, is the
    one flattened; `jattr` is just dropped. A key that already exists as a real column
    wins over its attributes-derived namesake."""
    attributes = row.get("attributes")
    if attributes is None or (hasattr(attributes, "__len__") and len(attributes) == 0):
        # duckdb's LIST(STRUCT) column comes back as a numpy.ndarray, not a plain list --
        # `not attributes` on one raises "ambiguous truth value" instead of testing emptiness.
        return {key: value for key, value in row.items() if key not in ("attributes", "jattr")}
    grouped: dict[str, list] = {}
    for pair in attributes:
        grouped.setdefault(pair["k"], []).append(pair["v"])
    flattened = {key: values[0] if len(values) == 1 else values
                for key, values in grouped.items() if key not in row}
    return {**{key: value for key, value in row.items() if key not in ("attributes", "jattr")},
           **flattened}


_VISIT_FIELD = re.compile(r"^(.+?)(\d+)_sam$")


def _resolved_by_visit(row: dict) -> dict:
    """A wide-format longitudinal study exports one row per SUBJECT with one column per
    STUDY VISIT (calprotectin0_sam, calprotectin6_sam, ... calprotectin52_sam), then that
    whole row gets attached to whichever single specimen from that subject was actually
    sequenced. Verified on a real cohort (bioproject PRJNA930767): 49 of 72 biosamples
    carry all six visits' calprotectin values simultaneously, though each biosample is
    exactly one sequenced run of exactly one specimen -- only ONE of those six values was
    ever measured on the material that got profiled. `study_week_sam` says which.

    Never dropped: the other visits are real data about the same subject, just not about
    THIS specimen, and silently discarding them would be a scientific judgement call this
    function has no business making. They are relabeled instead, so nothing described as
    plain `calprotectin_sam` can be mistaken for this specimen's own measurement unless it
    verifiably is.
    """
    study_week = row.get("study_week_sam")
    if study_week is None:
        return row
    by_prefix: dict[str, dict[str, str]] = {}
    for key in row:
        match = _VISIT_FIELD.match(key)
        if match:
            by_prefix.setdefault(match.group(1), {})[match.group(2)] = key

    resolved = dict(row)
    for prefix, weeks in by_prefix.items():
        if len(weeks) < 2:      # a lone numbered field isn't a wide-format collision
            continue
        canonical = f"{prefix}_sam"
        for week, key in weeks.items():
            value = resolved.pop(key)
            if week == str(study_week):
                resolved.setdefault(canonical, value)     # a real column always wins
            else:
                resolved[f"{prefix}_sam__other_visit_week{week}"] = value
    return resolved


class CohortBuilder:
    def __init__(self, discovery: CriterionResolver, profiles: ProfileReconciler,
                 metadata: MetadataReconciler, factory: BiomFactory):
        self._discovery = discovery
        self._profiles = profiles
        self._metadata = metadata
        self._factory = factory

    def build(self, queries, request: Materialization, out: Path | None,
              on_step: Callable[[str], None] | None = None,
              discovered: Cohort | None = None,
              plan_dir: Path | None = None) -> tuple[biom.Table, BuildReport]:
        step = on_step or _noop_step
        cohort = self._discovered(queries, discovered, plan_dir, step)
        step("reading profile matrix")
        matrix = self._matrix(queries, request, cohort, plan_dir)
        step("assembling and writing biom")
        metadata = self._metadata.reconciled(cohort, request.metadata_winning_source)
        table = self._factory.build(matrix, metadata.restricted_to(matrix.biosamples()))
        written = self._written(table, out)
        if plan_dir is not None:
            checkpoint.clear(plan_dir)      # only needed to survive a crash mid-build
        return written, self._report(request, cohort, matrix)

    def _discovered(self, queries, discovered: Cohort | None, plan_dir: Path | None,
                    step: Callable[[str], None]) -> Cohort:
        if discovered is not None:
            step("discovering cohort (cached)")
            return discovered
        step("discovering cohort")
        if plan_dir is None:
            return self._discovery.discover(queries)
        key = checkpoint.cohort_key(queries)
        cached = checkpoint.load_cohort(plan_dir, key)
        if cached is not None:
            return cached
        cohort = self._discovery.discover(queries)
        checkpoint.save_cohort(plan_dir, cohort, key)
        return cohort

    def _matrix(self, queries, request: Materialization, cohort: Cohort,
               plan_dir: Path | None) -> ProfileMatrix:
        if plan_dir is None:
            return self._profiles.read(request.profile_sources, cohort.union())
        key = checkpoint.matrix_key(checkpoint.cohort_key(queries), request.profile_sources)
        cached = checkpoint.load_matrix(plan_dir, key)
        if cached is not None:
            return cached
        matrix = self._profiles.read(request.profile_sources, cohort.union())
        checkpoint.save_matrix(plan_dir, matrix, key)
        return matrix

    def _written(self, table: biom.Table, out: Path | None) -> biom.Table:
        if out is not None:
            out = Path(out)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_text(table.to_json("cohortquery"))
        return table

    def _report(self, request: Materialization, cohort: Cohort,
                matrix: ProfileMatrix) -> BuildReport:
        return BuildReport(family=request.family(),
                           columns=len(matrix.columns()),
                           biosamples=len(matrix.biosamples()),
                           features=len(matrix.counts.index),
                           dropped=dropped(cohort.union(), matrix.biosamples()))
