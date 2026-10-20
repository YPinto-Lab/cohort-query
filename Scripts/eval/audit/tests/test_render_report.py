import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from render_report import render
from schema import COLUMNS, new_row


def test_render_groups_runs_under_one_question_and_color_codes_judgment(tmp_path):
    csv_path = tmp_path / "index.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(new_row(
            question_id="q01", run_id="r1", question="stool samples from IBD adults",
            checked_at="2026-10-05T00:00:00", trigger_reason="initial", judgment="MATCH",
            gold_version="1", plan_path="/private/pinto-lab/plans/x/plan.json",
            generated_sql_path="q01/runs/r1/generated.sql", results_path="q01/runs/r1/results.csv"))
        writer.writerow(new_row(
            question_id="q01", run_id="r2", question="stool samples from IBD adults",
            checked_at="2026-11-01T00:00:00", trigger_reason="mirror_rebuild", judgment="PARTIAL",
            gold_version="1", plan_path="/private/pinto-lab/plans/y/plan.json",
            generated_sql_path="q01/runs/r2/generated.sql", results_path="q01/runs/r2/results.csv"))
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert content.count("q01") >= 1
    assert "2026-10-05T00:00:00" in content and "2026-11-01T00:00:00" in content
    assert 'badge match">MATCH' in content
    assert 'badge partial">PARTIAL' in content


def test_summary_counts_reflect_latest_run_per_question(tmp_path):
    """The actual pain point: the old report had no overview at all -- just a flat
    list. A reader needs totals by judgment (based on each question's LATEST run,
    not every historical run) before diving into individual questions."""
    csv_path = tmp_path / "index.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        # q01: superseded PARTIAL -> latest is MATCH
        writer.writerow(new_row(
            question_id="q01", run_id="r1", question="q one",
            checked_at="2026-10-05T00:00:00", trigger_reason="initial", judgment="PARTIAL",
            gold_version="1", plan_path="/x/plan.json",
            generated_sql_path="Scripts/eval/audit/q01/runs/r1/generated.sql",
            results_path="Scripts/eval/audit/q01/runs/r1/results.csv"))
        writer.writerow(new_row(
            question_id="q01", run_id="r2", question="q one",
            checked_at="2026-11-01T00:00:00", trigger_reason="code_change", judgment="MATCH",
            gold_version="1", plan_path="/x/plan.json",
            generated_sql_path="Scripts/eval/audit/q01/runs/r2/generated.sql",
            results_path="Scripts/eval/audit/q01/runs/r2/results.csv"))
        # q02: single MISMATCH run
        writer.writerow(new_row(
            question_id="q02", run_id="r1", question="q two",
            checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MISMATCH",
            gold_version="1", plan_path="/x/plan.json",
            generated_sql_path="Scripts/eval/audit/q02/runs/r1/generated.sql",
            results_path="Scripts/eval/audit/q02/runs/r1/results.csv"))
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "2 questions" in content
    # latest-run tally: 1 MATCH (q01's r2), 0 PARTIAL, 1 MISMATCH (q02) -- PARTIAL's
    # superseded r1 must NOT count toward the total
    import re
    match_count = re.search(r'<span class="num">(\d+)</span>\s*<span class="label">match</span>', content, re.I)
    assert match_count and match_count.group(1) == "1"


def test_judgment_reasoning_is_shown_inline(tmp_path):
    """The other pain point: the actual analysis (why something scored PARTIAL, what
    bug was found) lived only in judgment_reasoning/notes.md, invisible from the
    report itself."""
    csv_path = tmp_path / "index.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(new_row(
            question_id="q04", run_id="r1", question="BMI samples",
            checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
            gold_version="1", plan_path="/x/plan.json",
            generated_sql_path="Scripts/eval/audit/q04/runs/r1/generated.sql",
            results_path="Scripts/eval/audit/q04/runs/r1/results.csv",
            judgment_reasoning="CONFIRMED BUG: host_body_mass_index_sam_s_dpl230 excluded entirely.",
            judgment_reference="Scripts/eval/audit/q04/notes.md"))
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "CONFIRMED BUG: host_body_mass_index_sam_s_dpl230 excluded entirely." in content
    assert 'href="q04/notes.md"' in content


def test_needs_researcher_confirmation_is_flagged(tmp_path):
    csv_path = tmp_path / "index.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(new_row(
            question_id="q05", run_id="r1", question="ambiguous question",
            checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
            gold_version="1", plan_path="/x/plan.json",
            generated_sql_path="Scripts/eval/audit/q05/runs/r1/generated.sql",
            results_path="Scripts/eval/audit/q05/runs/r1/results.csv",
            needs_researcher_confirmation="yes",
            confirmation_note="Is this interpretation defensible?"))
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "Is this interpretation defensible?" in content


def test_list_row_selects_its_detail_panel(tmp_path):
    """Mail-app layout: clicking a list row (identified by data-id) must reveal the
    matching detail panel (id="detail-<question_id>"), and the row's visible title
    must be the human question text, not the slug -- the slug is secondary."""
    csv_path = tmp_path / "index.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(new_row(
            question_id="q07-mouse-gut-metagenome", run_id="r1", question="mouse gut metagenome samples",
            checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MATCH",
            gold_version="1", plan_path="/x/plan.json",
            generated_sql_path="Scripts/eval/audit/q07-mouse-gut-metagenome/runs/r1/generated.sql",
            results_path="Scripts/eval/audit/q07-mouse-gut-metagenome/runs/r1/results.csv"))
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert 'data-id="q07-mouse-gut-metagenome"' in content
    assert "selectQuestion('q07-mouse-gut-metagenome')" in content
    assert 'id="detail-q07-mouse-gut-metagenome"' in content
    assert "mouse gut metagenome samples" in content


def test_list_rows_carry_a_sortable_rank_putting_mismatch_before_match(tmp_path):
    """Mail-app default: most-urgent-first ordering (MISMATCH, then PARTIAL, then
    MATCH), sortable by clicking the column header."""
    csv_path = tmp_path / "index.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(new_row(
            question_id="q_match", run_id="r1", question="a match question",
            checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MATCH",
            gold_version="1", plan_path="/x/plan.json",
            generated_sql_path="Scripts/eval/audit/q_match/runs/r1/generated.sql",
            results_path="Scripts/eval/audit/q_match/runs/r1/results.csv"))
        writer.writerow(new_row(
            question_id="q_mismatch", run_id="r1", question="a mismatch question",
            checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MISMATCH",
            gold_version="1", plan_path="/x/plan.json",
            generated_sql_path="Scripts/eval/audit/q_mismatch/runs/r1/generated.sql",
            results_path="Scripts/eval/audit/q_mismatch/runs/r1/results.csv"))
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    import re
    match_rank = re.search(r'data-id="q_match"\s+data-rank="(\d)_', content).group(1)
    mismatch_rank = re.search(r'data-id="q_mismatch"\s+data-rank="(\d)_', content).group(1)
    assert int(mismatch_rank) < int(match_rank)
    assert "sortList('rank')" in content
    assert "sortList('question')" in content
    assert "sortList('checked')" in content


def test_sidecar_links_are_relative_to_the_report_not_the_repo_root(tmp_path):
    """The actual bug: index.csv stores sidecar paths relative to the repo root
    (e.g. "Scripts/eval/audit/q12.../results.csv"), but report.html itself lives
    inside Scripts/eval/audit/ -- a raw repo-root-relative href doubles that
    prefix and 404s. Links must have the shared "Scripts/eval/audit/" prefix
    stripped so they resolve relative to report.html's own location."""
    csv_path = tmp_path / "index.csv"
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        writer.writerow(new_row(
            question_id="q12", run_id="r1", question="type 2 diabetes",
            checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
            gold_version="1", plan_path="/private/pinto-lab/plans/x/plan.json",
            generated_sql_path="Scripts/eval/audit/q12-type2-diabetes-jattr/runs/r1/generated.sql",
            results_path="Scripts/eval/audit/q12-type2-diabetes-jattr/runs/r1/results.csv"))
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert 'href="q12-type2-diabetes-jattr/runs/r1/results.csv"' in content
    assert 'href="q12-type2-diabetes-jattr/runs/r1/generated.sql"' in content
    assert "Scripts/eval/audit/q12" not in content
