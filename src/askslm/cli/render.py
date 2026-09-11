"""Formatting only -- no prompting, no state. Kept separate from session.py so the
parts worth testing do not require driving a terminal."""
from __future__ import annotations

from askslm.bioproject_rollup import CriterionCount, ProjectRow
from askslm.plan import CohortPreview
from askslm.sources import Source

NARROW = 50            # a plain threshold, not a model judgement (HLD C.0.2)


def preview_line(preview: CohortPreview) -> str:
    """`412 biosamples · STAT 380 · METAPHLAN 228 · MOTUS 222`"""
    parts = [f"{preview.union} biosamples"]
    parts += [f"{source.name} {count}"
              for source, count in preview.by_profile_source.items()]
    return " · ".join(parts)


def narrow_warning(preview: CohortPreview) -> str | None:
    if preview.union >= NARROW:
        return None
    return f"{preview.union} samples -- narrow. Try widening the question."


def overlap_rows(preview: CohortPreview, winner: Source) -> list[tuple[str, str, str]]:
    """The trust screen (HLD C.1.3): who has which samples, and who wins the overlap."""
    counts = preview.by_metadata_source
    rows = [(source.name, str(count), "") for source, count in counts.items()]
    rows.append(("shared", str(preview.shared), f"<- {winner.name} wins these"))
    return rows


def bioproject_columns(rows: list[ProjectRow]) -> list[str]:
    """Ordered, de-duplicated concept names across every row -- the per-criterion
    column headers, since every row must show the same columns."""
    seen: list[str] = []
    for row in rows:
        for criterion in row.criteria:
            if criterion.concept not in seen:
                seen.append(criterion.concept)
    return seen


def bioproject_table_rows(rows: list[ProjectRow], columns: list[str]) -> list[tuple[str, ...]]:
    """One row per project: project, biosamples, then one cell per column in
    `columns` -- each criterion's OWN standalone count for that project,
    unconditionally, regardless of how criteria combined into the cohort."""
    return [_table_row(row, columns) for row in rows]


def _table_row(row: ProjectRow, columns: list[str]) -> tuple[str, ...]:
    by_concept = {criterion.concept: criterion for criterion in row.criteria}
    cells = [_criterion_cell(by_concept.get(concept)) for concept in columns]
    return (row.project, str(row.biosample_count), *cells)


def _criterion_cell(criterion: CriterionCount | None) -> str:
    if criterion is None or criterion.biosample_count == 0:
        return "0"
    matched_on = ", ".join(criterion.matched_on)
    return f"{criterion.biosample_count} ({matched_on})"


def bioproject_choice_label(row: ProjectRow) -> str:
    """The multi-select checkbox's per-project title: project, size, and a
    compact summary of which criteria it actually satisfies."""
    summary = ", ".join(f"{criterion.concept}: {criterion.biosample_count}"
                        for criterion in row.criteria if criterion.biosample_count)
    suffix = f" -- {summary}" if summary else ""
    return f"{row.project} ({row.biosample_count} biosamples){suffix}"
