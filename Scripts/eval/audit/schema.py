"""Single source of truth for the audit index.csv columns -- used by the writer,
the staleness checker, and the report generator so they can't drift from each
other. One row = one verification run of one question (append-only, see
record_run.py), not one row per question."""
from __future__ import annotations

COLUMNS = (
    "question_id", "run_id", "checked_at", "trigger_reason",
    "question",
    "plan_path", "generated_sql_path", "results_path", "result_row_count",
    "gold_sql_path", "gold_version",
    # Set-overlap scorecard against gold.sql -- blank when the question has no single
    # gold answer to compare against (ambiguous phrasing, capability-boundary tests).
    # generated_count is always the primary metadata source's count (the one gold.sql
    # targets), not the multi-source result_row_count dict.
    "gold_count", "generated_count", "overlap_count",
    "judgment", "judgment_reasoning", "judgment_reference",
    "missed_what", "missed_link", "why_missed",
    "needs_researcher_confirmation", "confirmation_note",
    "verified_mirror_build", "verified_code_commit",
)


def new_row(**fields: str) -> dict[str, str]:
    """Every column present, defaulting to "" -- a partial row never silently
    drops a column the writer or report expects to find."""
    unknown = set(fields) - set(COLUMNS)
    if unknown:
        raise ValueError(f"not a real column: {sorted(unknown)}")
    return {column: str(fields.get(column, "")) for column in COLUMNS}
