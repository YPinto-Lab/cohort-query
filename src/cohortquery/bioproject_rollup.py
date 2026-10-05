"""The discovered cohort, grouped by project, with each jattr criterion's own
standalone reach broken out per project -- the "explain" the design settled on:
never intersect/union away a criterion silently, always show which project
satisfies which criterion and on what actual key/value.

A join across two metadata sources (SRA's bioproject, Metalog's study_code for
biosamples SRA never saw), so it is a Processor, not an Accessor (CLAUDE.md:
"Accessors read exactly one source; joins belong in Processors").
"""
from __future__ import annotations

from dataclasses import dataclass

import pandas as pd

from cohortquery.accession import Accession
from cohortquery.cohort import Cohort
from cohortquery.ports import Database

UNKNOWN_PROJECT = "(unknown project)"


@dataclass(frozen=True)
class CriterionCount:
    concept: str
    biosample_count: int
    matched_on: tuple[str, ...]      # distinct keys/values this project's samples matched on


@dataclass(frozen=True)
class ProjectRow:
    project: str
    biosample_count: int
    criteria: tuple[CriterionCount, ...]     # every jattr criterion, standalone, always shown


class BioProjectRollup:
    def __init__(self, database: Database):
        self._database = database

    def rows(self, cohort: Cohort) -> list[ProjectRow]:
        biosamples = cohort.union()
        if not biosamples:
            return []
        project_of = self._project_of(biosamples)
        by_project = _grouped_by_project(biosamples, project_of)
        matches_by_concept = _matches_by_concept(cohort)
        rows = [self._row(project, members, matches_by_concept)
               for project, members in by_project.items()]
        return sorted(rows, key=_by_size_desc)

    def filter_to_projects(self, cohort: Cohort, projects: frozenset[str]) -> Cohort:
        """The multi-select's result applied: keep only biosamples whose project
        is one the researcher checked. jattr_matches is left untouched -- it
        describes what discovery FOUND, not what was ultimately kept."""
        biosamples = cohort.union()
        project_of = self._project_of(biosamples)
        keep = frozenset(sample for sample in biosamples
                         if project_of.get(sample, UNKNOWN_PROJECT) in projects)
        by_source = {source: keys & keep for source, keys in cohort.by_source.items()}
        return Cohort(by_source, cohort.jattr_matches)

    def _row(self, project: str, members: set[Accession],
            matches_by_concept: dict[str, list]) -> ProjectRow:
        criteria = tuple(self._criterion_count(concept, members, matches)
                         for concept, matches in matches_by_concept.items())
        return ProjectRow(project, len(members), criteria)

    def _criterion_count(self, concept: str, members: set[Accession], matches: list) -> CriterionCount:
        in_project = [match for match in matches if match.biosamples & members]
        count = len(members & frozenset().union(*(match.biosamples for match in in_project))) \
            if in_project else 0
        matched_on = tuple(sorted({match.matched_on for match in in_project}))
        return CriterionCount(concept, count, matched_on)

    def _project_of(self, biosamples: frozenset[Accession]) -> dict[Accession, str]:
        project_of = self._sra_bioprojects(biosamples)
        remaining = biosamples - project_of.keys()
        project_of.update(self._metalog_study_codes(remaining))
        return project_of

    def _sra_bioprojects(self, biosamples: frozenset[Accession]) -> dict[Accession, str]:
        rows = self._database.query(
            "SELECT biosample, bioproject FROM sra_metadata "
            "WHERE biosample IN (SELECT unnest(?::VARCHAR[])) AND bioproject IS NOT NULL",
            [sorted(biosamples)])
        return _label_map(rows, "biosample", "bioproject")

    def _metalog_study_codes(self, biosamples: frozenset[Accession]) -> dict[Accession, str]:
        if not biosamples:
            return {}
        rows = self._database.query(
            "SELECT coalesce(biosample, sample_alias) AS accession, study_code "
            "FROM metalog_metadata WHERE coalesce(biosample, sample_alias) "
            "IN (SELECT unnest(?::VARCHAR[])) AND study_code IS NOT NULL",
            [sorted(biosamples)])
        return _label_map(rows, "accession", "study_code")


def _label_map(rows: pd.DataFrame, key_column: str, label_column: str) -> dict[Accession, str]:
    return {Accession(key): label for key, label in zip(rows[key_column], rows[label_column])}


def _grouped_by_project(biosamples: frozenset[Accession], project_of: dict[Accession, str]
                        ) -> dict[str, set[Accession]]:
    by_project: dict[str, set[Accession]] = {}
    for sample in biosamples:
        project = project_of.get(sample, UNKNOWN_PROJECT)
        by_project.setdefault(project, set()).add(sample)
    return by_project


def _matches_by_concept(cohort: Cohort) -> dict[str, list]:
    """Flattened across every source's queries -- a concept is not expected to
    repeat across sources, but this must not silently drop it if it ever does."""
    flattened: dict[str, list] = {}
    for source_matches in cohort.jattr_matches.values():
        for concept, matches in source_matches.items():
            flattened.setdefault(concept, []).extend(matches)
    return flattened


def _by_size_desc(row: ProjectRow) -> int:
    return -row.biosample_count
