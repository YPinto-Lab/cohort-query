"""Response parsing only. No network: the client is stubbed, because a test that needs
an API key is a test that does not run."""
import json

import pytest

from askslm.adapters import GeminiBackend
from askslm.sources import Source
from askslm.translation import ResearchQuestion, TranslationPrompt


class StubClient:
    """Mimics google-genai's client.models.generate_content(...).text"""

    def __init__(self, payload: str):
        self.models = _StubModels(payload)
        self.last_config = None


class _StubModels:
    def __init__(self, payload: str):
        self._payload = payload

    def generate_content(self, model, contents, config):
        self.model = model
        self.contents = contents
        self.config = config
        return _StubResponse(self._payload)


class _StubResponse:
    def __init__(self, text: str):
        self.text = text


def _prompt() -> TranslationPrompt:
    return TranslationPrompt(question=ResearchQuestion("adults with IBD"),
                             schemas="TABLE metalog_metadata")


def test_parses_queries_into_typed_source_queries():
    payload = json.dumps({
        "interpretation": "stool samples, subject_disease_status = IBD",
        "queries": [{"source": "METALOG_METADATA",
                     "sql": "SELECT biosample, sample_alias FROM metalog_metadata"}],
        "failure": None,
    })

    translation = GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())

    assert translation.queries[0].source is Source.METALOG_METADATA
    assert "metalog_metadata" in translation.queries[0].sql
    assert translation.failure is None


def test_a_refusal_becomes_a_failure_sentence_with_no_queries():
    """The model saying "I can't" is a first-class outcome, not an exception. It reaches
    the user as Plan.error and _guard_runnable refuses to run()."""
    payload = json.dumps({
        "interpretation": "",
        "queries": [],
        "failure": "no metadata field records how a subject felt",
    })

    translation = GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())

    assert translation.queries == ()
    assert translation.failure == "no metadata field records how a subject felt"


def test_an_explicit_null_interpretation_becomes_an_empty_string():
    """Observed live: on a refusal Gemini returns `"interpretation": null`, and
    dict.get(key, "") returns None for a key that IS present with a null value -- so
    Translation.interpretation, typed str, silently held None."""
    payload = json.dumps({"interpretation": None, "queries": [],
                          "failure": "no metadata field records sample type"})

    translation = GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())

    assert translation.interpretation == ""
    assert translation.failure == "no metadata field records sample type"


def test_json_wrapped_in_a_markdown_fence_is_still_parsed():
    """Models fence their JSON even when told not to. Stripping it is one line here and
    an unexplained crash otherwise."""
    payload = '```json\n{"interpretation": "x", "queries": [], "failure": null}\n```'

    translation = GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())

    assert translation.interpretation == "x"


def test_a_fence_with_no_language_tag_is_still_parsed():
    """Some models emit a bare ``` fence with no "json" after it. The stripping must not
    assume the language tag is there."""
    payload = '```\n{"interpretation": "x", "queries": [], "failure": null}\n```'

    translation = GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())

    assert translation.interpretation == "x"


def test_trailing_prose_after_the_closing_fence_is_ignored():
    """A model that fences the JSON correctly can still add a sentence of commentary
    after the closing fence. That trailing text must not break the parse."""
    payload = ('```json\n{"interpretation": "x", "queries": [], "failure": null}\n```\n'
              "Let me know if you'd like me to refine this further.")

    translation = GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())

    assert translation.interpretation == "x"


def test_an_unknown_source_name_is_a_loud_error():
    """Trust input, fail fast -- but a hallucinated source name would otherwise become a
    silently missing half of the cohort. (SRA_TAXONOMY is not usable here: it is a real
    Source member, just a PROFILE one the LLM never writes -- this must be a name that
    does not exist in the enum at all.)"""
    payload = json.dumps({"interpretation": "x", "failure": None,
                          "queries": [{"source": "SRA_NARRATIVE", "sql": "SELECT 1"}]})

    with pytest.raises(KeyError):
        GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())


def test_a_real_but_non_metadata_source_is_also_a_loud_error():
    """SRA_TAXONOMY is a real Source, not a hallucination -- but it is a PROFILE source,
    not METADATA. If it slipped through, MetadataReconciler would read a 13.6-billion-row
    taxonomy table as if it were sample metadata: a silent wrong answer, not a crash."""
    payload = json.dumps({"interpretation": "x", "failure": None,
                          "queries": [{"source": "SRA_TAXONOMY", "sql": "SELECT 1"}]})

    with pytest.raises(ValueError, match="SRA_TAXONOMY"):
        GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())
