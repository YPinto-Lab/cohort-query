# Attribute Key Retrieval Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** `"IBD fecal metagenomic with calprotectin"` produces a cohort instead of a refusal.

**Architecture:** Index every `jattr` key once at ETL; search that index with terms from the question at `ask()` time; inject only the matches into the prompt. Zero extra LLM hops — it is a local index lookup before the single existing hop.

**Design:** `Docs/superpowers/specs/2026-08-19-attribute-retrieval-design.html`. Read it — it records what was measured and why flattening was rejected.

---

## Prerequisites

```bash
git fetch origin && git switch -c feature/attribute-retrieval origin/main
```

Never delete branches. Finish with push + `gh pr create --base main`, then stop.

## Context

- **Run tests:** `python3 -m pytest Tests/ -q` from the repo root. Baseline **72 passing**.
- `sra_metadata.jattr` is a `VARCHAR` holding JSON, one row per sequencing run, 39,100,115 rows.
- **Verified, do not re-derive:** `json_extract_string(jattr, '$.key')` works (1.7s); casting `jattr` to `MAP(...)` returns **zero rows** and must not be used; `unnest(json_keys(jattr))` costs ~1s per 20k rows; extracting keys *and* values in one pass costs 36s per 20k rows and is therefore rejected for the full table.
- House style: no `lambda` — always a named `def`; readability first; trust input and fail fast (sanctioned validation points are `config()` and the LLM boundary); no backward-compat aliases; compose over duplicate.

## File Structure

| File | Responsibility |
|---|---|
| `Scripts/build_mirror/build_attribute_index.py` | **new.** Writes the `attribute_keys` table into an existing mirror. |
| `src/askslm/attributes.py` | **new.** `AttributeIndex(database).matching(question)` + prompt rendering. |
| `src/askslm/translation.py` | **modify.** `Translator` composes the attribute block into the prompt. |
| `src/askslm/prompt.py` | **modify.** Teach the model `json_extract_string` / `TRY_CAST`. |
| `src/askslm/runtime.py` | **modify.** `translator()` builds the index. |
| `Tests/fixtures/mirror.py` | **modify.** Fixture gains `attribute_keys`. |
| `Tests/test_attributes.py` | **new.** |

---

### Task 1: The ETL index

**Files:** Create `Scripts/build_mirror/build_attribute_index.py`; modify `Tests/fixtures/mirror.py`; test `Tests/test_attributes.py`.

Two passes, deliberately. Counts come from **all** rows because the number is a fact the researcher may act on. Sample values come from a **sample** because they only illustrate format, and doing them over all rows costs ~19 hours instead of ~32 minutes.

- [ ] **Step 1: Write the failing test** in `Tests/test_attributes.py`:

```python
"""Phenotype hides in jattr. 35,768 distinct keys in a 200k-row sample, and the
interesting ones are RARE -- calprotectin_sam is in 0.006% of runs. Indexing lets a
researcher name one and have it found."""
import duckdb
import pytest

from fixtures.mirror import build_fixture_mirror


@pytest.fixture(scope="module")
def con(tmp_path_factory):
    path = build_fixture_mirror(tmp_path_factory.mktemp("attrs") / "fixture.duckdb")
    connection = duckdb.connect(str(path), read_only=True)
    yield connection
    connection.close()


def test_every_jattr_key_is_indexed_with_its_occurrence_count(con):
    rows = con.execute(
        "SELECT key, occurrences FROM attribute_keys ORDER BY key").fetchall()

    assert ("host_age", 20) in rows          # the fixture's one jattr key, on every run


def test_the_index_carries_sample_values_so_the_model_sees_the_format(con):
    """`calprotectin_sam` holds "435.0" -- a NUMBER STORED AS A STRING. Without a sample
    the model cannot know it needs TRY_CAST."""
    samples = con.execute(
        "SELECT samples_json FROM attribute_keys WHERE key = 'host_age'").fetchone()[0]

    assert samples is not None and samples != "[]"
```

- [ ] **Step 2: Run it, confirm it fails** — `Table with name attribute_keys does not exist!`

- [ ] **Step 3: Implement** `Scripts/build_mirror/build_attribute_index.py`:

```python
"""Index every `jattr` key so a researcher can name a phenotype and have it found.

SRA hides its clinical fields in `jattr`, a JSON blob: 35,768 distinct keys in a
200,000-row sample. Flattening the frequent ones does not help -- they are technical
(`bytes`, `bases`, `primary_search`), while the interesting ones are rare by nature
(`calprotectin_sam` is in 2,342 of 39,100,115 runs). So we index them all and retrieve
per question instead. See the design doc for the measurements.

    python Scripts/build_mirror/build_attribute_index.py --db askslm_mirror.duckdb
"""
from __future__ import annotations

import argparse
from pathlib import Path

import duckdb

DEFAULT_SAMPLE_ROWS = 200_000
MAX_SAMPLES = 3


class AttributeIndexBuilder:
    """Two passes over sra_metadata.jattr: exact counts, sampled values.

    One pass would be simpler and is not affordable: extracting keys AND values together
    costs 36s per 20k rows (~19 hours for the table), against ~1s per 20k for keys alone
    (~32 min). Counts must be exact because a researcher acts on them; sample values only
    illustrate format, so a sample is honest.
    """

    def __init__(self, db_path: Path, sample_rows: int = DEFAULT_SAMPLE_ROWS):
        self.db_path = db_path
        self.sample_rows = sample_rows

    def build(self) -> None:
        con = duckdb.connect(str(self.db_path))
        con.execute("DROP TABLE IF EXISTS attribute_keys")
        con.execute("""
            CREATE TABLE attribute_keys (
                key TEXT,
                occurrences BIGINT,     -- exact, over every row
                samples_json TEXT       -- a few real values, from a sample
            )
        """)
        self._count_keys(con)
        self._attach_samples(con)
        self._report(con)
        con.close()

    def _count_keys(self, con: duckdb.DuckDBPyConnection) -> None:
        con.execute("""
            INSERT INTO attribute_keys
            SELECT k, count(*), NULL
            FROM (SELECT unnest(json_keys(jattr)) AS k FROM sra_metadata)
            GROUP BY k
        """)

    def _attach_samples(self, con: duckdb.DuckDBPyConnection) -> None:
        """Values are extracted per (row, key), which is why this runs over a sample."""
        con.execute(f"""
            CREATE OR REPLACE TEMP TABLE sampled AS
            SELECT k, list(DISTINCT v)[1:{MAX_SAMPLES}] AS vs
            FROM (
                SELECT k, json_extract_string(jattr, '$.' || k) AS v
                FROM (SELECT jattr, unnest(json_keys(jattr)) AS k
                      FROM sra_metadata USING SAMPLE {self.sample_rows} ROWS)
                WHERE json_extract_string(jattr, '$.' || k) IS NOT NULL
            )
            GROUP BY k
        """)
        con.execute("""
            UPDATE attribute_keys a
            SET samples_json = to_json(s.vs)
            FROM sampled s WHERE s.k = a.key
        """)

    def _report(self, con: duckdb.DuckDBPyConnection) -> None:
        total, sampled = con.execute(
            "SELECT count(*), count(samples_json) FROM attribute_keys").fetchone()
        print(f"attribute_keys: {total} keys · {sampled} with sample values")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, required=True)
    parser.add_argument("--sample-rows", type=int, default=DEFAULT_SAMPLE_ROWS)
    args = parser.parse_args()
    AttributeIndexBuilder(args.db, args.sample_rows).build()


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Build it in the fixture.** In `Tests/fixtures/mirror.py`, next to the existing `SchemaCatalogBuilder` call, add `AttributeIndexBuilder(path).build()` (import it the same way). **Verify the fixture's `jattr` actually produces a key** — it holds `'{"host_age":"25"}'`-shaped values. If the fixture's sampling clause fails on a 20-row table, adjust the fixture call's `sample_rows`, not the production default.

- [ ] **Step 5:** `python3 -m pytest Tests/ -q` — expect 74.

- [ ] **Step 6: Commit** — `feat(attributes): index every jattr key so rare phenotypes are findable`

---

### Task 2: Runtime retrieval

**Files:** Create `src/askslm/attributes.py`; test `Tests/test_attributes.py` (append).

- [ ] **Step 1: Write the failing test:**

```python
def test_a_named_phenotype_is_retrieved_from_the_index():
    """The whole point: "with calprotectin" must find calprotectin_sam."""
    index = AttributeIndex(_FakeDatabase([
        ("calprotectin_sam", 2342, '["435.0","12.8"]'),
    ]))

    found = index.matching("IBD fecal metagenomic with calprotectin")

    assert "calprotectin_sam" in found


def test_short_and_common_words_do_not_match_everything():
    """Without a floor, "with" and "a" match half the index and the prompt fills with
    noise -- the exact failure this feature exists to fix."""
    index = AttributeIndex(_FakeDatabase([("with_something", 10, None)]))

    assert index.matching("samples with a disease") == {}
```

(Write `_FakeDatabase` yourself — a tiny stand-in whose `query` returns a DataFrame built from those tuples. Match how other tests fake the `Database` port.)

- [ ] **Step 2: Run it, confirm it fails.**

- [ ] **Step 3: Implement** `src/askslm/attributes.py`:

```python
"""Retrieve the handful of jattr keys a question is actually about.

Schema linking is supposed to hand the model the RELEVANT schema, not all of it. There
are ~35,768 attribute keys; naming them all would cost more than the entire rest of the
prompt and bury the one that matters. So the question selects them.
"""
from __future__ import annotations

import json

from askslm.ports import Database

MIN_TERM = 4          # "with", "and", "the" match half the index and teach nothing
MAX_KEYS = 25         # a question about one phenotype should not import a hundred


class AttributeIndex:
    """Looks up `attribute_keys`, the ETL-built census of every jattr key."""

    def __init__(self, database: Database):
        self._database = database

    def matching(self, question: str) -> dict[str, tuple[int, str | None]]:
        """key -> (occurrences, samples_json), for keys a term of the question names."""
        terms = _terms(question)
        if not terms:
            return {}
        patterns = [f"%{term}%" for term in terms]
        rows = self._database.query(
            "SELECT key, occurrences, samples_json FROM attribute_keys "
            "WHERE list_bool_or(list_transform(?::VARCHAR[], "
            "                   x -> lower(key) LIKE x)) "
            "ORDER BY occurrences DESC LIMIT ?", [patterns, MAX_KEYS])
        return {row.key: (row.occurrences, row.samples_json)
                for row in rows.itertuples(index=False)}


def _terms(question: str) -> list[str]:
    words = "".join(character if character.isalnum() else " "
                    for character in question.lower()).split()
    return sorted({word for word in words if len(word) >= MIN_TERM})


def render(matches: dict[str, tuple[int, str | None]]) -> str:
    """The prompt block. Empty when nothing matched -- silence is correct, an empty
    heading would imply the model should have used something."""
    if not matches:
        return ""
    lines = ["SRA PER-SAMPLE ATTRIBUTES matching this question",
             "  These live in the sra_metadata.jattr JSON column, not as real columns.",
             "  Read one with json_extract_string(jattr, '$.<key>').",
             "  Values are STRINGS -- wrap numbers in TRY_CAST(... AS DOUBLE)."]
    for key, (occurrences, samples) in matches.items():
        shown = f"  e.g. {json.loads(samples)}" if samples else ""
        lines.append(f"  {key}   ({occurrences} runs){shown}")
    return "\n".join(lines)
```

**The `list_transform` lambda above is DuckDB SQL, not Python** — the no-`lambda` house rule is about Python. If DuckDB rejects that syntax, build an `OR`-joined `lower(key) LIKE ?` clause with one parameter per term instead; do not inline the terms as literals.

- [ ] **Step 4:** Tests pass; full suite expect 76.

- [ ] **Step 5: Commit** — `feat(attributes): retrieve the keys a question names`

---

### Task 3: Wire it into the prompt

**Files:** modify `src/askslm/translation.py`, `src/askslm/prompt.py`, `src/askslm/runtime.py`; test in `Tests/test_translator.py`.

- [ ] **Step 1: Failing test** — a `Translator` built with a stub index must put the matched key into `prompt.schemas`.

- [ ] **Step 2: Implement.** `Translator.__init__(self, backend, catalog, attributes)`; in `translate`, build the schemas string as the catalog block plus `attributes.render(attributes.matching(question.text))`, joined by a blank line when non-empty. `runtime.translator()` constructs `AttributeIndex(database())`.

- [ ] **Step 3: Prompt.** Add to `SYSTEM_INSTRUCTION`, in WRITING PREDICATES:

```
Some SRA fields are not columns. They live in the JSON column `jattr` and are
listed under "SRA PER-SAMPLE ATTRIBUTES" when the question names one. Read them
with json_extract_string(jattr, '$.<key>'). Their values are strings, so compare
numbers with TRY_CAST(json_extract_string(jattr, '$.<key>') AS DOUBLE).
If a question names a measurement and no such attribute is listed, it is genuinely
absent -- say so in `failure` rather than inventing a column.
```

- [ ] **Step 4:** Full suite, expect 77+.

- [ ] **Step 5: Commit** — `feat(translation): put matched attributes in the prompt`

---

### Task 4: Build it on the real mirror and prove the question works

**Not a code task — do this last, and report the real output.**

- [ ] **Step 1: Deploy.**
```bash
rsync -a --exclude __pycache__ src Scripts biu:/private/pinto-lab/tools/just-ask/pkg/
ssh biu '~/.conda/envs/askslm/bin/pip install -q -e /private/pinto-lab/tools/just-ask/pkg'
```

- [ ] **Step 2: Build the index** (expect ~30-40 min; needs a WRITE lock, so check `pgrep -u tamamya -a python3` first and do not kill another user's query):
```bash
ssh biu 'cd /private/pinto-lab/tools/just-ask && ~/.conda/envs/askslm/bin/python \
    /private/pinto-lab/tools/just-ask/pkg/Scripts/build_mirror/build_attribute_index.py \
    --db mirror/askslm_mirror.duckdb'
```

- [ ] **Step 3: Prove the retrieval finds it:**
```python
from askslm.adapters import DuckDbConnection
from askslm.attributes import AttributeIndex, render
c = DuckDbConnection("/private/pinto-lab/tools/just-ask/mirror/askslm_mirror.duckdb")
print(render(AttributeIndex(c).matching("IBD fecal metagenomic with calprotectin")))
```
Expect `calprotectin_sam (2342 runs) e.g. ['435.0', ...]`.

- [ ] **Step 4: Report the new prompt size.** It was ~39,842 tokens. Confirm the attribute block adds little.

---

## Finishing

Push, `gh pr create --base main`, stop.

## Out of scope

- Semantic/synonym matching ("gut inflammation marker" → calprotectin). Lexical first; measure whether it fails.
- Indexing the `attributes` STRUCT column — same information as `jattr`.
- Indexing Metalog — already flat, 205 real columns the catalog exposes.
