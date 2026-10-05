"""The Translator is the only thing that knows a prompt needs schemas in it."""
from cohortquery.translation import (ResearchQuestion, SourceQuery, Translation,
                                TranslationPrompt, Translator)
from cohortquery.sources import Source


class SpyBackend:
    """Records the prompt it was handed, so the test can assert on it."""

    def __init__(self):
        self.prompt: TranslationPrompt | None = None

    def translate(self, prompt: TranslationPrompt) -> Translation:
        self.prompt = prompt
        return Translation(interpretation="ok",
                           queries=(SourceQuery(Source.SRA_METADATA, "SELECT 1"),))


class StubCatalog:
    def all(self) -> str:
        return "TABLE metalog_metadata\n  subject_disease_status  VARCHAR\n      values: [\"IBD\"]"


def test_the_prompt_carries_the_schemas_not_an_empty_string():
    """The walking skeleton passed schemas="", which is exactly the failure mode the
    catalog exists to prevent: a model guessing literals it was never shown."""
    backend = SpyBackend()
    translator = Translator(backend, StubCatalog())

    translator.translate(ResearchQuestion("adults with IBD"))

    assert "IBD" in backend.prompt.schemas
    assert backend.prompt.question.text == "adults with IBD"


def test_the_backends_translation_is_returned_unchanged():
    """Invalid SQL surfaces later, when the preview runs the counts -- not here.
    This step is pure, so it stays trivially testable."""
    translator = Translator(SpyBackend(), StubCatalog())

    translation = translator.translate(ResearchQuestion("anything"))

    assert translation.interpretation == "ok"


class StubConcepts:
    def __init__(self, values: dict | None = None):
        self._values = values or {}

    def matching_values(self, question: str):
        return self._values


def test_a_semantic_value_match_lands_in_the_prompt():
    """The metalog half of the feature: subject_disease_status's real values,
    found by meaning, must reach the schemas string."""
    backend = SpyBackend()
    translator = Translator(backend, StubCatalog(),
                            concepts=StubConcepts({"metalog_metadata.subject_disease_status":
                                         ["Crohn's disease", "ulcerative colitis"]}))

    translator.translate(ResearchQuestion("IBD cohort"))

    assert "Crohn's disease" in backend.prompt.schemas
    assert "ulcerative colitis" in backend.prompt.schemas


def test_no_concepts_collaborator_behaves_as_before():
    """concepts=None (the default) must not change existing behavior."""
    backend = SpyBackend()
    translator = Translator(backend, StubCatalog())

    translator.translate(ResearchQuestion("adults with IBD"))

    assert "IBD" in backend.prompt.schemas


def test_an_unknown_llm_name_fails_at_config_not_at_ask(tmp_path):
    """Fail fast: a typo in llm= must not survive until the first question."""
    import pytest

    import cohortquery
    from fixtures.mirror import build_fixture_mirror

    path = build_fixture_mirror(tmp_path / "fixture.duckdb")

    with pytest.raises(ValueError, match="unknown llm"):
        cohortquery.config(db=path, llm="gemni", llm_key="x")
