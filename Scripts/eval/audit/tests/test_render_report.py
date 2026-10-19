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
    assert 'class="match"' in content
    assert 'class="partial"' in content


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
