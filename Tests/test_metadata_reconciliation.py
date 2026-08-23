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

from askslm.cohort import Accession, Cohort
from askslm.metadata import MetadataReconciler
from askslm.sources import Source


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
