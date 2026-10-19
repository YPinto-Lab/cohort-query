"""Renders index.csv into a static, grouped-by-question HTML view -- entirely
regenerated every time, never hand-edited."""
from __future__ import annotations

import csv
import html
from collections import defaultdict
from pathlib import Path

_JUDGMENT_CLASS = {"MATCH": "match", "PARTIAL": "partial", "MISMATCH": "mismatch"}

# index.csv stores sidecar paths relative to the repo root (run_question.py's --question-dir
# is always "Scripts/eval/audit/qNN-.../"), but report.html itself lives inside that same
# Scripts/eval/audit/ directory -- a raw repo-root-relative href doubles the prefix and 404s.
# Stripping it makes the link relative to report.html's own location instead.
_REPORT_DIR_PREFIX = "Scripts/eval/audit/"


def _relative_href(stored_path: str) -> str:
    if stored_path.startswith(_REPORT_DIR_PREFIX):
        return stored_path[len(_REPORT_DIR_PREFIX):]
    return stored_path


def render(csv_path: Path, out_path: Path) -> None:
    out_path.write_text(_page(_grouped_by_question(csv_path)))


def _grouped_by_question(csv_path: Path) -> dict[str, list[dict]]:
    grouped = defaultdict(list)
    with csv_path.open() as fh:
        for row in csv.DictReader(fh):
            grouped[row["question_id"]].append(row)
    for runs in grouped.values():
        runs.sort(key=lambda row: row["checked_at"])
    return grouped


def _page(by_question: dict[str, list[dict]]) -> str:
    sections = "\n".join(_question_section(question_id, runs)
                          for question_id, runs in sorted(by_question.items()))
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>CohortQuery translation accuracy audit</title>
<style>
  body{{font:14px/1.5 -apple-system,sans-serif;max-width:1000px;margin:24px auto;padding:0 16px}}
  table{{border-collapse:collapse;width:100%;margin:8px 0 28px}}
  th,td{{border-bottom:1px solid #ddd;padding:6px 10px;text-align:left;vertical-align:top}}
  .match{{background:#d1fae5}}.partial{{background:#fef3c7}}.mismatch{{background:#fee2e2}}
</style></head><body>
<h1>Translation accuracy audit</h1>
{sections}
</body></html>"""


def _question_section(question_id: str, runs: list[dict]) -> str:
    question_text = html.escape(runs[0]["question"])
    rows = "\n".join(_run_row(row) for row in runs)
    return f"""<h2>{html.escape(question_id)}</h2><p>{question_text}</p>
<table>
<tr><th>checked_at</th><th>trigger</th><th>judgment</th><th>gold_version</th><th>plan</th><th>sidecars</th></tr>
{rows}
</table>"""


def _run_row(row: dict) -> str:
    judgment_class = _JUDGMENT_CLASS.get(row["judgment"], "")
    return f"""<tr class="{judgment_class}">
<td>{html.escape(row['checked_at'])}</td>
<td>{html.escape(row['trigger_reason'])}</td>
<td>{html.escape(row['judgment'])}</td>
<td>{html.escape(row['gold_version'])}</td>
<td><a href="{html.escape(row['plan_path'])}">plan</a></td>
<td><a href="{html.escape(_relative_href(row['generated_sql_path']))}">sql</a> &middot;
    <a href="{html.escape(_relative_href(row['results_path']))}">results</a></td>
</tr>"""
