"""A plan is the reproducible artifact: save it, replay it, never re-ask the LLM."""
import json

import pytest

import cohortquery
from cohortquery.plan import Plan, load_plan
from cohortquery.translation import ResearchQuestion, SourceQuery, Translation
from cohortquery.plan import CohortPreview


def _plan() -> Plan:
    return Plan(
        question=ResearchQuestion("adults with IBD"),
        translation=Translation(
            interpretation="subject_disease_status in (Crohn's disease, ulcerative colitis)",
            queries=(SourceQuery(cohortquery.Source.METALOG_METADATA,
                                 "SELECT biosample FROM metalog_metadata"),)),
        preview=CohortPreview(by_metadata_source={cohortquery.Source.METALOG_METADATA: 12},
                              shared=3, union=12,
                              by_profile_source={cohortquery.Source.METALOG_MOTUS3: 8}))


def test_a_saved_plan_round_trips_to_an_equal_plan(tmp_path):
    """Equality is the whole contract: replay must reproduce the same cohort, so
    anything lost in the round trip is a silently different result later."""
    path = tmp_path / "ibd.json"

    _plan().save(path)

    assert load_plan(path) == _plan()


def test_enum_keys_survive_the_round_trip(tmp_path):
    """JSON object keys are strings. Source enum members used as dict keys are the
    thing most likely to come back wrong, and would silently empty the preview."""
    path = tmp_path / "ibd.json"

    _plan().save(path)
    loaded = load_plan(path)

    assert loaded.preview.by_profile_source[cohortquery.Source.METALOG_MOTUS3] == 8
    assert loaded.translation.queries[0].source is cohortquery.Source.METALOG_METADATA


def test_a_failed_plan_still_saves_and_still_refuses_to_run(tmp_path):
    """A plan that could not be translated is still worth saving -- the user may want
    to send it to someone. It must keep refusing to run after a round trip."""
    path = tmp_path / "bad.json"
    failed = Plan(ResearchQuestion("people who felt unwell"),
                  Translation(interpretation="", queries=(), failure="no such field"),
                  CohortPreview(), error="no such field")

    failed.save(path)

    with pytest.raises(cohortquery.TranslationError):
        load_plan(path).run(profile_sources=cohortquery.Source.METALOG_MOTUS3)


def test_discovered_cohort_round_trips(tmp_path):
    from cohortquery.cohort import Cohort

    plan = Plan(
        question=ResearchQuestion("adults with IBD"),
        translation=Translation(
            interpretation="x",
            queries=(SourceQuery(cohortquery.Source.METALOG_METADATA,
                                 "SELECT biosample FROM metalog_metadata"),)),
        preview=CohortPreview(union=2),
        discovered=Cohort({cohortquery.Source.METALOG_METADATA:
                           frozenset({"SAMN001", "SAMN002"})}))
    path = tmp_path / "cached.json"

    plan.save(path)
    loaded = load_plan(path)

    assert (loaded.discovered.by_source[cohortquery.Source.METALOG_METADATA]
           == frozenset({"SAMN001", "SAMN002"}))


def test_jattr_matches_round_trip_with_the_cohort():
    """The explain data (which key/value each concept matched on, and which
    biosamples) must survive a save/load cycle -- a researcher reopening a saved
    plan should see the same "why" they saw when they first asked."""
    from cohortquery.cohort import Cohort
    from cohortquery.jattr_concepts import JattrMatch

    cohort = Cohort(
        {cohortquery.Source.SRA_METADATA: frozenset({"SAMN001"})},
        jattr_matches={cohortquery.Source.SRA_METADATA: {
            "IBD": [JattrMatch(concept="IBD", matched_on="ibd_sam",
                               biosamples=frozenset({"SAMN001"}))]}})
    plan = Plan(
        question=ResearchQuestion("IBD"),
        translation=Translation(interpretation="x",
                                queries=(SourceQuery(cohortquery.Source.SRA_METADATA, sql=None),)),
        preview=CohortPreview(union=1), discovered=cohort)

    from tempfile import TemporaryDirectory
    with TemporaryDirectory() as tmp:
        path = f"{tmp}/matches.json"
        plan.save(path)
        loaded = load_plan(path)

    match = loaded.discovered.jattr_matches[cohortquery.Source.SRA_METADATA]["IBD"][0]
    assert match.matched_on == "ibd_sam"
    assert match.biosamples == frozenset({"SAMN001"})


def test_selected_bioprojects_round_trips(tmp_path):
    path = tmp_path / "selected.json"
    plan = Plan(question=ResearchQuestion("x"),
               translation=Translation(interpretation="x", queries=()),
               preview=CohortPreview(),
               selected_bioprojects=frozenset({"PRJEB18471", "PRJNA999"}))

    plan.save(path)
    loaded = load_plan(path)

    assert loaded.selected_bioprojects == frozenset({"PRJEB18471", "PRJNA999"})


def test_selected_bioprojects_defaults_to_none_meaning_everything_kept(tmp_path):
    path = tmp_path / "unselected.json"
    _plan().save(path)

    loaded = load_plan(path)

    assert loaded.selected_bioprojects is None


def test_run_applies_the_bioproject_selection(tmp_path):
    """The multi-select's whole point: run() must materialize only the projects
    the researcher kept, not the full discovered cohort."""
    from cohortquery.adapters import CannedLlmBackend, DuckDbConnection
    from cohortquery.bioproject_rollup import BioProjectRollup
    from fixtures.mirror import build_fixture_mirror

    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    translation = Translation(
        interpretation="everyone",
        queries=(SourceQuery(cohortquery.Source.METALOG_METADATA,
                             "SELECT * FROM metalog_metadata"),))
    cohortquery.config(db=path, database=connection, backend=CannedLlmBackend(translation))
    plan = cohortquery.ask("everyone")
    rows = BioProjectRollup(connection).rows(plan.discovered)
    kept = rows[0]

    narrowed = Plan(plan.question, plan.translation, plan.preview,
                    discovered=plan.discovered,
                    selected_bioprojects=frozenset({kept.project}))
    _, report = narrowed.run(profile_sources=cohortquery.Source.METALOG_MOTUS3)

    assert report.biosamples + len(report.dropped) == kept.biosample_count
    connection.close()


def test_an_old_plan_json_with_no_discovered_key_still_loads(tmp_path):
    """An old plan.json, saved before this field existed, has no "discovered" key
    at all -- it must still load, with discovered=None, and fall back to fresh
    discovery rather than crashing on a missing key."""
    path = tmp_path / "old.json"
    _plan().save(path)
    payload = json.loads(path.read_text())
    del payload["discovered"]
    path.write_text(json.dumps(payload))

    loaded = load_plan(path)

    assert loaded.discovered is None
