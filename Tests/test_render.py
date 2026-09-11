"""Rendering is pure so it can be tested without driving a terminal."""
import askslm
from askslm.bioproject_rollup import CriterionCount, ProjectRow
from askslm.cli.render import (bioproject_choice_label, bioproject_columns,
                               bioproject_table_rows, narrow_warning, preview_line,
                               overlap_rows)
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


def _project_rows() -> list[ProjectRow]:
    return [
        ProjectRow("PRJEB18471", 665, (
            CriterionCount("IBD", 620, ("ibd_sam",)),
            CriterionCount("calprotectin measurement", 45, ("calprotectin_sam",)))),
        ProjectRow("PRJNA1045596", 436, (
            CriterionCount("IBD", 436, ("disease_status_sam",)),
            CriterionCount("calprotectin measurement", 0, ()))),
    ]


def test_bioproject_columns_lists_every_distinct_concept_once():
    columns = bioproject_columns(_project_rows())

    assert columns == ["IBD", "calprotectin measurement"]


def test_bioproject_table_rows_show_each_projects_own_standalone_counts():
    columns = bioproject_columns(_project_rows())

    rows = bioproject_table_rows(_project_rows(), columns)

    assert rows[0] == ("PRJEB18471", "665", "620 (ibd_sam)", "45 (calprotectin_sam)")
    assert rows[1] == ("PRJNA1045596", "436", "436 (disease_status_sam)", "0")


def test_bioproject_choice_label_summarizes_matched_criteria():
    label = bioproject_choice_label(_project_rows()[0])

    assert label.startswith("PRJEB18471 (665 biosamples)")
    assert "IBD: 620" in label
    assert "calprotectin measurement: 45" in label


def test_bioproject_choice_label_omits_criteria_that_did_not_match():
    label = bioproject_choice_label(_project_rows()[1])

    assert "calprotectin measurement" not in label
