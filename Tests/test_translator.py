"""The Translator is the only thing that knows a prompt needs schemas in it."""
from askslm.translation import (ResearchQuestion, SourceQuery, Translation,
                                TranslationPrompt, Translator)
from askslm.sources import Source


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


def test_an_unknown_llm_name_fails_at_config_not_at_ask(tmp_path):
    """Fail fast: a typo in llm= must not survive until the first question."""
    import pytest

    import askslm
    from fixtures.mirror import build_fixture_mirror

    path = build_fixture_mirror(tmp_path / "fixture.duckdb")

    with pytest.raises(ValueError, match="unknown llm"):
        askslm.config(db=path, llm="gemni", llm_key="x")
