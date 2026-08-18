# Translation Half Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make `askslm.ask()` work on a real research question in plain English — a real LLM writes the metadata SQL, primed with the mirror's actual column values, and its accuracy is measured rather than eyeballed.

**Architecture:** Three pieces behind the existing `LlmBackend` port. `SchemaCatalog` reads the `schema_catalog` table already built into the mirror and renders it as prompt text (columns + types + real value vocabularies). `Translator` composes catalog + question into a `TranslationPrompt` and hands it to the backend. `GeminiBackend` implements the port against `google-genai`, returning strict JSON. Nothing below the port changes — the walking skeleton's `CannedLlmBackend` stays for tests.

**Tech Stack:** Python 3.12+, DuckDB (read-only), `google-genai` 2.6.0, pytest. No new dependency beyond `google-genai`.

---

## Prerequisites (do this first, once)

The repo forbids working on `main` (enforced by a PreToolUse hook and a git pre-commit hook).

```bash
git fetch origin && git switch -c feature/translation-half origin/main
```

Announce the branch. Every task below commits to it. Do **not** delete branches. When all tasks are done, push and `gh pr create --base main`, then stop — the human squash-merges.

## Context an implementer needs

- **Run tests with:** `python3 -m pytest Tests/ -q` from the repo root. `Tests/conftest.py` puts `src/` on the path; there is no installed package to rebuild.
- **The mirror is opened READ-ONLY.** Never write to it. Any `INSERT`/`UPDATE` is refused by DuckDB itself, which is the design.
- **Two metadata sources only:** `Source.SRA_METADATA` (table `sra_metadata`) and `Source.METALOG_METADATA` (table `metalog_metadata`). The LLM writes SQL for these two and nothing else — every profile-side query is mechanical and generated in code (HLD E.2).
- **What generated SQL must return:** rows carrying `biosample`, or `sample_alias` for Metalog's orphan tail. See `src/askslm/cohort.py:key_column`. A query returning neither yields an empty cohort.
- **House style (enforced in review):** no `lambda` — always a named `def`. Readability over cleverness. Trust input and fail fast: no defensive validation past `config()`. Don't add backward-compat aliases.
- **The spec** is `Docs/superpowers/specs/2026-06-17-askslm-architecture-hld-lld.html`, sections E.2 (translation), F.1 (SchemaCatalog + Translator), H.3 (eval).

## File Structure

| File | Responsibility |
|---|---|
| `src/askslm/catalog.py` | **new.** Reads `schema_catalog` from the mirror; renders prompt text for the metadata sources. |
| `src/askslm/translation.py` | **modify.** Gains `Translator` (composes catalog + question → backend). Existing dataclasses unchanged. |
| `src/askslm/prompt.py` | **new.** The system instruction: the rules the model must follow. Text only, no logic. |
| `src/askslm/adapters.py` | **modify.** Gains `GeminiBackend` alongside `DuckDbConnection` and `CannedLlmBackend`. |
| `src/askslm/runtime.py` | **modify.** `Settings` gains `llm_model`; composition root builds the catalog, translator, and the selected backend. |
| `src/askslm/__init__.py` | **modify.** `ask()` uses the translator instead of `schemas=""`. |
| `Tests/fixtures/mirror.py` | **modify.** The fixture mirror gains a real `schema_catalog` table. |
| `Tests/test_catalog.py` | **new.** Catalog rendering. |
| `Tests/test_translator.py` | **new.** Translator wiring, with a spy backend. |
| `Tests/test_gemini_backend.py` | **new.** Response parsing, with a stubbed client. No network. |
| `Scripts/eval/questions.jsonl` | **new.** The eval set: question + gold SQL per source. Fixture-scale examples ship; the real set is authored by the domain owner. |
| `Scripts/eval/run_eval.py` | **new.** Scores execution accuracy three ways per question. |
| `Tests/test_eval_scoring.py` | **new.** The scorer's own arithmetic, on synthetic sets. |

---

### Task 1: The fixture mirror gains a schema_catalog

`ask()` will read `schema_catalog` on every call, so the fixture must have one or every existing end-to-end test breaks. The builder already exists in `Scripts/build_mirror/build_schema_catalog.py`; `Tests/test_schema_catalog.py` already imports it this way.

**Files:**
- Modify: `Tests/fixtures/mirror.py`
- Test: `Tests/test_fixture_mirror.py`

- [ ] **Step 1: Write the failing test**

Append to `Tests/test_fixture_mirror.py`:

```python
def test_fixture_carries_a_schema_catalog_so_ask_can_prompt(con):
    """ask() reads schema_catalog on every call. A fixture without one is not a mirror."""
    rows = con.execute(
        "SELECT count(*) FROM schema_catalog WHERE table_name = 'metalog_metadata'"
    ).fetchone()[0]

    assert rows > 0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest Tests/test_fixture_mirror.py::test_fixture_carries_a_schema_catalog_so_ask_can_prompt -v`
Expected: FAIL — `duckdb.CatalogException: Table with name schema_catalog does not exist!`

- [ ] **Step 3: Build the catalog inside the fixture**

In `Tests/fixtures/mirror.py`, add this import near the top (after the existing imports):

```python
import sys

_BUILD_MIRROR = Path(__file__).parent.parent.parent / "Scripts" / "build_mirror"
if str(_BUILD_MIRROR) not in sys.path:
    sys.path.insert(0, str(_BUILD_MIRROR))
```

Then, at the very end of `build_fixture_mirror`, after the connection that populates the tables is closed and before the path is returned, add:

```python
    # The real mirror gets its catalog from a separate pass over a finished file, so the
    # fixture does the same -- same code path, same table shape. max_distinct is small
    # here on purpose: the fixture must exercise BOTH the complete-vocabulary and the
    # truncated branch, and its columns have only a handful of values each.
    from build_schema_catalog import SchemaCatalogBuilder

    SchemaCatalogBuilder(path, max_distinct=5).build()
```

If `build_fixture_mirror` currently returns `path` while a connection is still open, close it first — `SchemaCatalogBuilder` opens the file for writing.

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest Tests/ -q`
Expected: PASS, 33 tests (32 existing + 1 new).

- [ ] **Step 5: Commit**

```bash
git add Tests/fixtures/mirror.py Tests/test_fixture_mirror.py
git commit -m "test(fixtures): fixture mirror carries a schema_catalog

ask() is about to read this table on every call, so a fixture without one
stops modelling the real mirror. Built by the same SchemaCatalogBuilder the
lab runs, with max_distinct=5 so the fixture exercises both the complete and
the truncated vocabulary branch."
```

---

### Task 2: SchemaCatalog reader

Renders what the model needs to write correct SQL: columns, types, and the **real** value strings. Values are never cleaned — the model must see that `'\n\t\t\t\tWGS\n\t\t\t'` exists, or its `= 'WGS'` predicate silently drops those rows.

**Files:**
- Create: `src/askslm/catalog.py`
- Test: `Tests/test_catalog.py`

- [ ] **Step 1: Write the failing test**

Create `Tests/test_catalog.py`:

```python
"""The catalog is the model's only view of the data. What it omits, the model invents."""
import pytest

from askslm.adapters import DuckDbConnection
from askslm.catalog import SchemaCatalog

from fixtures.mirror import build_fixture_mirror


@pytest.fixture
def catalog(tmp_path):
    path = build_fixture_mirror(tmp_path / "fixture.duckdb")
    connection = DuckDbConnection(path)
    yield SchemaCatalog(connection)
    connection.close()


def test_names_both_metadata_tables_and_no_profile_table(catalog):
    """The LLM writes metadata SQL only (HLD E.2). A profile table in the prompt
    invites it to write a query nothing will ever run."""
    rendered = catalog.all()

    assert "sra_metadata" in rendered
    assert "metalog_metadata" in rendered
    assert "sra_taxonomy" not in rendered
    assert "metalog_motus3" not in rendered


def test_low_cardinality_columns_ship_their_real_values(catalog):
    """'IBD' has to be matchable against the literal stored in the data. Given only a
    column name the model invents a plausible spelling and gets zero rows back."""
    rendered = catalog.all()

    assert "subject_disease_status" in rendered
    assert "IBD" in rendered


def test_array_columns_are_flagged_so_equality_is_not_used(catalog):
    """geo_loc_name_sam is VARCHAR[]. `WHERE geo_loc_name_sam = 'Israel'` matches
    nothing at all -- silently."""
    rendered = catalog.all()

    line = _line_for(rendered, "geo_loc_name_sam")
    assert "[]" in line
    assert "list_contains" in line


def _line_for(rendered: str, column: str) -> str:
    return next(line for line in rendered.splitlines() if line.strip().startswith(column))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest Tests/test_catalog.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'askslm.catalog'`

- [ ] **Step 3: Write the implementation**

Create `src/askslm/catalog.py`:

```python
"""The mirror's schema, rendered for a prompt: columns, types, and REAL values.

Columns alone are not enough. Nothing in a column list tells a model that IBD is
written in this data as whatever literal occupies `subject_disease_status`, so given
only names it invents a plausible spelling and the query returns zero rows -- which
looks like an empty cohort, not a bug. Shipping the vocabularies is the standard
text-to-SQL fix (schema linking + value retrieval), not an invention. HLD F.1.
"""
from __future__ import annotations

import json

from askslm.ports import Database
from askslm.sources import Source, SourceKind

_ARRAY_HINT = "  -- ARRAY: use list_contains(column, 'value'), never ="


class SchemaCatalog:
    """Reads the `schema_catalog` table the ETL wrote into the mirror.

    Built at ETL time rather than here: a runtime SELECT DISTINCT across 108 Metalog
    columns on every connect is the rejected alternative, and the cardinality cutoff can
    be re-tuned in seconds against the eval set instead of hours.
    """

    def __init__(self, database: Database):
        self._database = database

    def all(self) -> str:
        """Every METADATA source, in one block. The profile tables are deliberately
        absent -- the LLM never writes their SQL (HLD E.2)."""
        return "\n\n".join(self._render(source) for source in _metadata_sources())

    def _render(self, source: Source) -> str:
        table = source.spec().table
        rows = self._database.query(
            "SELECT column_name, data_type, distinct_count, truncated, values_json "
            "FROM schema_catalog WHERE table_name = ? ORDER BY column_name", [table])
        lines = [f"TABLE {table}   (source: {source.name})"]
        lines.extend(_column_line(row) for _, row in rows.iterrows())
        return "\n".join(lines)


def _metadata_sources() -> list[Source]:
    return [source for source in Source if source.kind() is SourceKind.METADATA]


def _column_line(row) -> str:
    line = f"  {row['column_name']}  {row['data_type']}"
    if str(row["data_type"]).endswith("[]"):
        line += _ARRAY_HINT
    return line + _values_suffix(row)


def _values_suffix(row) -> str:
    """Values are rendered RAW. A vocabulary that quietly strips the whitespace out of
    '\\n\\t\\t\\t\\tWGS\\n\\t\\t\\t' teaches the model a literal that is not in the data."""
    if row["values_json"] is None:
        return ""
    values = json.dumps(json.loads(row["values_json"]), ensure_ascii=False)
    if row["truncated"]:
        return (f"\n      {row['distinct_count']} distinct values, showing the most common."
                f" Prefer ILIKE '%pattern%' over =. Sample: {values}")
    return f"\n      values: {values}"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest Tests/test_catalog.py -v`
Expected: PASS, 3 tests.

- [ ] **Step 5: Commit**

```bash
git add src/askslm/catalog.py Tests/test_catalog.py
git commit -m "feat(catalog): render the mirror's columns AND real value vocabularies

Columns alone cannot work: nothing in a column list tells the model that IBD is
stored as whatever literal occupies subject_disease_status, so it invents a
spelling and gets zero rows -- which reads as an empty cohort, not a bug.

Values ship RAW. The real table holds both 'WGS' and '\\n\\t\\t\\t\\tWGS\\n\\t\\t\\t';
a cleaned vocabulary teaches a literal that is not in the data. Array columns
carry an explicit list_contains hint because = matches nothing on VARCHAR[]."
```

---

### Task 3: The system instruction

Isolated in its own module so the eval can attribute an accuracy change to a prompt diff.

**Files:**
- Create: `src/askslm/prompt.py`
- Test: `Tests/test_catalog.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `Tests/test_catalog.py`:

```python
def test_system_instruction_states_the_key_and_the_two_sources():
    """The generated SQL is useless unless it returns the join key, and the model must
    know it is writing TWO independent queries, not one join."""
    from askslm.prompt import SYSTEM_INSTRUCTION

    assert "biosample" in SYSTEM_INSTRUCTION
    assert "sample_alias" in SYSTEM_INSTRUCTION
    assert "SELECT" in SYSTEM_INSTRUCTION
    assert "JOIN" in SYSTEM_INSTRUCTION          # to forbid it across the two sources
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest Tests/test_catalog.py::test_system_instruction_states_the_key_and_the_two_sources -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'askslm.prompt'`

- [ ] **Step 3: Write the implementation**

Create `src/askslm/prompt.py`:

```python
"""What the model is told. Isolated so the eval can attribute an accuracy change to a
prompt diff -- if this lived inside the backend, every prompt experiment would be a
diff against provider code."""
from __future__ import annotations

SYSTEM_INSTRUCTION = """\
You translate a biologist's research question into SQL over a read-only DuckDB
mirror of NCBI SRA and the Metalog collection.

WHAT TO PRODUCE
Write ONE SELECT per metadata source listed in the schema. Today there are two:
SRA_METADATA and METALOG_METADATA. Write them independently.

NEVER join the two sources together. They are separate databases with no shared
vocabulary, and the caller compares their results as sets to learn which samples
each source knows about. A join destroys that comparison. Each query must stand
alone, and one source returning nothing must not affect the other.

EVERY QUERY MUST RETURN THE SAMPLE KEY
Select the `biosample` column. For metalog_metadata also select `sample_alias`,
because some Metalog samples have no BioSample and are addressed by alias.
A query that returns neither yields an empty cohort. `SELECT *` is acceptable.

WRITING PREDICATES
- Use ONLY the values shown in the schema. They are the literal strings stored in
  the data, including any leading or trailing whitespace. Do not tidy them.
- Where a column's values are listed in full, prefer exact equality or IN.
- Where the schema says the list is truncated, prefer ILIKE '%pattern%'.
- For a column whose type ends in [], use list_contains(column, 'value').
  Equality against an array column matches nothing.
- Emit SELECT statements only. The database is read-only.

SCOPE
This is a search tool over anything that can become a feature table, not a
metagenomics-only tool. SRA's taxonomic profiles cover every run NCBI ingests, so
human tumour, mouse, or environmental cohorts are all legitimate. Never add a
metagenome filter the question did not ask for.

WHEN YOU CANNOT TRANSLATE
If the question cannot be expressed against these columns, return no queries and
set `failure` to one plain sentence naming what could not be matched -- for
example "no metadata field records how a subject felt". Do not guess.

OUTPUT
Return JSON only, matching exactly:
{"interpretation": "...", "queries": [{"source": "...", "sql": "..."}],
 "failure": null}
`interpretation` is one line of plain English restating the cohort you selected;
it is shown to the researcher as show-your-work. `source` must be one of the
source names given in the schema block. On failure, `queries` is [].
"""
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest Tests/test_catalog.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 5: Commit**

```bash
git add src/askslm/prompt.py Tests/test_catalog.py
git commit -m "feat(prompt): the system instruction, in its own module

Isolated so the eval can attribute an accuracy change to a prompt diff. States
the three things the SQL is useless without: return the sample key, never join
the two sources (the caller compares them as sets), and use only the literal
values from the schema. Also states that askslm is NOT metagenomics-only, so
the model never adds a filter the question did not ask for."
```

---

### Task 4: Translator

**Files:**
- Modify: `src/askslm/translation.py`
- Test: `Tests/test_translator.py`

- [ ] **Step 1: Write the failing test**

Create `Tests/test_translator.py`:

```python
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
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest Tests/test_translator.py -v`
Expected: FAIL — `ImportError: cannot import name 'Translator' from 'askslm.translation'`

- [ ] **Step 3: Write the implementation**

Append to `src/askslm/translation.py`:

```python
class Translator:
    """Question + schemas -> Translation. The one network step, kept pure.

    Invalid SQL is NOT caught here: it surfaces when CohortPreviewBuilder runs the
    counts (HLD F.3). A Translation may come back carrying `failure` -- the model
    saying it could not translate at all -- which reaches the user as Plan.error.
    """

    def __init__(self, backend, catalog):
        self._backend = backend
        self._catalog = catalog

    def translate(self, question: ResearchQuestion) -> Translation:
        return self._backend.translate(
            TranslationPrompt(question=question, schemas=self._catalog.all()))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest Tests/test_translator.py -v`
Expected: PASS, 2 tests.

- [ ] **Step 5: Commit**

```bash
git add src/askslm/translation.py Tests/test_translator.py
git commit -m "feat(translation): Translator composes the catalog into the prompt

One network step, kept pure -- invalid SQL surfaces later when the preview runs
the counts, not here."
```

---

### Task 5: Wire the Translator into ask()

Replaces the hardcoded `schemas=""` in `src/askslm/__init__.py:ask`.

**Files:**
- Modify: `src/askslm/runtime.py`
- Modify: `src/askslm/__init__.py`
- Test: `Tests/test_walking_skeleton.py`

- [ ] **Step 1: Write the failing test**

Append to `Tests/test_walking_skeleton.py`:

```python
def test_ask_sends_the_real_schemas_to_the_backend(configured):
    """Regression: ask() used to hardcode schemas="" while the catalog sat unread in
    the mirror. A backend that never sees the vocabularies invents literals."""
    seen = {}

    class RecordingBackend:
        def translate(self, prompt):
            seen["schemas"] = prompt.schemas
            return IBD_TRANSLATION

    askslm.config(db=configured / "fixture.duckdb", database=_reopen(configured),
                  backend=RecordingBackend())

    askslm.ask("adults with IBD")

    assert "metalog_metadata" in seen["schemas"]
    assert "subject_disease_status" in seen["schemas"]


def _reopen(configured):
    return DuckDbConnection(configured / "fixture.duckdb")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest Tests/test_walking_skeleton.py::test_ask_sends_the_real_schemas_to_the_backend -v`
Expected: FAIL — `AssertionError` (schemas is `""`).

- [ ] **Step 3: Add the translator factory to the composition root**

In `src/askslm/runtime.py`, add the import:

```python
from askslm.catalog import SchemaCatalog
from askslm.translation import Translator
```

and the factory, after `backend()`:

```python
def translator() -> Translator:
    return Translator(backend(), SchemaCatalog(database()))
```

- [ ] **Step 4: Use it in ask()**

In `src/askslm/__init__.py`, replace the body of `ask()`:

```python
def ask(question: str) -> Plan:
    """One LLM hop plus cheap COUNTs. Persists nothing yet -- see the status note above."""
    research_question = ResearchQuestion(question)
    translation = runtime.translator().translate(research_question)
    if translation.failure is not None:
        return Plan(research_question, translation, CohortPreview(), error=translation.failure)
    return Plan(research_question, translation, _preview(translation))
```

Remove the now-unused `TranslationPrompt` from the import line if nothing else uses it, but keep it in `__all__` — it is part of the public surface.

- [ ] **Step 5: Run the full suite**

Run: `python3 -m pytest Tests/ -q`
Expected: PASS, 38 tests.

- [ ] **Step 6: Commit**

```bash
git add src/askslm/runtime.py src/askslm/__init__.py Tests/test_walking_skeleton.py
git commit -m "feat(ask): prompt with the real schemas instead of an empty string

ask() hardcoded schemas=\"\" while the catalog sat unread in the mirror, so any
real backend would have been inventing literals from column names alone."
```

---

### Task 6: GeminiBackend

**Files:**
- Modify: `src/askslm/adapters.py`
- Modify: `pyproject.toml`
- Test: `Tests/test_gemini_backend.py`

- [ ] **Step 1: Write the failing test**

Create `Tests/test_gemini_backend.py`:

```python
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
    silently missing half of the cohort."""
    payload = json.dumps({"interpretation": "x", "failure": None,
                          "queries": [{"source": "SRA_TAXONOMY", "sql": "SELECT 1"}]})

    with pytest.raises(KeyError):
        GeminiBackend(StubClient(payload), model="test-model").translate(_prompt())
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest Tests/test_gemini_backend.py -v`
Expected: FAIL — `ImportError: cannot import name 'GeminiBackend'`

- [ ] **Step 3: Write the implementation**

Append to `src/askslm/adapters.py`, and add `import json` plus `from askslm.prompt import SYSTEM_INSTRUCTION`, `from askslm.sources import Source`, `from askslm.translation import SourceQuery` to the imports:

```python
class GeminiBackend:
    """The real LlmBackend. Same port as CannedLlmBackend, so nothing below it changes.

    The client is injected rather than constructed here: that is what lets the tests
    exercise every branch of the parsing with no API key and no network.
    """

    def __init__(self, client, model: str):
        self._client = client
        self._model = model

    def translate(self, prompt: TranslationPrompt) -> Translation:
        response = self._client.models.generate_content(
            model=self._model,
            contents=_prompt_text(prompt),
            config={"system_instruction": SYSTEM_INSTRUCTION,
                    "response_mime_type": "application/json"})
        return _translation_of(json.loads(_unfenced(response.text)))


def open_gemini(api_key: str, model: str) -> GeminiBackend:
    """Constructed at the composition root; imported lazily so `import askslm` does not
    require google-genai for anyone using the canned backend."""
    from google import genai

    return GeminiBackend(genai.Client(api_key=api_key), model)


def _prompt_text(prompt: TranslationPrompt) -> str:
    return (f"SCHEMA\n{prompt.schemas}\n\n"
            f"QUESTION\n{prompt.question.text}\n")


def _unfenced(text: str) -> str:
    """Models fence their JSON even when told to return JSON only."""
    stripped = text.strip()
    if not stripped.startswith("```"):
        return stripped
    body = stripped.split("\n", 1)[1]
    return body.rsplit("```", 1)[0].strip()


def _translation_of(payload: dict) -> Translation:
    queries = tuple(SourceQuery(Source[entry["source"]], entry["sql"])
                    for entry in payload.get("queries", []))
    return Translation(interpretation=payload.get("interpretation", ""),
                       queries=queries,
                       failure=payload.get("failure"))
```

- [ ] **Step 4: Declare the dependency**

In `pyproject.toml`, under `[project]`, add:

```toml
dependencies = [
    "duckdb>=1.4",
    "pandas>=2.0",
    "biom-format>=2.1",
    "ete3>=3.1",
    "google-genai>=2.6",
]
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest Tests/test_gemini_backend.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add src/askslm/adapters.py pyproject.toml Tests/test_gemini_backend.py
git commit -m "feat(adapters): GeminiBackend behind the existing LlmBackend port

The client is injected, not constructed, so every parsing branch is tested with
no API key and no network. Handles the markdown fence models emit even when told
to return JSON only, and treats a refusal as a first-class Translation.failure
rather than an exception. A hallucinated source name raises loudly -- silently
dropping it would remove half the cohort with no signal."
```

---

### Task 7: Backend selection at config()

`Settings` already carries `llm` and `llm_key`. Make them mean something.

**Files:**
- Modify: `src/askslm/runtime.py`
- Modify: `src/askslm/__init__.py`
- Test: `Tests/test_translator.py` (append)

- [ ] **Step 1: Write the failing test**

Append to `Tests/test_translator.py`:

```python
def test_an_unknown_llm_name_fails_at_config_not_at_ask(tmp_path):
    """Fail fast: a typo in llm= must not survive until the first question."""
    import pytest

    import askslm
    from fixtures.mirror import build_fixture_mirror

    path = build_fixture_mirror(tmp_path / "fixture.duckdb")

    with pytest.raises(ValueError, match="unknown llm"):
        askslm.config(db=path, llm="gemni", llm_key="x")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest Tests/test_translator.py::test_an_unknown_llm_name_fails_at_config_not_at_ask -v`
Expected: FAIL — no exception raised.

- [ ] **Step 3: Write the implementation**

In `src/askslm/runtime.py`, add `llm_model` to `Settings` and validate the backend name:

```python
@dataclass(frozen=True)
class Settings:
    db_path: Path
    llm: str = "canned"
    llm_key: str = ""
    llm_model: str = "gemini-2.5-pro"

    def __post_init__(self):
        if not Path(self.db_path).exists():
            raise ValueError(f"database file not found: {self.db_path}")
        if self.llm not in ("canned", "gemini"):
            raise ValueError(f"unknown llm {self.llm!r}: expected 'canned' or 'gemini'")
```

Replace `backend()`:

```python
def backend() -> LlmBackend:
    """An explicitly injected backend always wins -- that is how the tests pass a fake.
    Otherwise the one named in Settings is constructed here, at the composition root."""
    global _backend
    if _backend is None:
        _backend = _named_backend(_require_settings())
    return _backend


def _named_backend(settings: Settings) -> LlmBackend:
    if settings.llm == "gemini":
        from askslm.adapters import open_gemini

        return open_gemini(settings.llm_key, settings.llm_model)
    raise RuntimeError(
        "no LlmBackend configured: pass backend=... or config(llm='gemini', llm_key=...)")
```

In `src/askslm/__init__.py`, thread the model through `config()`:

```python
def config(db: str | Path, llm: str = "canned", llm_key: str = "",
           llm_model: str = "gemini-2.5-pro", **wiring) -> None:
    """Configure once. Fails fast if the database is missing or the llm name is unknown."""
    runtime.configure(
        runtime.Settings(db_path=Path(db), llm=llm, llm_key=llm_key, llm_model=llm_model),
        **wiring)
```

- [ ] **Step 4: Run the full suite**

Run: `python3 -m pytest Tests/ -q`
Expected: PASS, 43 tests.

- [ ] **Step 5: Verify the real backend against the live API — ONE call**

This is the only step in the plan that needs a key and a network. It confirms the model name in `Settings` is real and that the response parses.

```bash
GEMINI_KEY=<the key> python3 - <<'PY'
import os, sys
sys.path.insert(0, "src")
from askslm.adapters import open_gemini
from askslm.prompt import SYSTEM_INSTRUCTION
from askslm.translation import ResearchQuestion, TranslationPrompt

backend = open_gemini(os.environ["GEMINI_KEY"], "gemini-2.5-pro")
prompt = TranslationPrompt(
    question=ResearchQuestion("stool samples from adults with IBD"),
    schemas="TABLE metalog_metadata   (source: METALOG_METADATA)\n"
            "  biosample  VARCHAR\n  sample_alias  VARCHAR\n"
            "  subject_disease_status  VARCHAR\n      values: [\"IBD\",\"healthy\",\"CRC\"]\n"
            "  age_years  DOUBLE")
translation = backend.translate(prompt)
print(translation.interpretation)
for query in translation.queries:
    print(query.source.name, "->", query.sql)
PY
```

Expected: one `METALOG_METADATA` query selecting `biosample`, filtering `subject_disease_status = 'IBD'`.
**If the model name 404s**, ask the human which Gemini model to use and change the `llm_model` default — do not guess a second name.

- [ ] **Step 6: Commit**

```bash
git add src/askslm/runtime.py src/askslm/__init__.py Tests/test_translator.py
git commit -m "feat(runtime): select the backend at config(), fail fast on a bad name

An injected backend still wins so tests keep passing fakes; otherwise the named
one is constructed at the composition root. A typo in llm= now raises at
config() instead of surviving until the first question."
```

---

### Task 8: The eval set format and its scorer

The riskiest thing in the product is the one thing the fixture tests cannot check. This is the measurement (HLD H.3).

**Files:**
- Create: `Scripts/eval/questions.jsonl`
- Create: `Scripts/eval/run_eval.py`
- Test: `Tests/test_eval_scoring.py`

- [ ] **Step 1: Write the failing test**

Create `Tests/test_eval_scoring.py`:

```python
"""Execution accuracy, not string match: two queries can differ in every character and
still select the same cohort -- and can also match textually while diverging on the
partition, which is the specific failure per-source translation invites (HLD E.2)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent / "Scripts" / "eval"))

from run_eval import Score, score_question


def test_identical_sets_score_one_everywhere():
    score = score_question(
        generated={"SRA_METADATA": {"S1", "S2"}, "METALOG_METADATA": {"S2", "S3"}},
        gold={"SRA_METADATA": {"S1", "S2"}, "METALOG_METADATA": {"S2", "S3"}})

    assert score == Score(per_source={"SRA_METADATA": 1.0, "METALOG_METADATA": 1.0},
                          shared=1.0)


def test_one_source_right_and_the_other_wrong_is_not_averaged_away():
    """Reporting a single number would hide exactly the bias we are hunting: a concept
    resolved strictly in one vocabulary and loosely in the other."""
    score = score_question(
        generated={"SRA_METADATA": {"S1"}, "METALOG_METADATA": set()},
        gold={"SRA_METADATA": {"S1"}, "METALOG_METADATA": {"S9"}})

    assert score.per_source["SRA_METADATA"] == 1.0
    assert score.per_source["METALOG_METADATA"] == 0.0


def test_the_shared_partition_is_scored_separately():
    """Both sources can be individually plausible while their OVERLAP is wrong."""
    score = score_question(
        generated={"SRA_METADATA": {"S1", "S2"}, "METALOG_METADATA": {"S3"}},
        gold={"SRA_METADATA": {"S1", "S2"}, "METALOG_METADATA": {"S2"}})

    assert score.per_source["SRA_METADATA"] == 1.0
    assert score.shared == 0.0        # generated overlap is empty, gold's is {S2}


def test_two_empty_sets_agree():
    """A question both queries correctly find nothing for is not a failure."""
    score = score_question(generated={"SRA_METADATA": set()}, gold={"SRA_METADATA": set()})

    assert score.per_source["SRA_METADATA"] == 1.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest Tests/test_eval_scoring.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'run_eval'`

- [ ] **Step 3: Write the scorer**

Create `Scripts/eval/run_eval.py`:

```python
"""Score the translator on real research questions with hand-written gold SQL.

Deliberately NOT a pytest: it needs the full mirror and a live API key, so CI cannot
run it. The fixture tests are what gate. This is a tracked measurement -- run it when
the prompt, the vocabularies, or the backend change, and diff the numbers. HLD H.3.

    python3 Scripts/eval/run_eval.py --db mirror.duckdb --key $GEMINI_KEY
"""
from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass, field
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

QUESTIONS = Path(__file__).parent / "questions.jsonl"


@dataclass(frozen=True)
class Score:
    per_source: dict[str, float] = field(default_factory=dict)
    shared: float = 0.0


def score_question(generated: dict[str, set], gold: dict[str, set]) -> Score:
    """Execution accuracy: exact set agreement, scored per source AND on the overlap.

    Three numbers rather than one because the per-source design invites a specific
    failure -- "adults with IBD" resolving strictly in SRA and loosely in Metalog
    biases the cohort silently, and an averaged score would hide it.
    """
    per_source = {source: _agreement(generated.get(source, set()), keys)
                  for source, keys in gold.items()}
    return Score(per_source=per_source,
                 shared=_agreement(_overlap(generated), _overlap(gold)))


def _agreement(left: set, right: set) -> float:
    return 1.0 if left == right else 0.0


def _overlap(by_source: dict[str, set]) -> set:
    """Samples more than one source returned. With fewer than two sources there is no
    overlap to speak of, and an empty set compares equal to an empty set."""
    sets = list(by_source.values())
    if len(sets) < 2:
        return set()
    return set.intersection(*sets)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True, help="the real mirror")
    parser.add_argument("--key", required=True, help="Gemini API key")
    parser.add_argument("--model", default="gemini-2.5-pro")
    args = parser.parse_args()

    import askslm
    from askslm.adapters import DuckDbConnection

    connection = DuckDbConnection(args.db)
    askslm.config(db=args.db, llm="gemini", llm_key=args.key, llm_model=args.model,
                  database=connection)

    totals = []
    for line in QUESTIONS.read_text().splitlines():
        if not line.strip() or line.lstrip().startswith("//"):
            continue
        case = json.loads(line)
        totals.append(_run_one(connection, case))
    _report(totals)
    connection.close()


def _run_one(connection, case: dict) -> Score:
    import askslm

    plan = askslm.ask(case["question"])
    generated = {query.source.name: _keys(connection, query.sql)
                 for query in plan.translation.queries}
    gold = {source: _keys(connection, sql) for source, sql in case["gold"].items()}
    score = score_question(generated, gold)
    print(f"\n{case['question']}")
    print(f"  interpretation: {plan.translation.interpretation}")
    for source, value in score.per_source.items():
        print(f"  {source}: {value:.0f}")
    print(f"  shared: {score.shared:.0f}")
    return score


def _keys(connection, sql: str) -> set:
    from askslm.cohort import accessions_of

    return set(accessions_of(connection.query(sql)))


def _report(scores: list[Score]) -> None:
    if not scores:
        print("no questions scored")
        return
    sources = sorted({source for score in scores for source in score.per_source})
    print("\n=== execution accuracy ===")
    for source in sources:
        values = [score.per_source[source] for score in scores if source in score.per_source]
        print(f"{source}: {sum(values) / len(values):.2f}  ({len(values)} questions)")
    shared = [score.shared for score in scores]
    print(f"shared partition: {sum(shared) / len(shared):.2f}")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Write the question file**

Create `Scripts/eval/questions.jsonl`. One JSON object per line; `//` lines are comments.

```
// The eval set. Gold SQL is authored BY THE DOMAIN OWNER -- only they know that
// "adults with IBD" means these cells of subject_disease_status and this age cutoff.
// Draft against the live schema, correct by hand; the corrected version is truth.
// Target 15-20 questions drawn from REAL research questions, not invented ones.
// At least one MUST be a non-metagenome question (askslm is a search tool, not a
// metagenomics-only tool) so the no-scoping decision is enforced by a test.
{"question": "stool samples from adults with IBD", "gold": {"METALOG_METADATA": "SELECT biosample, sample_alias FROM metalog_metadata WHERE subject_disease_status = 'IBD' AND age_years >= 18"}}
{"question": "healthy controls from Israel", "gold": {"METALOG_METADATA": "SELECT biosample, sample_alias FROM metalog_metadata WHERE subject_disease_status = 'healthy' AND geographic_location = 'Israel'"}}
{"question": "human tumour RNA-seq runs, for viral reads", "gold": {"SRA_METADATA": "SELECT biosample FROM sra_metadata WHERE organism = 'Homo sapiens' AND librarysource = 'TRANSCRIPTOMIC'"}}
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python3 -m pytest Tests/test_eval_scoring.py -v`
Expected: PASS, 4 tests.

- [ ] **Step 6: Commit**

```bash
git add Scripts/eval/ Tests/test_eval_scoring.py
git commit -m "feat(eval): execution-accuracy harness for the translator

The riskiest thing in the product is the one thing the fixture tests cannot
check. Scored three ways per question -- per metadata source AND on the shared
partition -- because an averaged number would hide the specific failure the
per-source design invites: a concept resolved strictly in one vocabulary and
loosely in the other biases the cohort silently.

Not a pytest: it needs the full mirror and a live key, so CI cannot run it. The
three shipped questions establish the format and prove the scorer; the real
15-20 with gold SQL are authored by the domain owner."
```

---

### Task 9: Update the status docs

`src/askslm/__init__.py` still says "the LLM is a canned backend". Leaving that stale is how the next reader is misled.

**Files:**
- Modify: `src/askslm/__init__.py`
- Modify: `CLAUDE.md`
- Modify: `README.md`

- [ ] **Step 1: Update the module docstring**

In `src/askslm/__init__.py`, replace the STATUS paragraph:

```python
STATUS: the question -> .biom path is real end to end, with a real LLM. Configure it
with config(db=..., llm="gemini", llm_key=...); llm="canned" plus an injected backend
is what the tests use. Still missing: the terminal app and plan persistence.
```

- [ ] **Step 2: Update CLAUDE.md**

In the Layout section, add the new modules under `src/askslm/`:

```
  catalog.py        schema_catalog -> prompt text (columns + REAL value vocabularies)
  prompt.py         the system instruction, isolated so eval can attribute prompt diffs
  translation.py    Translator: question + schemas -> Translation
Scripts/eval/       the translation eval set + execution-accuracy scorer (H.3)
```

- [ ] **Step 3: Update README.md**

Add a usage line showing the real backend:

```python
askslm.config(db="askslm_mirror.duckdb", llm="gemini", llm_key=os.environ["GEMINI_KEY"])
plan = askslm.ask("fecal metagenomes from adults with IBD, Western countries")
print(plan)
table, report = plan.run(profile_sources=askslm.Source.METALOG_MOTUS3, out="cohort.biom")
```

- [ ] **Step 4: Run the full suite one last time**

Run: `python3 -m pytest Tests/ -q`
Expected: PASS, 47 tests.

- [ ] **Step 5: Commit**

```bash
git add src/askslm/__init__.py CLAUDE.md README.md
git commit -m "docs: the LLM is no longer canned"
```

---

## Finishing

Use `superpowers:finishing-a-development-branch`. Push and open a PR against `main`:

```bash
git push -u origin feature/translation-half
gh pr create --base main --title "feat(translation): the real LLM half — catalog, Gemini, and an eval set"
```

Then **stop**. The human squash-merges through GitHub. Never delete the branch.

## Out of scope (deliberately)

- **Plan persistence** (`save=` / JSON round-trip) — independent, no dependency on this.
- **The terminal app** (questionary + rich) — wraps this; build it after the eval says translation works.
- **Flattening SRA `attributes`/`jattr`** — widens SRA's phenotype reach. Doing it later means revising SRA-side gold SQL, which is the known cost of this ordering.
- **The `tax_raw` sort** — gated on ≥400 GB free; see `Docs/superpowers/plans/2026-08-18-taxonomy-sort.html`.

## Self-review notes

- **Spec coverage:** F.1 `TranslationPrompt`/`Translator`/`SchemaCatalog` → Tasks 2, 4, 5. F.1 value vocabularies + cutoff tuning → Task 2 + Task 8. E.2 "LLM writes metadata queries only" → Task 2 (`_metadata_sources`) + Task 3 (instruction). E.2 `Translation.failure` → Task 6. H.3 eval set, execution accuracy, three-way scoring, non-metagenome question, not CI-gating → Task 8. H.1 "missing LLM key → ConfigError at config()" → Task 7.
- **Known gap, accepted:** the `SchemaCatalog` cardinality cutoff (currently 200) is *tunable* by rebuilding the catalog with a different `max_distinct`; this plan does not automate a sweep. Do that once the eval set has real questions, or the sweep optimises against three toy ones.
- **Type consistency:** `SchemaCatalog.all()`, `Translator.translate(ResearchQuestion) -> Translation`, `GeminiBackend.translate(TranslationPrompt) -> Translation`, `score_question(generated, gold) -> Score` are used identically in every task that references them.
