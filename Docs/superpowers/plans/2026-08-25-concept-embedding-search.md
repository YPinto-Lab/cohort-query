# Concept Embedding Search Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the semantic gap in `ask()`'s attribute/value retrieval — a question naming "IBD" must find `ibd_sam`/`host_disease_sam` (real jattr keys) and `"Crohn's disease"`/`"ulcerative colitis"` (real column values) even though none of those strings share a substring with "IBD".

**Architecture:** A build-time ETL step embeds every `attribute_keys.key` and every low-cardinality `schema_catalog` column value (Gemini's free embedding model), storing vectors in two new tables inside the same mirror file, indexed with DuckDB's `vss` extension. At `ask()` time, one embedding call per question feeds nearest-neighbor lookups that are unioned into the existing substring-search candidate set — the final SQL predicate is still written by the one existing translation LLM call, unchanged.

**Tech Stack:** DuckDB `vss` extension (HNSW index, `array_cosine_distance`), `google-genai`'s `embed_content` (model `gemini-embedding-001`) — both already verified against the real mirror and lab server.

**Spec:** `Docs/superpowers/specs/2026-08-25-concept-embedding-search-design.html`

---

## File Map

| File | Change |
|---|---|
| `src/askslm/ports.py` | Add `embed()` to the `LlmBackend` protocol |
| `src/askslm/adapters.py` | Implement `embed()` on `CannedLlmBackend` and `GeminiBackend` |
| `src/askslm/concept_search.py` | **New.** `ConceptIndex`: embedding-based key/value retrieval |
| `src/askslm/attributes.py` | `AttributeIndex` gains an optional `semantic` collaborator |
| `src/askslm/translation.py` | `Translator` gains a `concepts` collaborator; appends the value block |
| `src/askslm/runtime.py` | Wire `ConceptIndex` into the composition root |
| `Scripts/build_mirror/build_concept_embeddings.py` | **New.** ETL: embeds keys + values, builds the two tables |
| `Tests/fixtures/mirror.py` | Build the two embedding tables with a deterministic fake embedder |
| `Scripts/eval/questions.jsonl` | Two new cases |

---

### Task 1: `embed()` on the `LlmBackend` port

**Files:**
- Modify: `src/askslm/ports.py`
- Modify: `src/askslm/adapters.py`
- Test: `Tests/test_adapters.py` (new file)

- [ ] **Step 1: Write the failing tests**

```python
# Tests/test_adapters.py
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
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest Tests/test_adapters.py -v`
Expected: FAIL — `CannedLlmBackend`/`GeminiBackend` have no `embed` method (`AttributeError`).

- [ ] **Step 3: Add `embed()` to the port**

In `src/askslm/ports.py`, add to `class LlmBackend(Protocol):`, after `expand()`:

```python
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Vector per input string, batched into one call, same order as `texts`.

        A separate, cheap call on its own quota pool (HELPER_MODEL-class), used to
        find candidate keys/values that share no substring with the question's
        wording ("IBD" -> ibd_sam). A backend with no model returns [] and
        retrieval falls back to substring matching alone.
        """
```

- [ ] **Step 4: Implement on `CannedLlmBackend`**

In `src/askslm/adapters.py`, inside `class CannedLlmBackend:`, after `expand()`:

```python
    def embed(self, texts: list[str]) -> list[list[float]]:
        """No model behind this backend, so no vectors -- retrieval falls back to
        substring matching, which is what the tests exercise."""
        return []
```

- [ ] **Step 5: Implement on `GeminiBackend`**

In `src/askslm/adapters.py`, add a class constant and method to `class GeminiBackend:`
(place `EMBEDDING_MODEL` next to the existing `HELPER_MODEL`):

```python
    # gemini-embedding-001 is the current recommended text embedding model
    # (text-embedding-004 was deprecated January 2026) -- free tier, separate
    # quota pool from both the translation and helper models. Confirm this is
    # still current before relying on it; Google deprecates on ~annual cadence.
    EMBEDDING_MODEL = "gemini-embedding-001"
```

```python
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Never raises: a failed embedding call must degrade to substring-only
        retrieval, not take down ask(). Batched into ONE call -- embed_content
        accepts a list of contents and returns one vector per input, same order."""
        if not texts:
            return []
        start = time.monotonic()
        try:
            response = self._client.models.embed_content(
                model=self.EMBEDDING_MODEL, contents=texts,
                config={"output_dimensionality": EMBED_DIM})
        except Exception:
            _log_safely("embed (%.2fs) failed for texts=%r",
                       time.monotonic() - start, texts)
            return []
        _log_safely("embed (%.2fs) for %d texts", time.monotonic() - start, len(texts))
        return [list(embedding.values) for embedding in response.embeddings]
```

Add the import at the top of `src/askslm/adapters.py`, alongside the other `askslm` imports:

```python
from askslm.concept_search import EMBED_DIM
```

(This creates a forward dependency on Task 2's new module — `concept_search.py` must exist
before this import resolves. Do Task 2 first if executing out of order, or accept the
import error until Task 2 lands.)

- [ ] **Step 6: Run the tests to verify they pass**

Run: `pytest Tests/test_adapters.py -v`
Expected: PASS (once Task 2's `EMBED_DIM` constant exists — see Step 5's note)

- [ ] **Step 7: Commit**

```bash
git add src/askslm/ports.py src/askslm/adapters.py Tests/test_adapters.py
git commit -m "feat: add embed() to LlmBackend for semantic candidate retrieval"
```

---

### Task 2: `ConceptIndex` — embedding-based key and value retrieval

**Files:**
- Create: `src/askslm/concept_search.py`
- Test: `Tests/test_concept_search.py`

This is the core new logic, and it must be testable with **no real database and no
network** — a fake `Database` port (matching `_FakeDatabase` in `Tests/test_attributes.py`)
and a fake embedder that returns pre-assigned vectors so nearest-neighbor behavior is
deterministic.

- [ ] **Step 1: Write the failing tests**

```python
# Tests/test_concept_search.py
"""Embedding-based retrieval for the cases substring search structurally cannot reach:
"IBD" sharing zero characters with ibd_sam's neighbors or "Crohn's disease"."""
import pandas as pd
import pytest

from askslm.concept_search import ConceptIndex, render_values


class _FakeEmbedder:
    """Returns a fixed vector per input text, so nearest-neighbor distance is
    deterministic in tests -- no real Gemini call, no real semantics."""

    def __init__(self, vectors: dict[str, list[float]]):
        self._vectors = vectors

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._vectors[text] for text in texts]


class _FakeKeyEmbeddingDatabase:
    """Stands in for the Database port over attribute_key_embeddings JOIN
    attribute_keys. `rows` is (key, occurrences, samples_json, vector)."""

    def __init__(self, rows):
        self._rows = rows

    def query(self, sql, params=None):
        query_vector = params[0]
        limit = params[1]
        scored = sorted(self._rows, key=lambda row: _distance(row[3], query_vector))
        top = scored[:limit]
        return pd.DataFrame(
            [(key, occ, samples) for key, occ, samples, _ in top],
            columns=["key", "occurrences", "samples_json"])


class _FakeValueEmbeddingDatabase:
    """Stands in for the Database port over column_value_embeddings.
    `rows` is (table_name, column_name, value, vector)."""

    def __init__(self, rows):
        self._rows = rows

    def query(self, sql, params=None):
        query_vector = params[0]
        limit = params[1]
        scored = sorted(self._rows, key=lambda row: _distance(row[3], query_vector))
        top = scored[:limit]
        return pd.DataFrame(
            [(t, c, v) for t, c, v, _ in top],
            columns=["table_name", "column_name", "value"])


def _distance(a, b):
    """Squared Euclidean distance -- good enough to order fixed 2D test vectors;
    the real query uses DuckDB's array_cosine_distance, exercised separately in
    the fixture-backed integration test (Task 6)."""
    return sum((x - y) ** 2 for x, y in zip(a, b))


IBD_VECTOR = [1.0, 0.0]
UNRELATED_VECTOR = [0.0, 1.0]


def test_a_short_acronym_finds_its_semantic_neighbor_key():
    """The bug this feature exists to fix: "IBD" (3 chars) is dropped by substring
    search's MIN_TERM floor, but ibd_sam is real and populous. Embedding search has
    no length floor -- it finds it by meaning, not spelling."""
    keys_db = _FakeKeyEmbeddingDatabase([
        ("ibd_sam", 44976, None, IBD_VECTOR),
        ("unrelated_key", 100, None, UNRELATED_VECTOR),
    ])
    values_db = _FakeValueEmbeddingDatabase([])
    embedder = _FakeEmbedder({"IBD": IBD_VECTOR})
    index = ConceptIndex(keys_db, values_db, embedder=embedder)

    found = index.matching_keys("IBD fecal metagenomic")

    assert "ibd_sam" in found


def test_matching_values_finds_disease_subtypes_for_an_umbrella_term():
    """The metalog case: subject_disease_status has "Crohn's disease" and
    "ulcerative colitis" but no "IBD" literal. Embedding search on the VALUE finds
    both from the umbrella term in the question."""
    keys_db = _FakeKeyEmbeddingDatabase([])
    values_db = _FakeValueEmbeddingDatabase([
        ("metalog_metadata", "subject_disease_status", "Crohn's disease", IBD_VECTOR),
        ("metalog_metadata", "subject_disease_status", "ulcerative colitis", IBD_VECTOR),
        ("metalog_metadata", "geographic_location", "Israel", UNRELATED_VECTOR),
    ])
    embedder = _FakeEmbedder({"IBD": IBD_VECTOR})
    index = ConceptIndex(keys_db, values_db, embedder=embedder)

    found = index.matching_values("IBD cohort")

    assert found["metalog_metadata.subject_disease_status"] == [
        "Crohn's disease", "ulcerative colitis"]
    assert "metalog_metadata.geographic_location" not in found


def test_no_embedder_degrades_to_no_candidates():
    """A CannedLlmBackend (or a failed Gemini call) returns [] from embed() -- this
    must not raise, just contribute nothing."""
    embedder = _FakeEmbedder({})

    class _EmptyEmbedder:
        def embed(self, texts):
            return []

    index = ConceptIndex(_FakeKeyEmbeddingDatabase([]), _FakeValueEmbeddingDatabase([]),
                         embedder=_EmptyEmbedder())

    assert index.matching_keys("IBD") == {}
    assert index.matching_values("IBD") == {}


def test_render_values_formats_the_prompt_block():
    block = render_values({"metalog_metadata.subject_disease_status":
                           ["Crohn's disease", "ulcerative colitis"]})

    assert "subject_disease_status" in block
    assert "Crohn's disease" in block
    assert "ulcerative colitis" in block


def test_render_values_is_empty_when_nothing_matched():
    assert render_values({}) == ""
```

- [ ] **Step 2: Run the tests to verify they fail**

Run: `pytest Tests/test_concept_search.py -v`
Expected: FAIL — `askslm.concept_search` does not exist (`ModuleNotFoundError`).

- [ ] **Step 3: Write the implementation**

```python
# src/askslm/concept_search.py
"""Retrieval for the cases substring search structurally cannot reach: a question's
wording sharing no characters with the field or value that means the same thing.

"IBD" (3 chars) is dropped by attributes.py's MIN_TERM floor before substring search
even runs, and even found, it shares no substring with ibd_sam or "Crohn's disease".
Embedding search finds these by meaning: vectors for the field names and low-cardinality
column values are computed once at mirror-build time
(Scripts/build_mirror/build_concept_embeddings.py); this module embeds the question and
does nearest-neighbor lookup against them. See the design doc for what was measured.
"""
from __future__ import annotations

import pandas as pd

from askslm.ports import Database

EMBED_DIM = 256          # small and cheap: this indexes short field names/values, not
                          # documents. Gemini's default is 3072; requested lower via
                          # output_dimensionality at both build and query time -- the two
                          # MUST match, a query vector of the wrong width is a DuckDB error.

TOP_K_KEYS = 5            # nearest keys per question term
TOP_K_VALUES = 5          # nearest values per question term

MIN_TERM = 3               # floor is 1 char lower than attributes.py's MIN_TERM=5 --
                            # this is the mechanism that exists specifically to reach
                            # short acronyms (IBD, TB, UC) substring search drops.


class ConceptIndex:
    """Question -> candidate keys and candidate values, by embedding similarity.

    Two Database ports because the two embedding tables are unrelated shapes (one
    keyed by jattr key, one keyed by table.column.value) -- matches the "each
    accessor reads one source" convention the rest of the package follows. Both are
    typically the SAME underlying DuckDbConnection at the composition root; they are
    separate constructor arguments so a test can fake either independently.
    """

    def __init__(self, key_embeddings: Database, value_embeddings: Database, embedder):
        self._key_embeddings = key_embeddings
        self._value_embeddings = value_embeddings
        self._embedder = embedder

    def matching_keys(self, question: str) -> dict[str, tuple[int, str | None]]:
        """key -> (occurrences, samples_json), same shape as AttributeIndex.matching()
        so the two can be unioned before the MAX_KEYS budget is applied."""
        found: dict[str, tuple[int, str | None]] = {}
        for term, vector in self._term_vectors(question):
            for row in self._nearest_keys(vector=vector).itertuples(index=False):
                found.setdefault(row.key, (row.occurrences, row.samples_json))
        return found

    def matching_values(self, question: str) -> dict[str, list[str]]:
        """"table.column" -> matched values, in nearest-first order, de-duplicated."""
        found: dict[str, list[str]] = {}
        for term, vector in self._term_vectors(question):
            for row in self._nearest_values(vector=vector).itertuples(index=False):
                _add_value(found=found, row=row)
        return found

    def _term_vectors(self, question: str) -> list[tuple[str, list[float]]]:
        """One embed() call for every term at once -- the "one live call per ask()"
        the design commits to, not one call per term."""
        terms = _terms(question)
        if not terms:
            return []
        vectors = self._embedder.embed(terms)
        if not vectors:
            return []
        return list(zip(terms, vectors))

    def _nearest_keys(self, vector: list[float]) -> pd.DataFrame:
        return self._key_embeddings.query(
            "SELECT k.key, k.occurrences, k.samples_json "
            "FROM attribute_key_embeddings e JOIN attribute_keys k USING (key) "
            f"ORDER BY array_cosine_distance(e.vector, ?::FLOAT[{EMBED_DIM}]) LIMIT ?",
            [vector, TOP_K_KEYS])

    def _nearest_values(self, vector: list[float]) -> pd.DataFrame:
        return self._value_embeddings.query(
            "SELECT table_name, column_name, value FROM column_value_embeddings "
            f"ORDER BY array_cosine_distance(vector, ?::FLOAT[{EMBED_DIM}]) LIMIT ?",
            [vector, TOP_K_VALUES])


def _add_value(found: dict[str, list[str]], row) -> None:
    key = f"{row.table_name}.{row.column_name}"
    values = found.setdefault(key, [])
    if row.value not in values:
        values.append(row.value)


def _terms(question: str) -> list[str]:
    words = "".join(character if character.isalnum() else " "
                    for character in question).split()
    return sorted({word for word in words if len(word) >= MIN_TERM})


def render_values(matches: dict[str, list[str]]) -> str:
    """The prompt block for value-level concept matches. Empty when nothing matched,
    same convention as attributes.py's render()."""
    if not matches:
        return ""
    lines = ["CONCEPT MATCHES (values found by meaning, not literal wording)",
             "  These are REAL values of the named column -- OR them together with =",
             "  when the question names the broader concept they all belong to."]
    for column, values in matches.items():
        quoted = ", ".join(f'"{value}"' for value in values)
        lines.append(f"  {column}: {quoted}")
    return "\n".join(lines)
```

**Design notes surfaced by writing the tests** (flag these to the user before continuing —
they are implementation judgment calls the spec didn't pin down):
- `_terms()` here does NOT lowercase (unlike `attributes.py._terms()`), because case is
  meaningful to an embedding model in a way it isn't to a substring `LIKE`. `MIN_TERM = 3`
  admits "IBD"/"TB"/"UC" specifically; verify this doesn't reintroduce stopword noise once
  real embeddings are in use (a 3-letter word's nearest neighbor is still constrained by
  `TOP_K_KEYS`/`TOP_K_VALUES`, unlike substring search's unbounded match count).
- `TOP_K_KEYS`/`TOP_K_VALUES` are a bounded top-N, not a distance threshold. A calibrated
  distance cutoff (this codebase's existing style — see `schema_catalog`'s measured
  constants) needs a corpus of real embeddings to tune against, which doesn't exist until
  Task 8's ETL run. Revisit after the eval run in Task 9.

- [ ] **Step 4: Run the tests to verify they pass**

Run: `pytest Tests/test_concept_search.py -v`
Expected: PASS

- [ ] **Step 5: Re-run Task 1's tests now that `EMBED_DIM` exists**

Run: `pytest Tests/test_adapters.py -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add src/askslm/concept_search.py Tests/test_concept_search.py
git commit -m "feat: add ConceptIndex, embedding-based key/value retrieval"
```

---

### Task 3: Wire `ConceptIndex` into `AttributeIndex` and `Translator`

**Files:**
- Modify: `src/askslm/attributes.py`
- Modify: `src/askslm/translation.py`
- Modify: `Tests/test_attributes.py`
- Modify: `Tests/test_translator.py`

- [ ] **Step 1: Write the failing test for `AttributeIndex`**

Add to `Tests/test_attributes.py`:

```python
class _StubSemantic:
    def __init__(self, matches):
        self._matches = matches

    def matching_keys(self, question):
        return self._matches


def test_a_semantic_match_is_unioned_with_substring_matches():
    """The whole point of Task 3: ibd_sam, found only by embedding similarity (no
    substring in common with "IBD"), must still reach the rendered prompt block."""
    index = AttributeIndex(_FakeDatabase([("calprotectin_sam", 2342, None)]),
                           semantic=_StubSemantic({"ibd_sam": (44976, None)}))

    found = index.matching("IBD fecal metagenomic with calprotectin")

    assert "calprotectin_sam" in found
    assert "ibd_sam" in found


def test_no_semantic_collaborator_behaves_as_before():
    """semantic=None (the default) must not change existing behavior -- every
    existing test in this file constructs AttributeIndex without it."""
    index = AttributeIndex(_FakeDatabase([("calprotectin_sam", 2342, None)]))

    found = index.matching("with calprotectin")

    assert "calprotectin_sam" in found
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest Tests/test_attributes.py -v -k semantic`
Expected: FAIL — `AttributeIndex.__init__()` has no `semantic` parameter (`TypeError`).

- [ ] **Step 3: Modify `AttributeIndex`**

In `src/askslm/attributes.py`, change the constructor and `matching()`:

```python
    def __init__(self, database: Database, expander=None, semantic=None):
        self._database = database
        self._expander = expander
        self._semantic = semantic

    def matching(self, question: str) -> dict[str, tuple[int, str | None]]:
        """key -> (occurrences, samples_json), for keys a term of the question names
        OR a semantic neighbor of the question's meaning.

        The budget is per TERM for substring matches (see the class docstring); the
        semantic matches from ConceptIndex are unioned in afterward, since they carry
        their own top-K bound (TOP_K_KEYS in concept_search.py) and don't need the same
        per-term slot protection -- there's no "broad term crowds out a precise one"
        failure mode when every term already returns at most TOP_K_KEYS candidates.
        """
        found: dict[str, tuple[int, str | None]] = {}
        for term in self._search_terms(question):
            for key, row in self._for_term(term).items():
                found.setdefault(key, row)
        if self._semantic is not None:
            for key, row in self._semantic.matching_keys(question).items():
                found.setdefault(key, row)
        return dict(sorted(found.items(), key=_by_occurrences)[:MAX_KEYS])
```

(Only `__init__` and `matching()` change; `_search_terms`, `_is_generic`, `_for_term`
are untouched.)

- [ ] **Step 4: Run to verify it passes**

Run: `pytest Tests/test_attributes.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Write the failing test for `Translator`**

Add to `Tests/test_translator.py`:

```python
class StubConcepts:
    def __init__(self, values: dict | None = None):
        self._values = values or {}

    def matching_values(self, question: str):
        return self._values


def test_a_semantic_value_match_lands_in_the_prompt():
    """The metalog half of the feature: subject_disease_status's real values,
    found by meaning, must reach the schemas string the same way attribute keys do."""
    backend = SpyBackend()
    translator = Translator(backend, StubCatalog(), StubAttributes(),
                            StubConcepts({"metalog_metadata.subject_disease_status":
                                         ["Crohn's disease", "ulcerative colitis"]}))

    translator.translate(ResearchQuestion("IBD cohort"))

    assert "Crohn's disease" in backend.prompt.schemas
    assert "ulcerative colitis" in backend.prompt.schemas


def test_no_concepts_collaborator_behaves_as_before():
    """concepts=None (the default) must not change existing behavior -- every
    existing test in this file constructs Translator without it."""
    backend = SpyBackend()
    translator = Translator(backend, StubCatalog(), StubAttributes())

    translator.translate(ResearchQuestion("adults with IBD"))

    assert "IBD" in backend.prompt.schemas
```

- [ ] **Step 6: Run to verify it fails**

Run: `pytest Tests/test_translator.py -v -k concept`
Expected: FAIL — `Translator.__init__()` has no `concepts` parameter (`TypeError`).

- [ ] **Step 7: Modify `Translator`**

In `src/askslm/translation.py`:

Add the import to the top of `src/askslm/translation.py`, alongside the existing
`from askslm.attributes import render as render_attributes`:

```python
from askslm.concept_search import render_values as render_concept_values
```

```python
class Translator:
    def __init__(self, backend: LlmBackend, catalog, attributes, concepts=None):
        self._backend = backend
        self._catalog = catalog
        self._attributes = attributes
        self._concepts = concepts

    def translate(self, question: ResearchQuestion) -> Translation:
        return self._backend.translate(
            TranslationPrompt(question=question, schemas=self._schemas(question)))

    def _schemas(self, question: ResearchQuestion) -> str:
        blocks = [self._catalog.all(),
                  render_attributes(self._attributes.matching(question.text)),
                  self._concept_values_block(question)]
        return "\n\n".join(block for block in blocks if block)

    def _concept_values_block(self, question: ResearchQuestion) -> str:
        if self._concepts is None:
            return ""
        return render_concept_values(self._concepts.matching_values(question.text))
```

- [ ] **Step 8: Run to verify it passes**

Run: `pytest Tests/test_translator.py -v`
Expected: PASS (all tests)

- [ ] **Step 9: Commit**

```bash
git add src/askslm/attributes.py src/askslm/translation.py Tests/test_attributes.py Tests/test_translator.py
git commit -m "feat: union embedding-based candidates into attribute and value retrieval"
```

---

### Task 4: `DuckDbConnection` loads the `vss` extension

**Files:**
- Modify: `src/askslm/adapters.py`
- Test: `Tests/test_runtime_gpu.py` pattern (add alongside, see Step 1)

Reading a persisted HNSW index only requires `LOAD vss` at connect time — verified
against the real mirror: the experimental-persistence flag is needed when the index is
*built* (Task 5's ETL script), not when it's read.

- [ ] **Step 1: Write the failing test**

```python
# add to a new Tests/test_duckdb_connection.py
"""DuckDbConnection must load vss so array_cosine_distance and HNSW indexes work --
without it, any query touching the embedding tables raises a Catalog Error."""
from askslm.adapters import DuckDbConnection
from fixtures.mirror import build_fixture_mirror


def test_vss_functions_are_usable_after_connecting(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)

    result = connection.query(
        "SELECT array_cosine_distance([1.0,0.0]::FLOAT[2], [1.0,0.0]::FLOAT[2]) AS d")

    assert result["d"][0] == 0.0
    connection.close()
```

- [ ] **Step 2: Run to verify it fails**

Run: `pytest Tests/test_duckdb_connection.py -v`
Expected: FAIL — `Catalog Error: Scalar Function with name array_cosine_distance does not exist!`

- [ ] **Step 3: Load `vss` in `DuckDbConnection.__init__`**

In `src/askslm/adapters.py`, modify `DuckDbConnection.__init__`:

```python
    def __init__(self, db_path: Path, gpu: bool = False):
        self._connection = duckdb.connect(str(db_path), read_only=True)
        self._connection.execute("INSTALL vss")
        self._connection.execute("LOAD vss")
        self._attach_sources()
        self._gpu = gpu
        if gpu:
            self._connection.execute(f"LOAD '{SIRIUS_EXTENSION_PATH}'")
            self._connection.execute("SELECT gpu_buffer_init()")
```

- [ ] **Step 4: Run to verify it passes**

Run: `pytest Tests/test_duckdb_connection.py -v`
Expected: PASS

- [ ] **Step 5: Run the full existing suite to confirm no regression**

Run: `pytest Tests/ -v`
Expected: PASS (all tests, including everything from Tasks 1-3)

- [ ] **Step 6: Commit**

```bash
git add src/askslm/adapters.py Tests/test_duckdb_connection.py
git commit -m "feat: load vss extension on connect, for embedding nearest-neighbor queries"
```

---

### Task 5: ETL — `build_concept_embeddings.py`

**Files:**
- Create: `Scripts/build_mirror/build_concept_embeddings.py`
- Test: `Scripts/build_mirror/test_build_concept_embeddings.py`

Follows `build_attribute_index.py`/`build_schema_catalog.py`'s pattern: a class with a
`build()` method, run manually against the mirror via `python Scripts/build_mirror/....py
--db path`. Unlike those two, this one calls an LLM (for embeddings), so the embedder is
**injected** — exactly like `GeminiBackend`'s client — so tests run with no network.

- [ ] **Step 1: Write the failing tests**

```python
# Scripts/build_mirror/test_build_concept_embeddings.py
"""Embeds attribute_keys and low-cardinality schema_catalog values into two new
tables. Uses a fake embedder throughout -- this must never call the real Gemini API
in a test run."""
import sys
from pathlib import Path

import duckdb
import pytest

sys.path.insert(0, str(Path(__file__).parent))
from build_concept_embeddings import ConceptEmbeddingBuilder


class _FakeEmbedder:
    """Deterministic: every vector is [len(text), 0.0] -- enough to prove wiring
    (right number of rows, right dimensionality) without needing real semantics."""

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [[float(len(text)), 0.0] for text in texts]


@pytest.fixture
def db_path(tmp_path):
    path = tmp_path / "mini.duckdb"
    con = duckdb.connect(str(path))
    con.execute("CREATE TABLE attribute_keys (key TEXT, occurrences BIGINT, samples_json TEXT)")
    con.executemany("INSERT INTO attribute_keys VALUES (?, ?, ?)", [
        ("ibd_sam", 44976, None),
        ("calprotectin_sam", 2342, '["435.0"]'),
    ])
    con.execute("""CREATE TABLE schema_catalog (
        table_name TEXT, column_name TEXT, data_type TEXT,
        distinct_count BIGINT, truncated BOOLEAN, values_json TEXT)""")
    con.executemany("INSERT INTO schema_catalog VALUES (?, ?, ?, ?, ?, ?)", [
        ("metalog_metadata", "subject_disease_status", "VARCHAR", 3, False,
         '["Crohn\'s disease", "ulcerative colitis", "healthy control"]'),
        ("sra_metadata", "sample_name", "VARCHAR", 30505772, True, '["GB_513_1"]'),
    ])
    con.close()
    return path


def test_every_key_gets_one_embedding_row(db_path):
    ConceptEmbeddingBuilder(db_path, embedder=_FakeEmbedder(), dim=2).build()

    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute("SELECT key FROM attribute_key_embeddings ORDER BY key").fetchall()
    con.close()

    assert rows == [("calprotectin_sam",), ("ibd_sam",)]


def test_only_complete_untruncated_vocabularies_are_embedded(db_path):
    """sample_name is truncated (near-unique, 30.5M distinct on the real mirror) --
    embedding it would be a per-row dump, not a vocabulary. Only the complete,
    low-cardinality columns qualify."""
    ConceptEmbeddingBuilder(db_path, embedder=_FakeEmbedder(), dim=2).build()

    con = duckdb.connect(str(db_path), read_only=True)
    rows = con.execute(
        "SELECT DISTINCT table_name, column_name FROM column_value_embeddings").fetchall()
    con.close()

    assert rows == [("metalog_metadata", "subject_disease_status")]


def test_every_value_of_a_qualifying_column_gets_a_row(db_path):
    ConceptEmbeddingBuilder(db_path, embedder=_FakeEmbedder(), dim=2).build()

    con = duckdb.connect(str(db_path), read_only=True)
    values = con.execute(
        "SELECT value FROM column_value_embeddings ORDER BY value").fetchall()
    con.close()

    assert values == [("Crohn's disease",), ("healthy control",), ("ulcerative colitis",)]


def test_vectors_have_the_requested_dimensionality(db_path):
    ConceptEmbeddingBuilder(db_path, embedder=_FakeEmbedder(), dim=2).build()

    con = duckdb.connect(str(db_path), read_only=True)
    vector = con.execute(
        "SELECT vector FROM attribute_key_embeddings WHERE key = 'ibd_sam'").fetchone()[0]
    con.close()

    assert len(vector) == 2
```

- [ ] **Step 2: Run to verify they fail**

Run: `pytest Scripts/build_mirror/test_build_concept_embeddings.py -v`
Expected: FAIL — module does not exist.

- [ ] **Step 3: Write the implementation**

```python
# Scripts/build_mirror/build_concept_embeddings.py
"""Embed attribute_keys and low-cardinality schema_catalog values, so a question can
find a field or value that means the same thing without sharing its spelling.

Run AFTER build_attribute_index.py and build_schema_catalog.py -- this reads both of
their output tables. Batches every text into as few embed() calls as the batch size
allows: one call per BATCH_SIZE items, not one call per item, because the real mirror
has ~36,000 keys plus however many low-cardinality column values.

    python Scripts/build_mirror/build_concept_embeddings.py --db askslm_mirror.duckdb --api-key $ASKSLM_LLM_KEY
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import duckdb

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))
from askslm.concept_search import EMBED_DIM

DEFAULT_BATCH_SIZE = 100    # conservative default for the embedding API's batch limit;
                            # raise it if the real API accepts more in one call --
                            # verify against the live endpoint before trusting a bigger
                            # number, this was not measured against the real API limit.


class ConceptEmbeddingBuilder:
    """Two tables: attribute_key_embeddings (every jattr key) and
    column_value_embeddings (every value of every low-cardinality metadata column)."""

    def __init__(self, db_path: Path, embedder, dim: int = EMBED_DIM,
                batch_size: int = DEFAULT_BATCH_SIZE):
        self.db_path = db_path
        self.embedder = embedder
        self.dim = dim
        self.batch_size = batch_size

    def build(self) -> None:
        con = duckdb.connect(str(self.db_path))
        self._build_key_embeddings(con=con)
        self._build_value_embeddings(con=con)
        self._report(con=con)
        con.close()

    def _build_key_embeddings(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("DROP TABLE IF EXISTS attribute_key_embeddings")
        con.execute(f"CREATE TABLE attribute_key_embeddings (key TEXT, vector FLOAT[{self.dim}])")
        keys = [row[0] for row in con.execute("SELECT key FROM attribute_keys").fetchall()]
        vectors = self._embed_in_batches(texts=keys)
        con.executemany("INSERT INTO attribute_key_embeddings VALUES (?, ?)",
                        list(zip(keys, vectors)))
        self._create_hnsw_index(con=con, table="attribute_key_embeddings")

    def _build_value_embeddings(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("DROP TABLE IF EXISTS column_value_embeddings")
        con.execute(f"""CREATE TABLE column_value_embeddings (
            table_name TEXT, column_name TEXT, value TEXT, vector FLOAT[{self.dim}])""")
        columns = self._qualifying_columns(con=con)
        vectors = self._embed_in_batches(texts=[value for _, _, value in columns])
        rows = [(table, column, value, vector)
                for (table, column, value), vector in zip(columns, vectors)]
        con.executemany("INSERT INTO column_value_embeddings VALUES (?, ?, ?, ?)", rows)
        self._create_hnsw_index(con=con, table="column_value_embeddings")

    def _embed_in_batches(self, texts: list[str]) -> list[list[float]]:
        """Shared by both tables: same batching, same embedder, different callers.
        Not premature abstraction -- both call sites need it right now, unchanged."""
        vectors: list[list[float]] = []
        for batch in _chunks(items=texts, size=self.batch_size):
            vectors.extend(self.embedder.embed(batch))
        return vectors

    def _create_hnsw_index(self, con: duckdb.DuckDBPyConnection, table: str) -> None:
        con.execute("SET hnsw_enable_experimental_persistence = true")
        con.execute(f"CREATE INDEX {table}_idx ON {table} USING HNSW (vector) "
                    "WITH (metric = 'cosine')")

    def _qualifying_columns(self, con: duckdb.DuckDBPyConnection) -> list[tuple[str, str, str]]:
        """Only columns schema_catalog already shows a COMPLETE vocabulary for --
        truncated or NULL-valued columns are identifiers or free text, not vocabulary
        (see build_schema_catalog.py's _is_identifier)."""
        rows = con.execute(
            "SELECT table_name, column_name, values_json FROM schema_catalog "
            "WHERE truncated = false AND values_json IS NOT NULL").fetchall()
        return [(table_name, column_name, value)
                for table_name, column_name, values_json in rows
                for value in json.loads(values_json)]

    def _report(self, con: duckdb.DuckDBPyConnection) -> None:
        keys, values = con.execute(
            "SELECT (SELECT count(*) FROM attribute_key_embeddings), "
            "       (SELECT count(*) FROM column_value_embeddings)").fetchone()
        print(f"attribute_key_embeddings: {keys} keys · "
              f"column_value_embeddings: {values} values")


def _chunks(items: list, size: int) -> list[list]:
    return [items[i:i + size] for i in range(0, len(items), size)]


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--api-key", required=True)
    parser.add_argument("--dim", type=int, default=EMBED_DIM)
    parser.add_argument("--batch-size", type=int, default=DEFAULT_BATCH_SIZE)
    args = parser.parse_args()

    from askslm.adapters import open_gemini

    embedder = open_gemini(args.api_key, "gemini-2.5-flash")  # model unused by embed()
    ConceptEmbeddingBuilder(args.db, embedder, args.dim, args.batch_size).build()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run to verify the tests pass**

Run: `pytest Scripts/build_mirror/test_build_concept_embeddings.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add Scripts/build_mirror/build_concept_embeddings.py Scripts/build_mirror/test_build_concept_embeddings.py
git commit -m "feat: ETL step embedding attribute keys and low-cardinality column values"
```

---

### Task 6: Fixture mirror builds the embedding tables

**Files:**
- Modify: `Tests/fixtures/mirror.py`

The fixture must carry both new tables so `AttributeIndex`/`ConceptIndex` integration
tests (Task 7) and any future test can run against something with the real shape. Uses a
deterministic fake embedder — the fixture must stay network-free.

- [ ] **Step 1: Add a deterministic fixture embedder and wire the builder in**

In `Tests/fixtures/mirror.py`, add the import and a fixture-local fake embedder:

```python
from build_concept_embeddings import ConceptEmbeddingBuilder
```

(add alongside the existing `from build_attribute_index import ...` /
`from build_schema_catalog import ...` imports)

```python
class _FixtureEmbedder:
    """Deterministic, hand-placed vectors for the specific terms the fixture's own
    tests need to be semantic neighbors of each other -- NOT a real embedding model.
    "IBD" and both real disease values map to the same point; everything else maps
    to a distinct point per distinct string, so no two unrelated strings collide."""

    _KNOWN = {
        "IBD": [1.0, 0.0],
        "Crohn's disease": [1.0, 0.0],
        "ulcerative colitis": [1.0, 0.0],
        "ibd_sam": [1.0, 0.0],
    }

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._KNOWN.get(text, [0.0, float(len(text))]) for text in texts]
```

Add the call at the end of `build_fixture_mirror`, after the existing two builder calls:

```python
    SchemaCatalogBuilder(path, max_distinct=5).build()
    AttributeIndexBuilder(path).build()
    ConceptEmbeddingBuilder(path, embedder=_FixtureEmbedder(), dim=2).build()

    return path
```

Also add `"ibd_sam"` as a jattr key on at least one fixture row, so
`attribute_key_embeddings` has something meaningful in it. In `_sra_metadata_row`,
change the `jattr` field (currently always `'{"host_age":"%d"}' % (25 + index)`) for
ONE specific biosample:

```python
def _sra_metadata_row(run: str, biosample: str, index: int) -> tuple:
    jattr = '{"host_age":"%d","ibd_sam":"true"}' % (25 + index) if biosample == "SAMN00009" \
        else '{"host_age":"%d"}' % (25 + index)
    return (
        run,
        biosample,
        f"PRJNA{900 + index % 3}",
        "WGS",
        "human gut metagenome",
        "METAGENOMIC",
        "ILLUMINA",
        COUNTRIES[index % len(COUNTRIES)],
        f"2021-0{index % 9 + 1}-15",
        jattr,
        [COUNTRIES[index % len(COUNTRIES)]],
    )
```

- [ ] **Step 2: Run the existing fixture-dependent test suite to confirm no regression**

Run: `pytest Tests/ -v`
Expected: PASS (all tests -- `AttributeIndexBuilder`'s existing assertions on
`host_age` are untouched, `ibd_sam` is additive on one row only)

- [ ] **Step 3: Commit**

```bash
git add Tests/fixtures/mirror.py
git commit -m "test: fixture mirror carries concept embedding tables"
```

---

### Task 7: End-to-end proof against the fixture

**Files:**
- Test: `Tests/test_concept_search_integration.py`

The unit tests in Task 2 use fake `Database` ports with hand-computed distance. This
task proves the real SQL (`array_cosine_distance`, `vss`, the JOIN) works against a real
DuckDB file, closing the gap between "the logic is right" and "the query runs."

- [ ] **Step 1: Write the test**

```python
# Tests/test_concept_search_integration.py
"""Proves the real SQL against a real DuckDB file -- the unit tests in
test_concept_search.py fake the Database port; this one does not."""
from askslm.adapters import DuckDbConnection
from askslm.concept_search import ConceptIndex
from fixtures.mirror import build_fixture_mirror


class _FixtureEmbedder:
    """Same mapping as Tests/fixtures/mirror.py's _FixtureEmbedder -- duplicated here
    deliberately rather than imported, so this test does not reach into the ETL
    script's test-only helper. If the two drift, this test is what catches it."""

    _KNOWN = {"IBD": [1.0, 0.0]}

    def embed(self, texts: list[str]) -> list[list[float]]:
        return [self._KNOWN.get(text, [0.0, float(len(text))]) for text in texts]


def test_a_short_acronym_finds_ibd_sam_through_real_duckdb_vss(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    index = ConceptIndex(connection, connection, embedder=_FixtureEmbedder())

    found = index.matching_keys("IBD")

    assert "ibd_sam" in found
    connection.close()


def test_ibd_finds_both_disease_subtypes_through_real_duckdb_vss(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    index = ConceptIndex(connection, connection, embedder=_FixtureEmbedder())

    found = index.matching_values("IBD")

    values = found.get("metalog_metadata.subject_disease_status", [])
    assert "Crohn's disease" in values
    assert "ulcerative colitis" in values
    connection.close()
```

- [ ] **Step 2: Run to verify it fails, then passes**

Run: `pytest Tests/test_concept_search_integration.py -v`

If it fails on the FIRST run because Tasks 1-6 aren't all committed yet, that's
expected — this task depends on all of them. Once Tasks 1-6 are done: Expected: PASS.

- [ ] **Step 3: Run the full suite one more time**

Run: `pytest Tests/ Scripts/build_mirror/ -v`
Expected: PASS, everything.

- [ ] **Step 4: Commit**

```bash
git add Tests/test_concept_search_integration.py
git commit -m "test: prove embedding retrieval end to end against real DuckDB vss"
```

---

### Task 8: Wire into the composition root

**Files:**
- Modify: `src/askslm/runtime.py`

- [ ] **Step 1: Wire `ConceptIndex` into `translator()`**

In `src/askslm/runtime.py`:

```python
from askslm.concept_search import ConceptIndex
```

(add to the existing `from askslm...` import block, alphabetically with the others)

```python
def translator() -> Translator:
    db = database()
    llm = backend()
    concepts = ConceptIndex(db, db, embedder=llm)
    return Translator(llm, SchemaCatalog(db),
                      AttributeIndex(db, expander=llm, semantic=concepts), concepts)
```

`db` is passed as both `key_embeddings` and `value_embeddings` — at the composition
root there is exactly one `DuckDbConnection`, which is the real mirror carrying both
tables; `ConceptIndex`'s two-port constructor exists for test isolation (Task 2), not
because production ever uses two different databases.

- [ ] **Step 2: No new test needed here** — `runtime.py`'s existing coverage
(`Tests/test_runtime_gpu.py` and the config-validation tests in `test_translator.py`)
exercises this wiring indirectly through `askslm.config()` + `ask()`. Confirm by running
the full suite:

Run: `pytest Tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/askslm/runtime.py
git commit -m "feat: wire ConceptIndex into the composition root"
```

---

### Task 9: Eval cases

**Files:**
- Modify: `Scripts/eval/questions.jsonl`

Two cases, gold SQL to be verified against the real mirror before this task is marked
done (not against the fixture — the eval set's own header requires real-mirror
verification). Both were already spot-checked manually in the design conversation; this
task is about landing them in the file correctly, with the disclaimer marker agreed on.

- [ ] **Step 1: Re-verify the IBD gold SQL against the real mirror**

```bash
ssh biu 'source ~/.bashrc; conda activate askslm; python3 -c "
import duckdb
con = duckdb.connect(\"/private/pinto-lab/tools/just-ask/mirror/askslm_mirror.duckdb\", read_only=True)
n = con.execute(\"SELECT count(*) FROM sra_metadata WHERE bioproject = %s AND (json_extract_string(jattr, \x27\$.ibd_sam\x27) IS NOT NULL OR json_extract_string(jattr, \x27\$.host_disease_sam\x27) ILIKE %s)\" % (chr(39)+\"PRJNA1265906\"+chr(39), chr(39)+\"%25inflammatory%25\"+chr(39))).fetchone()
print(n)
"'
```

Record the real row count returned — it becomes the comment justifying the gold row
below (do not invent a count; use what this command actually returns).

- [ ] **Step 2: Add the two cases**

Append to `Scripts/eval/questions.jsonl` (before the closing of the file, as new JSON
lines — this file is JSONL, one object per line, with `//`-prefixed comment lines
allowed per its existing header):

```
{"question": "adults with inflammatory bowel disease, fecal calprotectin measured", "gold": {"SRA_METADATA": "SELECT biosample FROM sra_metadata WHERE bioproject = 'PRJNA1265906' AND json_extract_string(jattr, '$.fecalcalprotectin_run') IS NOT NULL"}, "_note": "verified executable against real mirror by Claude 2026-08-25 (returns the PRJNA1265906/SRP586738 cohort with real fecalcalprotectin_run values); scientific correctness of the gold SQL's criteria not yet confirmed by researcher"}
{"question": "shotgun metagenomic sequencing of the human gut", "gold": {"SRA_METADATA": "SELECT biosample FROM sra_metadata WHERE librarysource = 'METAGENOMIC' AND organism ILIKE '%gut metagenome%'"}, "_note": "verified executable against real mirror by Claude 2026-08-25 (librarysource enum value confirmed: GENOMIC/METAGENOMIC/VIRAL RNA/TRANSCRIPTOMIC/.../OTHER -- AMPLICON is not a librarysource value on this mirror, confirm the 16S-exclusion case still needs a different column before trusting this as the negative example); scientific correctness not yet confirmed by researcher"}
```

**Flag to the user:** the second case's `_note` says something the design conversation
assumed but never actually verified — `librarysource`'s real distinct values (checked
earlier: `GENOMIC, METAGENOMIC, VIRAL RNA, TRANSCRIPTOMIC, TRANSCRIPTOMIC SINGLE CELL,
OTHER, METATRANSCRIPTOMIC, GENOMIC SINGLE CELL, SYNTHETIC`) contain **no `AMPLICON`
value**. 16S/amplicon exclusion, if it exists in the real data, must live in a different
column (`librarystrategy` was queried and errored as nonexistent;
`libraryselection`/`library_name` were listed as candidates but never checked). This
eval case is weaker than intended until that's confirmed — it tests the positive match,
not the exclusion the shotgun-vs-16S example was meant to demonstrate. Confirm the real
exclusion column before treating this case as validating anything about exclusions.

- [ ] **Step 3: Commit**

```bash
git add Scripts/eval/questions.jsonl
git commit -m "test: add two eval cases for embedding-based concept retrieval"
```

---

### Task 10: Build the real embeddings and run the eval

**This task runs against the real mirror and spends real (free-tier) API calls — not
something to automate unattended. Run it yourself, in order:**

- [ ] **Step 1: Baseline eval run, BEFORE the embedding tables exist**

```bash
ssh biu
cd /private/pinto-lab/tools/just-ask/pkg   # or wherever the package is checked out
git pull && git checkout feature/concept-embedding-search
conda activate askslm
python Scripts/eval/run_eval.py --db /private/pinto-lab/tools/just-ask/mirror/askslm_mirror.duckdb \
    --llm-key $ASKSLM_LLM_KEY > /tmp/eval_before.txt
```

Record the score. The two new cases are expected to FAIL here (or at best pass by luck
on synonym-guessing alone) — this is the regression baseline.

- [ ] **Step 2: Build the embedding tables on the real mirror**

```bash
python Scripts/build_mirror/build_attribute_index.py --db askslm_mirror.duckdb   # if not already current
python Scripts/build_mirror/build_schema_catalog.py --db askslm_mirror.duckdb    # if not already current
python Scripts/build_mirror/build_concept_embeddings.py --db askslm_mirror.duckdb --api-key $ASKSLM_LLM_KEY
```

Expect this to take a while — ~36,000 keys plus the low-cardinality column values,
batched at 100 per call (`DEFAULT_BATCH_SIZE`). Watch the printed report line
(`attribute_key_embeddings: N keys · column_value_embeddings: M values`) for sane
numbers before continuing — N should be close to the real mirror's known ~35,768 keys.

- [ ] **Step 3: Eval run AFTER the embedding tables exist**

```bash
python Scripts/eval/run_eval.py --db /private/pinto-lab/tools/just-ask/mirror/askslm_mirror.duckdb \
    --llm-key $ASKSLM_LLM_KEY > /tmp/eval_after.txt
diff /tmp/eval_before.txt /tmp/eval_after.txt
```

Expected: no regression on the existing (3 placeholder + any real) cases, and the two
new cases from Task 9 now pass.

- [ ] **Step 4: If it doesn't work — do not force it**

If the new cases still fail after this, do not tune `TOP_K_KEYS`/`TOP_K_VALUES` blindly.
Log what the translator's prompt actually contained (the existing `_logger.info` calls in
`adapters.py` already record it) and look at whether `matching_keys`/`matching_values`
found the right candidates but the translation LLM still didn't use them (a prompt
wording problem) versus not finding them at all (a retrieval problem — check `TOP_K_*`,
`EMBED_DIM`, or whether `gemini-embedding-001` is still the current recommended model).

- [ ] **Step 5: No commit for this task** — it's a manual verification run, not a code
change. If Step 4 surfaces a real bug, that becomes a new task, not a silent tweak here.

---

## Style Pass (clean-code-style + ponytail)

Applied to every NEW production function in this plan (`concept_search.py`,
`build_concept_embeddings.py`, `Translator._schemas`): no function over 10 lines, no
`else`, no `lambda`, keyword arguments at call sites for anything past the first
self-evident positional argument. `ConceptIndex.matching_keys`/`matching_values` were
split into `_nearest_keys`/`_nearest_values`/`_add_value` to get under the limit;
`ConceptEmbeddingBuilder`'s two `_build_*` methods share `_embed_in_batches` and
`_create_hnsw_index` — extracted because both call sites need it *now*, not
speculatively (ponytail's bar for a shared helper).

**Where this plan deliberately does NOT retrofit the rule:** `GeminiBackend.embed()`
mirrors the existing shape of its siblings `expand()`/`repair()` in the same class
(both already over 10 lines, pre-existing style) — matched for in-class consistency
rather than diverged for a rule those neighbors don't follow. Calls into pre-existing
signatures (`open_gemini(args.api_key, "gemini-2.5-flash")`, `DuckDbConnection(...)`)
keep the codebase's own established positional-call style rather than being rewritten
— this plan does not retrofit files it isn't otherwise touching for this feature, per
writing-plans' "don't propose unrelated refactoring."

## Self-Review Notes

**Spec coverage:** every section of the design doc has a task — build-time embedding
(Task 5), query-time retrieval (Task 2), union with existing substring search (Task 3),
`vss`/in-mirror storage (Tasks 4-5), live-call-per-ask() (Task 2's `_term_vectors`), eval
cases with disclaimer (Task 9), before/after eval run (Task 10).

**Deviations from the spec surfaced while writing this plan, flagged rather than silently
resolved:**
1. The spec's "shotgun must not match 16S" example assumed an `AMPLICON` value on some
   SRA column; Task 9 found `librarysource` has no such value on the real mirror. The
   eval case was written to still be useful (tests the positive shotgun match) but does
   NOT yet test an exclusion, because the real exclusion column was never confirmed.
2. `TOP_K_KEYS`/`TOP_K_VALUES` are a bounded top-N rather than the spec's implied
   "nearest neighbors," because a calibrated distance threshold needs real embeddings to
   tune against (Task 2's design note). Revisit after Task 10's real run.
3. The metalog value-embedding case may add less than the spec assumed:
   `subject_disease_status`'s full value vocabulary is ALREADY unconditionally rendered
   by `SchemaCatalog.all()` on every question (it's a complete, non-truncated column) --
   the model already sees "Crohn's disease" and "ulcerative colitis" today, with or
   without this feature. Task 10's baseline run (Step 1, BEFORE building embeddings) is
   what actually tells us whether this was ever broken for metalog specifically, or
   whether the real gap is entirely on the SRA jattr-key side. Read that baseline result
   before assuming the value-embedding half of this plan pulls its weight.

**Placeholder scan:** a dead `for ... pass` loop was caught in Task 5 Step 3 during
self-review and removed before this plan was saved — `_build_value_embeddings` now goes
straight from `_qualifying_columns()` to the batched insert, no leftover draft code.

**Type consistency:** `ConceptIndex.matching_keys()` returns
`dict[str, tuple[int, str | None]]` everywhere it's used (Task 2's implementation, Task
3's union in `AttributeIndex.matching()`, Task 2's own tests) — same shape as
`AttributeIndex.matching()`'s existing return type. `matching_values()` returns
`dict[str, list[str]]` consistently across Task 2, Task 3, and `render_values()`.
`ConceptIndex.__init__(key_embeddings, value_embeddings, embedder)` parameter order and
names match every call site (Task 2 tests, Task 7, Task 8's `runtime.py` wiring).
