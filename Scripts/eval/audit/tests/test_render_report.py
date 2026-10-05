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
