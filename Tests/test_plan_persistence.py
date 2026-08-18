"""A plan is the reproducible artifact: save it, replay it, never re-ask the LLM."""
import pytest

import askslm
from askslm.plan import Plan, load_plan
from askslm.translation import ResearchQuestion, SourceQuery, Translation
from askslm.plan import CohortPreview


def _plan() -> Plan:
    return Plan(
        question=ResearchQuestion("adults with IBD"),
        translation=Translation(
            interpretation="subject_disease_status in (Crohn's disease, ulcerative colitis)",
            queries=(SourceQuery(askslm.Source.METALOG_METADATA,
                                 "SELECT biosample FROM metalog_metadata"),)),
        preview=CohortPreview(by_metadata_source={askslm.Source.METALOG_METADATA: 12},
                              shared=3, union=12,
                              by_profile_source={askslm.Source.METALOG_MOTUS3: 8}))


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

    assert loaded.preview.by_profile_source[askslm.Source.METALOG_MOTUS3] == 8
    assert loaded.translation.queries[0].source is askslm.Source.METALOG_METADATA


def test_a_failed_plan_still_saves_and_still_refuses_to_run(tmp_path):
    """A plan that could not be translated is still worth saving -- the user may want
    to send it to someone. It must keep refusing to run after a round trip."""
    path = tmp_path / "bad.json"
    failed = Plan(ResearchQuestion("people who felt unwell"),
                  Translation(interpretation="", queries=(), failure="no such field"),
                  CohortPreview(), error="no such field")

    failed.save(path)

    with pytest.raises(askslm.TranslationError):
        load_plan(path).run(profile_sources=askslm.Source.METALOG_MOTUS3)
