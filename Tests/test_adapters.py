"""embed() follows the same never-raises contract as expand()/repair(): a backend
with no model degrades to no candidates, never an exception that would take down ask()."""
from askslm.adapters import CannedLlmBackend
from askslm.translation import Translation


def test_canned_backend_embed_returns_nothing():
    """No model behind this backend -- matches expand()'s documented fallback."""
    backend = CannedLlmBackend(Translation(interpretation="", queries=()))

    assert backend.embed(["IBD", "calprotectin"]) == []


def test_gemini_backend_embed_calls_the_embedding_model():
    """The client is injected, exactly like translate()/expand() -- no network in
    this test. Asserts the real call shape: batched contents, one vector per input,
    aligned by position."""
    from askslm.adapters import GeminiBackend

    class _FakeEmbeddingResponse:
        def __init__(self, vectors):
            self.embeddings = [_FakeEmbedding(v) for v in vectors]

    class _FakeEmbedding:
        def __init__(self, values):
            self.values = values

    class _FakeModels:
        def __init__(self):
            self.calls = []

        def embed_content(self, *, model, contents, config=None):
            self.calls.append((model, contents, config))
            return _FakeEmbeddingResponse([[0.1, 0.2], [0.3, 0.4]])

    class _FakeClient:
        def __init__(self):
            self.models = _FakeModels()

    client = _FakeClient()
    backend = GeminiBackend(client, "gemini-2.5-flash")

    vectors = backend.embed(["IBD", "calprotectin"])

    assert vectors == [[0.1, 0.2], [0.3, 0.4]]
    model, contents, config = client.models.calls[0]
    assert model == GeminiBackend.EMBEDDING_MODEL
    assert contents == ["IBD", "calprotectin"]


def test_gemini_backend_embed_never_raises():
    """A failed embedding call must degrade to no candidates, not crash ask()."""
    from askslm.adapters import GeminiBackend

    class _RaisingModels:
        def embed_content(self, *, model, contents, config=None):
            raise RuntimeError("network down")

    class _FakeClient:
        def __init__(self):
            self.models = _RaisingModels()

    backend = GeminiBackend(_FakeClient(), "gemini-2.5-flash")

    assert backend.embed(["IBD"]) == []
