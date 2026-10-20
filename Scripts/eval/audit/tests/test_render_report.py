import csv
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from render_report import render
from schema import COLUMNS, new_row


def _write_index(csv_path, rows):
    with csv_path.open("w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=COLUMNS)
        writer.writeheader()
        for row in rows:
            writer.writerow(new_row(**row))


def test_render_groups_runs_under_one_question_and_color_codes_judgment(tmp_path):
    csv_path = tmp_path / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q01", run_id="r1", question="stool samples from IBD adults",
             checked_at="2026-10-05T00:00:00", trigger_reason="initial", judgment="MATCH",
             gold_version="1", plan_path="/private/pinto-lab/plans/x/plan.json",
             generated_sql_path="q01/runs/r1/generated.sql", results_path="q01/runs/r1/results.csv"),
        dict(question_id="q01", run_id="r2", question="stool samples from IBD adults",
             checked_at="2026-11-01T00:00:00", trigger_reason="mirror_rebuild", judgment="PARTIAL",
             gold_version="1", plan_path="/private/pinto-lab/plans/y/plan.json",
             generated_sql_path="q01/runs/r2/generated.sql", results_path="q01/runs/r2/results.csv"),
    ])
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
    _write_index(csv_path, [
        # q01: superseded PARTIAL -> latest is MATCH
        dict(question_id="q01", run_id="r1", question="q one",
             checked_at="2026-10-05T00:00:00", trigger_reason="initial", judgment="PARTIAL",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q01/runs/r1/generated.sql", results_path="q01/runs/r1/results.csv"),
        dict(question_id="q01", run_id="r2", question="q one",
             checked_at="2026-11-01T00:00:00", trigger_reason="code_change", judgment="MATCH",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q01/runs/r2/generated.sql", results_path="q01/runs/r2/results.csv"),
        # q02: single MISMATCH run
        dict(question_id="q02", run_id="r1", question="q two",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MISMATCH",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q02/runs/r1/generated.sql", results_path="q02/runs/r1/results.csv"),
    ])
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
    _write_index(csv_path, [
        dict(question_id="q04", run_id="r1", question="BMI samples",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q04/runs/r1/generated.sql", results_path="q04/runs/r1/results.csv",
             judgment_reasoning="CONFIRMED BUG: host_body_mass_index_sam_s_dpl230 excluded entirely."),
    ])
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "CONFIRMED BUG: host_body_mass_index_sam_s_dpl230 excluded entirely." in content


def test_needs_researcher_confirmation_is_flagged(tmp_path):
    csv_path = tmp_path / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q05", run_id="r1", question="ambiguous question",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q05/runs/r1/generated.sql", results_path="q05/runs/r1/results.csv",
             needs_researcher_confirmation="yes",
             confirmation_note="Is this interpretation defensible?"),
    ])
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "Is this interpretation defensible?" in content


def test_list_row_selects_its_detail_panel(tmp_path):
    """Mail-app layout: clicking a list row (identified by data-id) must reveal the
    matching detail panel (id="detail-<question_id>"), and the row's visible title
    must be the human question text, not the slug -- the slug is secondary."""
    csv_path = tmp_path / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q07-mouse-gut-metagenome", run_id="r1", question="mouse gut metagenome samples",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MATCH",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q07-mouse-gut-metagenome/runs/r1/generated.sql",
             results_path="q07-mouse-gut-metagenome/runs/r1/results.csv"),
    ])
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
    _write_index(csv_path, [
        dict(question_id="q_match", run_id="r1", question="a match question",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MATCH",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q_match/runs/r1/generated.sql", results_path="q_match/runs/r1/results.csv"),
        dict(question_id="q_mismatch", run_id="r1", question="a mismatch question",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MISMATCH",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q_mismatch/runs/r1/generated.sql", results_path="q_mismatch/runs/r1/results.csv"),
    ])
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


def test_plan_path_is_plain_text_not_a_link(tmp_path):
    """plan_path is always an absolute server-only path (/private/pinto-lab/plans/...)
    that never exists on a reader's own machine -- it was a dead link. Show it as
    plain reference text instead of a clickable <a href>."""
    csv_path = tmp_path / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q01", run_id="r1", question="q one",
             checked_at="2026-10-05T00:00:00", trigger_reason="initial", judgment="MATCH",
             gold_version="1", plan_path="/private/pinto-lab/plans/x/plan.json",
             generated_sql_path="q01/runs/r1/generated.sql", results_path="q01/runs/r1/results.csv"),
    ])
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "/private/pinto-lab/plans/x/plan.json" in content
    assert 'href="/private/pinto-lab/plans/x/plan.json"' not in content


def test_needs_input_is_flagged_in_the_list_row_not_only_the_detail_pane(tmp_path):
    """The actual bug: the summary stat card says "4 needs input" but the list
    itself gives no visual indication of WHICH rows those are -- you only find
    out by opening each question's detail pane one at a time."""
    csv_path = tmp_path / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q05", run_id="r1", question="ambiguous question",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q05/runs/r1/generated.sql", results_path="q05/runs/r1/results.csv",
             needs_researcher_confirmation="yes", confirmation_note="note"),
        dict(question_id="q02", run_id="r1", question="a settled question",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MATCH",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q02/runs/r1/generated.sql", results_path="q02/runs/r1/results.csv",
             needs_researcher_confirmation="no"),
    ])
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    list_section = content[content.index('id="list-body"'):content.index('</tbody>')]
    rows = list_section.split('<tr class="row"')[1:]
    row_q05 = next(r for r in rows if 'data-id="q05"' in r)
    row_q02 = next(r for r in rows if 'data-id="q02"' in r)
    assert "flag-dot" in row_q05
    assert "flag-dot" not in row_q02


def test_last_viewed_question_is_remembered_across_page_loads(tmp_path):
    """The actual bug: every refresh selected a hardcoded first question
    (alphabetically first, before the JS even sorts the list) -- losing your
    place every single reload. Fix: remember the last-viewed question via
    localStorage and restore it on load, instead of hardcoding one."""
    csv_path = tmp_path / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q01", run_id="r1", question="q one",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="MATCH",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="q01/runs/r1/generated.sql", results_path="q01/runs/r1/results.csv"),
    ])
    out_path = tmp_path / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "localStorage" in content
    assert "__FIRST_ID__" not in content  # no hardcoded fallback id baked into the page


def test_scorecard_shows_gold_vs_generated_buckets_not_a_raw_csv_dump(tmp_path):
    """The actual pain point: a raw results.csv dump (hundreds of
    "SRA_METADATA,SAMD..." lines) tells a reader nothing. When gold_count is
    present, show the comparison that actually matters: gold/generated/overlap/
    missed/extra counts -- not the biosample list."""
    audit_dir = tmp_path
    question_dir = audit_dir / "q03"
    run_dir = question_dir / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "generated.sql").write_text("SELECT biosample FROM sra_metadata;")
    (run_dir / "results.csv").write_text("source,biosample\nSRA_METADATA,SAMD00020630\n")

    csv_path = audit_dir / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q03", run_id="r1", question="tumor samples",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="Scripts/eval/audit/q03/runs/r1/generated.sql",
             results_path="Scripts/eval/audit/q03/runs/r1/results.csv",
             gold_count="33405", generated_count="68342", overlap_count="5212"),
    ])
    out_path = audit_dir / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "33,405" in content or "33405" in content
    assert "68,342" in content or "68342" in content
    assert "5,212" in content or "5212" in content
    # missed = gold - overlap = 28193; extra = generated - overlap = 63130
    assert "28,193" in content or "28193" in content
    assert "63,130" in content or "63130" in content
    assert "SAMD00020630" not in content


def test_scorecard_omitted_when_no_gold_count(tmp_path):
    """Ambiguous/capability-boundary questions (q05/q08) have no single gold
    answer -- don't fabricate a comparison for them, just skip the scorecard."""
    audit_dir = tmp_path
    run_dir = audit_dir / "q05" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "generated.sql").write_text("SELECT biosample FROM sra_metadata;")
    (run_dir / "results.csv").write_text("source,biosample\n")

    csv_path = audit_dir / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q05", run_id="r1", question="ambiguous question",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="Scripts/eval/audit/q05/runs/r1/generated.sql",
             results_path="Scripts/eval/audit/q05/runs/r1/results.csv"),
    ])
    out_path = audit_dir / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "no single gold" in content.lower()


def test_notes_markdown_is_rendered_not_shown_as_raw_text(tmp_path):
    """The other pain point: notes.md was shown as raw text inside a <pre> block
    -- "# Heading" literally visible instead of rendering as a heading."""
    audit_dir = tmp_path
    run_dir = audit_dir / "q05" / "runs" / "r1"
    run_dir.mkdir(parents=True)
    (run_dir / "generated.sql").write_text("SELECT 1;")
    (run_dir / "results.csv").write_text("source,biosample\n")
    (run_dir / "notes.md").write_text("# q05-healthy-adult-gut-ambiguous\n\n**Question:** \"healthy adults\"\n")

    csv_path = audit_dir / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q05", run_id="r1", question="ambiguous question",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
             gold_version="1", plan_path="/x/plan.json",
             generated_sql_path="Scripts/eval/audit/q05/runs/r1/generated.sql",
             results_path="Scripts/eval/audit/q05/runs/r1/results.csv",
             judgment_reference="Scripts/eval/audit/q05/runs/r1/notes.md"),
    ])
    out_path = audit_dir / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "<h1>q05-healthy-adult-gut-ambiguous</h1>" in content
    assert "<strong>Question:</strong>" in content
    assert "# q05-healthy-adult-gut-ambiguous" not in content


def test_sidecars_are_embedded_inline_not_linked(tmp_path):
    """The actual bug reported: clicking gold/sql/results/notes links triggered OS
    file-type downloads instead of displaying anything (a file:// + browser
    file-association quirk with .csv/.sql/.md). Fix: read each sidecar's real
    content at render time and embed it directly in the page -- nothing left to
    download, it just displays."""
    audit_dir = tmp_path
    question_dir = audit_dir / "q04-recorded-bmi-jattr-only"
    run_dir = question_dir / "runs" / "2026-10-19_initial"
    run_dir.mkdir(parents=True)
    (question_dir / "gold.sql").write_text("SELECT biosample FROM sra_metadata WHERE bmi_sam IS NOT NULL;")
    (run_dir / "generated.sql").write_text("SELECT biosample FROM sra_metadata WHERE jattr IS NOT NULL;")
    (run_dir / "results.csv").write_text("source,biosample\nSRA_METADATA,SAMN00000001\n")
    (run_dir / "notes.md").write_text("# q04 notes\nFull writeup text goes here.")

    csv_path = audit_dir / "index.csv"
    _write_index(csv_path, [
        dict(question_id="q04-recorded-bmi-jattr-only", run_id="2026-10-19_initial",
             question="samples with recorded body mass index",
             checked_at="2026-10-19T00:00:00", trigger_reason="initial", judgment="PARTIAL",
             gold_version="1", plan_path="/x/plan.json",
             gold_sql_path="Scripts/eval/audit/q04-recorded-bmi-jattr-only/gold.sql",
             generated_sql_path="Scripts/eval/audit/q04-recorded-bmi-jattr-only/runs/2026-10-19_initial/generated.sql",
             results_path="Scripts/eval/audit/q04-recorded-bmi-jattr-only/runs/2026-10-19_initial/results.csv",
             judgment_reference="Scripts/eval/audit/q04-recorded-bmi-jattr-only/runs/2026-10-19_initial/notes.md"),
    ])
    out_path = audit_dir / "report.html"
    render(csv_path, out_path)
    content = out_path.read_text()
    assert "SELECT biosample FROM sra_metadata WHERE bmi_sam IS NOT NULL;" in content
    assert "SELECT biosample FROM sra_metadata WHERE jattr IS NOT NULL;" in content
    assert "Full writeup text goes here." in content
