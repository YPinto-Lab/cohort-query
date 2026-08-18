"""Rendering is pure so it can be tested without driving a terminal."""
import askslm
from askslm.cli.render import narrow_warning, preview_line, overlap_rows
from askslm.plan import CohortPreview


def _preview() -> CohortPreview:
    return CohortPreview(
        by_metadata_source={askslm.Source.SRA_METADATA: 380,
                            askslm.Source.METALOG_METADATA: 207},
        shared=175, union=412,
        by_profile_source={askslm.Source.SRA_TAXONOMY: 380,
                           askslm.Source.METALOG_METAPHLAN4_ALL: 228})


def test_the_preview_line_leads_with_the_cohort_size():
    """HLD C.0: one line, cohort size first, then per-family coverage."""
    line = preview_line(_preview())

    assert line.startswith("412 biosamples")
    assert "228" in line


def test_a_narrow_cohort_is_warned_about():
    """A plain threshold, not a model judgement -- 12 samples is usually a mistake
    the user wants to see before spending the expensive run()."""
    assert narrow_warning(CohortPreview(union=12)) is not None
    assert narrow_warning(_preview()) is None


def test_overlap_rows_name_the_winner_of_the_shared_partition():
    """The trust screen: the user must be able to see WHICH source won the samples
    that appear in both databases."""
    rows = overlap_rows(_preview(), winner=askslm.Source.METALOG_METADATA)

    labels = [row[0] for row in rows]
    assert "shared" in labels
    assert any("METALOG_METADATA" in str(row) for row in rows)
