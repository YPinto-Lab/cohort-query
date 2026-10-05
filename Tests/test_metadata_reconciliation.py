"""MetadataReconciler must never blend in a row from a source that never confirmed a
given biosample as matching the question. `cohort.by_source[source]` is what a
source's OWN discovery query vetted; reading against `cohort.union()` instead lets an
unrelated row -- present in that source's raw table for an entirely different reason,
never checked against this question's criteria -- sneak in via combine_first even when
Cohort.shared() == 0. Found on a real cohort: plan.preview said shared=0 (SRA_METADATA
and METALOG_METADATA matched completely disjoint biosample sets), yet the built biom
had 15,729 columns carrying real data from BOTH sources.
"""
import pandas as pd

from cohortquery.cohort import Accession, Cohort
from cohortquery.metadata import MetadataReconciler
from cohortquery.sources import Source


class _FakeReader:
    def __init__(self, frames: dict[Source, pd.DataFrame]):
        self._frames = frames

    def read(self, source, accessions):
        frame = self._frames[source]
        return frame.loc[[key for key in frame.index if key in accessions]]


def test_an_unconfirmed_row_never_leaks_into_a_disjoint_cohort():
    """SAMN1 was discovered ONLY by SRA_METADATA's query -- it never appears in
    METALOG_METADATA's by_source set, so Cohort.shared() is empty. But
    metalog_metadata's raw table happens to have a row for SAMN1 anyway (an
    unrelated study that never satisfied metalog's own discovery criteria). That
    row must never appear in SAMN1's reconciled metadata."""
    cohort = Cohort({
        Source.SRA_METADATA: frozenset({Accession("SAMN1")}),
        Source.METALOG_METADATA: frozenset({Accession("SAMN2")}),
    })
    assert cohort.shared() == frozenset()      # confirmed disjoint, matching the real incident

    frames = {
        Source.SRA_METADATA: pd.DataFrame({"jattr": ["{}"]}, index=["SAMN1"]),
        Source.METALOG_METADATA: pd.DataFrame(
            {"study_code": ["unrelated_study"]}, index=["SAMN1", "SAMN2"]),
    }
    reconciled = MetadataReconciler(_FakeReader(frames)).reconciled(cohort, Source.METALOG_METADATA)

    assert "study_code" not in reconciled.columns_for(Accession("SAMN1"))
    assert pd.isna(reconciled.frame.loc["SAMN1", "study_code"])
    assert reconciled.frame.loc["SAMN2", "study_code"] == "unrelated_study"   # SAMN2's own row is real


def test_a_genuinely_shared_biosample_still_gets_both_sources_blended():
    """The fix must not become 'never combine anything' -- a biosample confirmed by
    BOTH discovery queries should still get combine_first's winner-wins-gaps-filled
    behavior."""
    cohort = Cohort({
        Source.SRA_METADATA: frozenset({Accession("SAMN1")}),
        Source.METALOG_METADATA: frozenset({Accession("SAMN1")}),
    })
    assert cohort.shared() == frozenset({Accession("SAMN1")})

    frames = {
        Source.SRA_METADATA: pd.DataFrame({"jattr": ["{}"], "sex": [None]}, index=["SAMN1"]),
        Source.METALOG_METADATA: pd.DataFrame({"sex": ["female"]}, index=["SAMN1"]),
    }
    reconciled = MetadataReconciler(_FakeReader(frames)).reconciled(cohort, Source.METALOG_METADATA)

    assert reconciled.frame.loc["SAMN1", "sex"] == "female"
    assert reconciled.columns_for(Accession("SAMN1")) == frozenset({"jattr", "sex"})


def test_falls_back_when_the_configured_winner_never_ran():
    """prompt.py can now omit a source's query entirely on partial criterion
    coverage (e.g. Metalog has no calprotectin field), so cohort.by_source --
    and therefore frames -- may simply not contain the default winning source.
    Reconciliation must fall back to whatever metadata source did run instead
    of KeyError-ing on `frames[winning_source]`."""
    cohort = Cohort({Source.SRA_METADATA: frozenset({Accession("SAMN1")})})
    frames = {Source.SRA_METADATA: pd.DataFrame({"jattr": ["{}"]}, index=["SAMN1"])}

    reconciled = MetadataReconciler(_FakeReader(frames)).reconciled(
        cohort, Source.METALOG_METADATA)

    assert reconciled.frame.loc["SAMN1", "jattr"] == "{}"


def _three_way_frames() -> dict[Source, pd.DataFrame]:
    """SAMN1 matched only SRA, SAMN2 matched both, SAMN3 only Metalog -- the three
    provenance cases in one fixture."""
    return {
        Source.SRA_METADATA: pd.DataFrame(
            {"attributes": [[{"k": "bmi_sam", "v": "22.5"}], [{"k": "bmi_sam", "v": "30.1"}]]},
            index=["SAMN1", "SAMN2"]),
        Source.METALOG_METADATA: pd.DataFrame(
            {"subject_disease_status": ["IBD", "healthy"]}, index=["SAMN2", "SAMN3"]),
    }


def _three_way_cohort() -> Cohort:
    return Cohort({
        Source.SRA_METADATA: frozenset(Accession(a) for a in ["SAMN1", "SAMN2"]),
        Source.METALOG_METADATA: frozenset(Accession(a) for a in ["SAMN2", "SAMN3"]),
    })


def test_covering_columns_records_which_source_actually_backed_each_row():
    """`columns_for` is what lets the biom writer tell "never looked up" apart from
    "looked up and empty". combine_first unions BOTH sources' columns onto every row,
    so without this a biosample only SRA matched still carries Metalog's whole schema
    as explicit nulls. Each row must report only the columns a source really vetted
    it against."""
    reconciled = MetadataReconciler(_FakeReader(_three_way_frames())).reconciled(
        _three_way_cohort(), Source.METALOG_METADATA)

    assert reconciled.columns_for(Accession("SAMN1")) == frozenset({"attributes"})
    assert reconciled.columns_for(Accession("SAMN2")) == frozenset(
        {"attributes", "subject_disease_status"})
    assert reconciled.columns_for(Accession("SAMN3")) == frozenset({"subject_disease_status"})


def test_restricted_to_carries_provenance_forward_and_forgets_dropped_rows():
    """`restricted_to` narrows the cohort late (a profile source covers fewer samples
    than discovery found). It must carry each surviving row's provenance with it --
    otherwise the biom writer loses the ability to drop foreign schema -- and must
    report None, not a stale set, for a row it dropped."""
    reconciled = MetadataReconciler(_FakeReader(_three_way_frames())).reconciled(
        _three_way_cohort(), Source.METALOG_METADATA)

    narrowed = reconciled.restricted_to(frozenset({Accession("SAMN1"), Accession("SAMN3")}))

    assert narrowed.columns_for(Accession("SAMN1")) == frozenset({"attributes"})
    assert narrowed.columns_for(Accession("SAMN3")) == frozenset({"subject_disease_status"})
    assert narrowed.columns_for(Accession("SAMN2")) is None
    assert list(narrowed.frame.index) == ["SAMN1", "SAMN3"]
