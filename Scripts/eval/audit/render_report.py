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


def _latest(runs: list[dict]) -> dict:
    return runs[-1]  # each question's runs list is already sorted by checked_at ascending


def _page(by_question: dict[str, list[dict]]) -> str:
    ordered = sorted(by_question.items())
    latest_runs = [_latest(runs) for _, runs in ordered]
    sections = "\n".join(_question_section(question_id, runs) for question_id, runs in ordered)
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>CohortQuery translation accuracy audit</title>
<style>
{_CSS}
</style></head><body>
<h1>Translation accuracy audit</h1>
<p class="subtitle">{len(ordered)} questions &middot; {sum(len(r) for _, r in ordered)} verification runs</p>
{_summary(latest_runs)}
{_toc(ordered, latest_runs)}
{sections}
</body></html>"""


def _summary(latest_runs: list[dict]) -> str:
    counts = {"MATCH": 0, "PARTIAL": 0, "MISMATCH": 0}
    flagged = 0
    for row in latest_runs:
        counts[row["judgment"]] = counts.get(row["judgment"], 0) + 1
        if row["needs_researcher_confirmation"] == "yes":
            flagged += 1
    stats = "".join(f"""<div class="stat {_JUDGMENT_CLASS.get(label, '')}">
<span class="num">{count}</span><span class="label">{label.lower()}</span></div>"""
                    for label, count in counts.items())
    stats += f"""<div class="stat flagged"><span class="num">{flagged}</span>
<span class="label">needs input</span></div>"""
    return f'<div class="stats">{stats}</div>'


def _toc(ordered: list[tuple[str, list[dict]]], latest_runs: list[dict]) -> str:
    items = "".join(
        f"""<li><a href="#{html.escape(question_id)}">
<span class="badge {_JUDGMENT_CLASS.get(latest['judgment'], '')}">{html.escape(latest['judgment'])}</span>
{html.escape(question_id)}</a></li>"""
        for (question_id, _), latest in zip(ordered, latest_runs))
    return f'<nav class="toc"><h2>Questions</h2><ul>{items}</ul></nav>'


def _question_section(question_id: str, runs: list[dict]) -> str:
    question_text = html.escape(runs[0]["question"])
    run_blocks = "\n".join(_run_block(row) for row in reversed(runs))
    return f"""<section class="question" id="{html.escape(question_id)}">
<h2>{html.escape(question_id)}</h2><p class="qtext">{question_text}</p>
{run_blocks}
</section>"""


def _run_block(row: dict) -> str:
    judgment_class = _JUDGMENT_CLASS.get(row["judgment"], "")
    reasoning = (f'<p class="reasoning">{html.escape(row["judgment_reasoning"])}</p>'
                 if row["judgment_reasoning"] else "")
    flag = (f'<div class="flag">❓ <strong>Needs input:</strong> {html.escape(row["confirmation_note"])}</div>'
            if row["needs_researcher_confirmation"] == "yes" and row["confirmation_note"] else "")
    links = _links(row)
    return f"""<div class="run">
<div class="meta">
<span class="badge {judgment_class}">{html.escape(row['judgment'])}</span>
<span>{html.escape(row['checked_at'])}</span>
<span>&middot; {html.escape(row['trigger_reason'])}</span>
<span>&middot; gold v{html.escape(row['gold_version'])}</span>
</div>
{reasoning}
{flag}
<div class="links">{links}</div>
</div>"""


def _links(row: dict) -> str:
    parts = [f'<a href="{html.escape(row["plan_path"])}">plan</a>']
    if row["gold_sql_path"]:
        parts.append(f'<a href="{html.escape(_relative_href(row["gold_sql_path"]))}">gold</a>')
    parts.append(f'<a href="{html.escape(_relative_href(row["generated_sql_path"]))}">sql</a>')
    parts.append(f'<a href="{html.escape(_relative_href(row["results_path"]))}">results</a>')
    if row["judgment_reference"]:
        parts.append(f'<a href="{html.escape(_relative_href(row["judgment_reference"]))}">notes</a>')
    return " &middot; ".join(parts)


_CSS = """
  :root{color-scheme:light dark}
  body{font:15px/1.6 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;
       max-width:960px;margin:32px auto;padding:0 20px}
  h1{margin-bottom:4px}
  .subtitle{opacity:.65;margin-top:0;margin-bottom:28px}
  .stats{display:flex;gap:12px;margin-bottom:24px;flex-wrap:wrap}
  .stat{flex:1;min-width:110px;border-radius:10px;padding:14px 16px;text-align:center}
  .stat .num{font-size:26px;font-weight:700;display:block}
  .stat .label{font-size:11px;text-transform:uppercase;letter-spacing:.04em;opacity:.7}
  .stat.match{background:#d1fae5;color:#065f46}
  .stat.partial{background:#fef3c7;color:#92400e}
  .stat.mismatch{background:#fee2e2;color:#991b1b}
  .stat.flagged{background:#ede9fe;color:#5b21b6}
  .toc{border:1px solid rgba(127,127,127,.3);border-radius:10px;padding:14px 18px;margin-bottom:28px}
  .toc h2{font-size:12px;text-transform:uppercase;letter-spacing:.05em;opacity:.65;margin:0 0 10px}
  .toc ul{list-style:none;margin:0;padding:0;display:grid;
          grid-template-columns:repeat(auto-fill,minmax(230px,1fr));gap:6px 18px}
  .toc a{text-decoration:none;color:inherit;font-size:13px}
  .badge{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;
         text-transform:uppercase;letter-spacing:.03em;margin-right:6px;vertical-align:middle}
  .badge.match{background:#10b981;color:#fff}
  .badge.partial{background:#f59e0b;color:#fff}
  .badge.mismatch{background:#ef4444;color:#fff}
  .question{border:1px solid rgba(127,127,127,.3);border-radius:10px;padding:18px 22px;margin-bottom:18px}
  .question h2{margin:0 0 2px;font-size:17px}
  .qtext{opacity:.75;margin:0 0 14px}
  .run{border-top:1px solid rgba(127,127,127,.2);padding-top:12px;margin-top:12px}
  .run:first-of-type{border-top:none;padding-top:0;margin-top:0}
  .meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;opacity:.75;margin-bottom:6px}
  .reasoning{margin:6px 0;font-size:14px}
  .flag{background:#ede9fe;border-left:3px solid #8b5cf6;padding:8px 12px;border-radius:6px;
        font-size:13px;margin:8px 0}
  .links a{margin-right:4px;font-size:13px}
"""
