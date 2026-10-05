"""BioProjectRollup: the discovered cohort grouped by project, with every jattr
criterion's own standalone reach shown per project regardless of how the
criteria combined into the final cohort -- the explain design settled on."""
import pandas as pd

from cohortquery.accession import Accession
from cohortquery.bioproject_rollup import UNKNOWN_PROJECT, BioProjectRollup
from cohortquery.cohort import Cohort
from cohortquery.jattr_concepts import JattrMatch
from cohortquery.sources import Source


class _FakeDatabase:
    def __init__(self, sra_rows=(), metalog_rows=()):
        self._sra_rows = sra_rows
        self._metalog_rows = metalog_rows

    def query(self, sql, params=None):
        if "sra_metadata" in sql:
            return pd.DataFrame(self._sra_rows, columns=["biosample", "bioproject"])
        return pd.DataFrame(self._metalog_rows, columns=["accession", "study_code"])


def _match(concept, matched_on, *samples):
    return JattrMatch(concept=concept, matched_on=matched_on,
                      biosamples=frozenset(Accession(s) for s in samples))


def test_biosamples_group_by_sra_bioproject():
    database = _FakeDatabase(sra_rows=[("SAMN001", "PRJEB18471"), ("SAMN002", "PRJEB18471"),
                                       ("SAMN003", "PRJNA999")])
    cohort = Cohort({Source.SRA_METADATA: {Accession("SAMN001"), Accession("SAMN002"),
                                           Accession("SAMN003")}})

    rows = BioProjectRollup(database).rows(cohort)

    by_project = {row.project: row.biosample_count for row in rows}
    assert by_project == {"PRJEB18471": 2, "PRJNA999": 1}


def test_metalog_only_biosamples_fall_back_to_study_code():
    """A biosample SRA never saw groups by Metalog's study_code instead."""
    database = _FakeDatabase(sra_rows=[], metalog_rows=[("MG_ORPHAN_1", "STUDY_0")])
    cohort = Cohort({Source.METALOG_METADATA: {Accession("MG_ORPHAN_1")}})

    rows = BioProjectRollup(database).rows(cohort)

    assert rows == [type(rows[0])(project="STUDY_0", biosample_count=1, criteria=())]


def test_a_biosample_in_neither_source_gets_the_unknown_bucket():
    database = _FakeDatabase(sra_rows=[], metalog_rows=[])
    cohort = Cohort({Source.SRA_METADATA: {Accession("SAMN999")}})

    rows = BioProjectRollup(database).rows(cohort)

    assert rows[0].project == UNKNOWN_PROJECT


def test_empty_cohort_produces_no_rows():
    rows = BioProjectRollup(_FakeDatabase()).rows(Cohort({}))

    assert rows == []


def test_each_criterion_shows_its_own_standalone_count_per_project():
    """The empty-AND explain case: IBD alone and calprotectin alone are both
    visible per project, independent of how they combined into the cohort."""
    database = _FakeDatabase(sra_rows=[("SAMN001", "PRJEB1"), ("SAMN002", "PRJEB1"),
                                       ("SAMN003", "PRJEB2")])
    jattr_matches = {
        Source.SRA_METADATA: {
            "IBD": [_match("IBD", "ibd_sam", "SAMN001", "SAMN002")],
            "calprotectin measurement": [_match("calprotectin measurement",
                                                "calprotectin_sam", "SAMN003")],
        }
    }
    cohort = Cohort({Source.SRA_METADATA: {Accession("SAMN001"), Accession("SAMN002"),
                                           Accession("SAMN003")}},
                    jattr_matches=jattr_matches)

    rows = BioProjectRollup(database).rows(cohort)

    prjeb1 = next(row for row in rows if row.project == "PRJEB1")
    prjeb2 = next(row for row in rows if row.project == "PRJEB2")
    ibd_in_1 = next(c for c in prjeb1.criteria if c.concept == "IBD")
    calpro_in_1 = next(c for c in prjeb1.criteria if c.concept == "calprotectin measurement")
    calpro_in_2 = next(c for c in prjeb2.criteria if c.concept == "calprotectin measurement")
    assert ibd_in_1.biosample_count == 2
    assert ibd_in_1.matched_on == ("ibd_sam",)
    assert calpro_in_1.biosample_count == 0        # neither PRJEB1 sample matched calprotectin
    assert calpro_in_2.biosample_count == 1


def test_rows_are_sorted_by_biosample_count_descending():
    database = _FakeDatabase(sra_rows=[("SAMN001", "SMALL"), ("SAMN002", "BIG"),
                                       ("SAMN003", "BIG")])
    cohort = Cohort({Source.SRA_METADATA: {Accession("SAMN001"), Accession("SAMN002"),
                                           Accession("SAMN003")}})

    rows = BioProjectRollup(database).rows(cohort)

    assert [row.project for row in rows] == ["BIG", "SMALL"]
