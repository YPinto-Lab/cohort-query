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


def test_json_wrapped_in_a_markdown_fence_is_still_parsed():
    """Models fence their JSON even when told not to. Stripping it is one line here and
    an unexplained crash otherwise."""
    payload = '```json\n{"interpretation": "x", "queries": [], "failure": null}\n```'

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
