"""embed() follows the same never-raises contract as expand()/repair(): a backend
with no model degrades to no candidates, never an exception that would take down ask().

GeminiBackend has no embed() of its own -- query-time embedding always goes through
LocalEmbedder (see runtime.embedder()), so there is nothing to test here beyond the
canned, no-model case."""
from cohortquery.adapters import CannedLlmBackend
from cohortquery.translation import Translation


def test_canned_backend_embed_returns_nothing():
    """No model behind this backend -- matches expand()'s documented fallback."""
    backend = CannedLlmBackend(Translation(interpretation="", queries=()))

    assert backend.embed(["IBD", "calprotectin"]) == []
