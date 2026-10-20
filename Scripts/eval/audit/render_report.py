"""Renders index.csv into a static, grouped-by-question HTML view -- entirely
regenerated every time, never hand-edited. Mail-app-style master/detail layout:
a sortable list of questions on the left, full run history on the right.

Sidecars (gold.sql, generated.sql, results.csv, notes.md) are read and embedded
directly in the page rather than linked -- a plain <a href> to a local .csv/.sql/.md
file triggers an OS file-association download in some browsers instead of
displaying anything, so there's nothing reliable to link to."""
from __future__ import annotations

import csv
import html
from collections import defaultdict
from pathlib import Path

import mistune

_JUDGMENT_CLASS = {"MATCH": "match", "PARTIAL": "partial", "MISMATCH": "mismatch"}
# Lower rank sorts first -- "most urgent" ordering, like a mail app surfacing flagged
# messages before read ones.
_JUDGMENT_RANK = {"MISMATCH": 0, "PARTIAL": 1, "MATCH": 2}

# index.csv stores sidecar paths relative to the repo root (run_question.py's --question-dir
# is always "Scripts/eval/audit/qNN-.../"), but index.csv (and report.html) live inside that
# same Scripts/eval/audit/ directory -- strip the shared prefix to read/link relative to there.
_REPORT_DIR_PREFIX = "Scripts/eval/audit/"
_MAX_EMBED_CHARS = 50_000


def _relative_href(stored_path: str) -> str:
    if stored_path.startswith(_REPORT_DIR_PREFIX):
        return stored_path[len(_REPORT_DIR_PREFIX):]
    return stored_path


def _read_sidecar(audit_dir: Path, stored_path: str) -> str:
    if not stored_path:
        return ""
    file_path = audit_dir / _relative_href(stored_path)
    try:
        text = file_path.read_text()
    except OSError:
        return f"(file not found: {_relative_href(stored_path)})"
    if len(text) > _MAX_EMBED_CHARS:
        text = text[:_MAX_EMBED_CHARS] + f"\n... (truncated, {len(text)} chars total)"
    return text


def render(csv_path: Path, out_path: Path) -> None:
    audit_dir = csv_path.resolve().parent
    out_path.write_text(_page(_grouped_by_question(csv_path), audit_dir))


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


def _page(by_question: dict[str, list[dict]], audit_dir: Path) -> str:
    ordered = sorted(by_question.items())
    latest_runs = [_latest(runs) for _, runs in ordered]
    list_rows = "\n".join(_list_row(question_id, latest) for (question_id, _), latest
                          in zip(ordered, latest_runs))
    detail_panels = "\n".join(_detail_panel(question_id, runs, audit_dir) for question_id, runs in ordered)
    first_id = ordered[0][0] if ordered else ""
    return f"""<!doctype html>
<html><head><meta charset="utf-8"><title>CohortQuery translation accuracy audit</title>
<style>
{_CSS}
</style></head><body>
<header class="topbar">
<h1>Translation accuracy audit</h1>
<p class="subtitle">{len(ordered)} questions &middot; {sum(len(r) for _, r in ordered)} verification runs</p>
{_summary(latest_runs)}
</header>
<div class="app">
<div class="list-pane">
<table id="list">
<thead><tr>
<th class="col-status" onclick="sortList('rank')">Status <span class="sort-indicator" id="sort-rank"></span></th>
<th onclick="sortList('question')">Question <span class="sort-indicator" id="sort-question"></span></th>
<th class="col-date" onclick="sortList('checked')">Checked <span class="sort-indicator" id="sort-checked"></span></th>
</tr></thead>
<tbody id="list-body">
{list_rows}
</tbody>
</table>
</div>
<div class="detail-pane" id="detail-pane">
{detail_panels}
</div>
</div>
<script>
{_JS.replace('__FIRST_ID__', first_id)}
</script>
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


def _list_row(question_id: str, latest: dict) -> str:
    judgment_class = _JUDGMENT_CLASS.get(latest["judgment"], "")
    rank = _JUDGMENT_RANK.get(latest["judgment"], 9)
    question_text = html.escape(latest["question"])
    # zero-padded composite key so a single string sort gives rank-then-alphabetical order
    sort_key = f"{rank}_{latest['question'].lower()}"
    checked_date = latest["checked_at"].split("T")[0]
    return f"""<tr class="row" data-id="{html.escape(question_id)}"
    data-rank="{html.escape(sort_key)}" data-question="{html.escape(latest['question'].lower())}"
    data-checked="{html.escape(latest['checked_at'])}" onclick="selectQuestion('{html.escape(question_id)}')">
<td class="col-status"><span class="badge {judgment_class}">{html.escape(latest['judgment'])}</span></td>
<td class="row-title">{question_text}<span class="row-id">{html.escape(question_id)}</span></td>
<td class="col-date">{html.escape(checked_date)}</td>
</tr>"""


def _detail_panel(question_id: str, runs: list[dict], audit_dir: Path) -> str:
    question_text = html.escape(runs[0]["question"])
    gold_sql = _read_sidecar(audit_dir, runs[-1]["gold_sql_path"])
    gold_block = (f'<details class="sidecar"><summary>Gold SQL</summary>'
                  f'<pre>{html.escape(gold_sql)}</pre></details>' if gold_sql else "")
    run_blocks = "\n".join(_run_block(row, audit_dir) for row in reversed(runs))
    return f"""<article class="detail" id="detail-{html.escape(question_id)}">
<header class="detail-header"><h2>{question_text}</h2><p class="slug">{html.escape(question_id)}</p></header>
{gold_block}
{run_blocks}
</article>"""


def _run_block(row: dict, audit_dir: Path) -> str:
    judgment_class = _JUDGMENT_CLASS.get(row["judgment"], "")
    reasoning = (f'<p class="reasoning">{html.escape(row["judgment_reasoning"])}</p>'
                 if row["judgment_reasoning"] else "")
    flag = (f'<div class="flag">&#10067; <strong>Needs input:</strong> {html.escape(row["confirmation_note"])}</div>'
            if row["needs_researcher_confirmation"] == "yes" and row["confirmation_note"] else "")
    sql_text = _read_sidecar(audit_dir, row["generated_sql_path"])
    notes_text = _read_sidecar(audit_dir, row["judgment_reference"])
    sidecars = f'<details class="sidecar"><summary>Generated SQL</summary><pre>{html.escape(sql_text)}</pre></details>'
    sidecars += _scorecard(row)
    if notes_text:
        sidecars += (f'\n<details class="sidecar"><summary>Notes</summary>'
                     f'<div class="markdown">{mistune.html(notes_text)}</div></details>')
    return f"""<div class="run">
<div class="meta">
<span class="badge {judgment_class}">{html.escape(row['judgment'])}</span>
<span>{html.escape(row['checked_at'])}</span>
<span>&middot; {html.escape(row['trigger_reason'])}</span>
<span>&middot; gold v{html.escape(row['gold_version'])}</span>
</div>
{reasoning}
{flag}
<p class="planpath">plan: {html.escape(row['plan_path'])}</p>
{sidecars}
</div>"""


def _scorecard(row: dict) -> str:
    """Gold vs. generated comparison -- the numbers that actually matter, not a raw
    biosample dump. Omitted when the question has no single gold answer to compare
    against (ambiguous phrasing, capability-boundary tests)."""
    if not row["gold_count"]:
        return ('<div class="sidecar no-gold">No single gold answer for this question '
                '-- see reasoning above.</div>')
    gold = int(row["gold_count"])
    generated = int(row["generated_count"])
    overlap = int(row["overlap_count"])
    missed = gold - overlap
    extra = generated - overlap
    recall = round(100 * overlap / gold) if gold else 0
    precision = round(100 * overlap / generated) if generated else 0
    rows = "".join(f"""<tr><td>{label}</td><td class="num">{value:,}</td></tr>"""
                   for label, value in [("Gold", gold), ("Generated", generated),
                                        ("Overlap (correct)", overlap),
                                        ("Missed (gold-only)", missed),
                                        ("Extra (generated-only)", extra)])
    return f"""<details class="sidecar" open><summary>Results comparison</summary>
<div class="scorecard">
<div class="bar-row"><span class="bar-label">Recall {recall}%</span>
<div class="bar-track"><div class="bar-fill recall" style="width:{recall}%"></div></div></div>
<div class="bar-row"><span class="bar-label">Precision {precision}%</span>
<div class="bar-track"><div class="bar-fill precision" style="width:{precision}%"></div></div></div>
<table class="scorecard-table">{rows}</table>
</div>
</details>"""


_CSS = """
  :root{color-scheme:light dark}
  *{box-sizing:border-box}
  html,body{height:100%;margin:0}
  body{font:14px/1.5 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;display:flex;flex-direction:column}
  .topbar{padding:16px 20px 0}
  .topbar h1{margin:0 0 2px;font-size:19px}
  .subtitle{opacity:.65;margin:0 0 14px;font-size:13px}
  .stats{display:flex;gap:10px;margin-bottom:14px;flex-wrap:wrap}
  .stat{flex:1;min-width:100px;border-radius:8px;padding:8px 12px;text-align:center}
  .stat .num{font-size:20px;font-weight:700;display:block}
  .stat .label{font-size:10px;text-transform:uppercase;letter-spacing:.04em;opacity:.7}
  .stat.match{background:#d1fae5;color:#065f46}
  .stat.partial{background:#fef3c7;color:#92400e}
  .stat.mismatch{background:#fee2e2;color:#991b1b}
  .stat.flagged{background:#ede9fe;color:#5b21b6}
  .app{display:flex;flex:1;min-height:0;border-top:1px solid rgba(127,127,127,.3)}
  .list-pane{width:360px;flex-shrink:0;overflow-y:auto;border-right:1px solid rgba(127,127,127,.3)}
  .detail-pane{flex:1;overflow-y:auto;padding:24px 32px}
  table{border-collapse:collapse;width:100%}
  thead th{position:sticky;top:0;background:Canvas;text-align:left;font-size:11px;
            text-transform:uppercase;letter-spacing:.04em;opacity:.6;padding:8px 12px;
            cursor:pointer;user-select:none;border-bottom:1px solid rgba(127,127,127,.3);white-space:nowrap}
  thead th:hover{opacity:1}
  .sort-indicator{display:inline-block;width:10px}
  .row{cursor:pointer;border-bottom:1px solid rgba(127,127,127,.15)}
  .row:hover{background:rgba(127,127,127,.08)}
  .row.selected{background:#2563eb;color:#fff}
  .row.selected .row-id{color:#dbeafe}
  .row td{padding:9px 12px;vertical-align:top}
  .col-status{white-space:nowrap}
  .col-date{white-space:nowrap;font-size:12px;opacity:.7}
  .row-title{font-size:13px}
  .row-id{display:block;font-size:11px;opacity:.55;margin-top:2px}
  .badge{display:inline-block;font-size:10px;font-weight:700;padding:2px 7px;border-radius:999px;
         text-transform:uppercase;letter-spacing:.03em;vertical-align:middle;white-space:nowrap}
  .badge.match{background:#10b981;color:#fff}
  .badge.partial{background:#f59e0b;color:#fff}
  .badge.mismatch{background:#ef4444;color:#fff}
  .detail{display:none}
  .detail.active{display:block}
  .detail-header{margin-bottom:18px}
  .detail-header h2{margin:0 0 4px;font-size:20px}
  .slug{opacity:.5;font-size:12px;margin:0}
  .run{border-top:1px solid rgba(127,127,127,.2);padding-top:14px;margin-top:14px}
  .run:first-of-type{border-top:none;padding-top:0;margin-top:0}
  .meta{display:flex;align-items:center;gap:8px;flex-wrap:wrap;font-size:13px;opacity:.75;margin-bottom:8px}
  .reasoning{margin:8px 0;font-size:14px}
  .flag{background:#ede9fe;border-left:3px solid #8b5cf6;padding:8px 12px;border-radius:6px;
        font-size:13px;margin:8px 0}
  .planpath{font-size:11px;opacity:.5;font-family:ui-monospace,Menlo,monospace;margin:8px 0;word-break:break-all}
  .sidecar{margin:6px 0;border:1px solid rgba(127,127,127,.25);border-radius:6px;overflow:hidden}
  .sidecar summary{padding:6px 10px;font-size:12px;cursor:pointer;background:rgba(127,127,127,.08)}
  .sidecar pre{margin:0;padding:10px 12px;font-size:12px;overflow:auto;max-height:320px;
               white-space:pre-wrap;word-break:break-word;font-family:ui-monospace,Menlo,monospace}
  .sidecar.no-gold{padding:8px 12px;font-size:12px;opacity:.6;font-style:italic}
  .scorecard{padding:12px 14px}
  .bar-row{margin-bottom:10px}
  .bar-label{display:block;font-size:12px;margin-bottom:3px;opacity:.8}
  .bar-track{background:rgba(127,127,127,.15);border-radius:4px;height:8px;overflow:hidden}
  .bar-fill{height:100%;border-radius:4px}
  .bar-fill.recall{background:#2563eb}
  .bar-fill.precision{background:#8b5cf6}
  .scorecard-table{width:100%;border-collapse:collapse;margin-top:10px;font-size:13px}
  .scorecard-table td{padding:4px 0;border-bottom:1px solid rgba(127,127,127,.12)}
  .scorecard-table td.num{text-align:right;font-variant-numeric:tabular-nums;font-weight:600}
  .markdown{padding:10px 14px;font-size:13px}
  .markdown h1{font-size:16px;margin:0 0 8px}
  .markdown h2{font-size:14px;margin:14px 0 6px}
  .markdown h3{font-size:13px;margin:12px 0 4px}
  .markdown p{margin:6px 0}
  .markdown code{font-family:ui-monospace,Menlo,monospace;background:rgba(127,127,127,.12);
                 padding:1px 4px;border-radius:3px;font-size:12px}
  .markdown pre{background:rgba(127,127,127,.08);padding:8px 10px;border-radius:6px;overflow:auto}
  .markdown pre code{background:none;padding:0}
  .markdown ul,.markdown ol{margin:6px 0;padding-left:22px}
"""

_JS = """
function selectQuestion(id){
  document.querySelectorAll('.detail').forEach(function(el){ el.classList.remove('active'); });
  document.querySelectorAll('.row').forEach(function(el){ el.classList.remove('selected'); });
  var panel = document.getElementById('detail-' + id);
  if (panel) panel.classList.add('active');
  var row = document.querySelector('.row[data-id="' + id + '"]');
  if (row) row.classList.add('selected');
}

function sortList(key){
  var tbody = document.getElementById('list-body');
  var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));
  var dir = (tbody.dataset.sortKey === key && tbody.dataset.sortDir === 'asc') ? 'desc' : 'asc';
  rows.sort(function(a, b){
    var av = a.dataset[key], bv = b.dataset[key];
    if (av < bv) return dir === 'asc' ? -1 : 1;
    if (av > bv) return dir === 'asc' ? 1 : -1;
    return 0;
  });
  rows.forEach(function(r){ tbody.appendChild(r); });
  tbody.dataset.sortKey = key;
  tbody.dataset.sortDir = dir;
  document.querySelectorAll('.sort-indicator').forEach(function(el){ el.textContent = ''; });
  var indicator = document.getElementById('sort-' + key);
  if (indicator) indicator.textContent = dir === 'asc' ? '\\u25B2' : '\\u25BC';
}

document.addEventListener('DOMContentLoaded', function(){
  var firstId = '__FIRST_ID__';
  if (firstId) selectQuestion(firstId);
  sortList('rank');
});
"""
