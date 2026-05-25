# Metadata Lean Core — Implementation Plan (Plan 2 of 3)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build the clean, tested metadata core — `extract` and `overview` — per `Docs/superpowers/specs/2026-05-25-askslm-lean-core-api-design.md` (§4.1, §4.2, §5.2).

**Architecture:** `from askslm import metadata` exposes two functions. `extract` reads SRA metadata and expands the `jattr` (JSON) and `attributes` (`k=.., v=..}`) blobs into real per-sample columns keyed by `acc` — so downstream sees fields, not blobs. `overview` takes that single columnar DataFrame and summarizes it (summary, per-project counts, discovered keys, coverage matrix). No MappingEngine, no network, no raw/enriched dual input. Engines are one-class-per-file; the public functions are a thin facade.

**Tech Stack:** Python 3.11+, pandas, pandera, pytest.

**Scope note:** Plan 2 of 3. Plan 1 (taxonomy core) is done. Plan 3 = deletions of superseded modules (MappingEngine, MetadataOverviewEngine, ENVO/ontology, DownstreamAnalysis, fat CLI), `askslm.py` vs `askslm/` reconciliation.

**Clean-code rules (binding):** one class per file; methods ≤10 lines doing one thing; ≤3 params (group into a frozen dataclass); no `else` (guard clauses); type hints; `pathlib.Path`; `logging` not `print`; banned words avoided (`data`, `info`, `manager`, `handler`, `util`, `helper`, `temp`, `obj`); tests in Arrange/Act/Assert with blank-line separation.

**Run tests** from the repo root with `python -m pytest` (puts repo root on `sys.path` so `from Common…`, `from Engines…`, `from askslm…` resolve). **Commits:** stage only the named files (never `git add -A`); no `Co-Authored-By` line.

---

## File Structure

**Create**
- `Common/contracts/metadata_results.py` — `MetadataOverview` DTO
- `Accessors/MetadataAccessor/__init__.py`, `metadata_file_accessor.py` — `MetadataFileAccessor`
- `Engines/MetadataEngine/source_key_parser.py` — `SourceKeyParser`
- `Engines/MetadataEngine/metadata_extractor.py` — `MetadataExtractor`
- `Engines/MetadataEngine/metadata_summary_builder.py` — `MetadataSummaryBuilder`
- `Engines/MetadataEngine/discovered_keys_builder.py` — `DiscoveredKeysBuilder`
- `Engines/MetadataEngine/metadata_coverage_builder.py` — `MetadataCoverageBuilder`
- `Engines/MetadataEngine/metadata_overview_builder.py` — `MetadataOverviewBuilder`
- `Engines/MetadataEngine/__init__.py` — facade (`extract`, `overview`)
- `Tests/unit/metadata/` test modules; `Tests/e2e/test_metadata_flow.py`

**Modify**
- `askslm/__init__.py` — add `metadata` namespace
- `askslm/contracts.py` — re-export `MetadataOverview`

**Reuse unchanged:** `Common/contracts/sra_schema.py` (`SRAMetadataSchema`). Do NOT create `__init__.py` in `Engines/MetadataEngine/` until Task 9 (namespace package until then), matching the taxonomy approach.

---

## Task 1: MetadataOverview DTO

**Files:** Create `Common/contracts/metadata_results.py`; Test `Tests/unit/metadata/test_metadata_results.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/metadata/test_metadata_results.py
import pandas as pd
from Common.contracts.metadata_results import MetadataOverview


def _overview():
    one = pd.DataFrame({"metric": ["samples"], "value": [3]})
    return MetadataOverview(summary_df=one, projects_df=one, discovered_keys_df=one,
                            discovered_keys_unique_df=one, coverage_matrix_df=one)


def test_overview_bundles_five_frames():
    overview = _overview()

    assert overview.summary_df.loc[0, "value"] == 3
    assert overview.coverage_matrix_df.loc[0, "metric"] == "samples"


def test_write_emits_five_csvs(tmp_path):
    paths = _overview().write(tmp_path)

    assert {p.name for p in paths} == {
        "summary.csv", "projects.csv", "discovered_keys.csv",
        "discovered_keys_unique.csv", "coverage_matrix.csv",
    }
    assert all(p.exists() for p in paths)
```

- [ ] **Step 2: Run, verify FAIL** — `python -m pytest Tests/unit/metadata/test_metadata_results.py -v` → `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# Common/contracts/metadata_results.py
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import pandas as pd


@dataclass(frozen=True)
class MetadataOverview:
    summary_df: pd.DataFrame
    projects_df: pd.DataFrame
    discovered_keys_df: pd.DataFrame
    discovered_keys_unique_df: pd.DataFrame
    coverage_matrix_df: pd.DataFrame

    def write(self, out_dir: Path) -> list[Path]:
        out_dir = Path(out_dir)
        out_dir.mkdir(parents=True, exist_ok=True)
        return [self._write(out_dir, name, frame) for name, frame in self._frames()]

    def _frames(self) -> list[tuple[str, pd.DataFrame]]:
        return [
            ("summary.csv", self.summary_df),
            ("projects.csv", self.projects_df),
            ("discovered_keys.csv", self.discovered_keys_df),
            ("discovered_keys_unique.csv", self.discovered_keys_unique_df),
            ("coverage_matrix.csv", self.coverage_matrix_df),
        ]

    def _write(self, out_dir: Path, name: str, frame: pd.DataFrame) -> Path:
        path = out_dir / name
        frame.to_csv(path, index=False)
        return path
```

- [ ] **Step 4: Run, verify PASS** (2 passed)
- [ ] **Step 5: Commit** — `git add Common/contracts/metadata_results.py Tests/unit/metadata/test_metadata_results.py` → `feat(contracts): add MetadataOverview result DTO`

---

## Task 2: MetadataFileAccessor

**Files:** Create `Accessors/MetadataAccessor/__init__.py` (empty), `Accessors/MetadataAccessor/metadata_file_accessor.py`; Test `Tests/unit/metadata/test_metadata_file_accessor.py`

- [ ] **Step 1: Write the failing test** (builds a schema-complete CSV in a tmp dir so validation passes)

```python
# Tests/unit/metadata/test_metadata_file_accessor.py
import pandas as pd
from Common.contracts.sra_schema import SRAMetadataSchema
from Accessors.MetadataAccessor.metadata_file_accessor import MetadataFileAccessor


def _write_csv(tmp_path):
    columns = list(SRAMetadataSchema.__fields__.keys())
    frame = pd.DataFrame({c: ["", ""] for c in columns})
    frame["acc"] = ["SRR1", "SRR2"]
    frame["bioproject"] = ["PRJ1", "PRJ1"]
    path = tmp_path / "metadata.csv"
    frame.to_csv(path, index=False)
    return path


def test_read_returns_validated_frame(tmp_path):
    accessor = MetadataFileAccessor()

    frame = accessor.read(_write_csv(tmp_path))

    assert list(frame["acc"]) == ["SRR1", "SRR2"]
    assert "bioproject" in frame.columns
```

- [ ] **Step 2: Run, verify FAIL** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# Accessors/MetadataAccessor/__init__.py
```

```python
# Accessors/MetadataAccessor/metadata_file_accessor.py
from __future__ import annotations

from pathlib import Path

import pandas as pd

from Common.contracts.sra_schema import SRAMetadataSchema


class MetadataFileAccessor:
    """Reads metadata.csv and validates it against SRAMetadataSchema."""

    def read(self, path: Path) -> pd.DataFrame:
        frame = pd.read_csv(Path(path))
        return SRAMetadataSchema.validate(frame)
```

- [ ] **Step 4: Run, verify PASS**
- [ ] **Step 5: Commit** — `git add Accessors/MetadataAccessor/ Tests/unit/metadata/test_metadata_file_accessor.py` → `feat(metadata): add metadata.csv file accessor`

---

## Task 3: SourceKeyParser

Parses one row's `jattr` (JSON dict; list values joined with spaces) and `attributes` (`k=KEY, v=VALUE}` pairs) into a flat `{key: value}` dict. `jattr` wins on key collisions.

**Files:** Create `Engines/MetadataEngine/source_key_parser.py`; Test `Tests/unit/metadata/test_source_key_parser.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/metadata/test_source_key_parser.py
import pandas as pd
from Engines.MetadataEngine.source_key_parser import SourceKeyParser


def test_parses_jattr_and_attributes():
    row = pd.Series({"jattr": '{"host": "human", "tags": ["a", "b"]}', "attributes": "k=sex, v=male}"})

    parsed = SourceKeyParser().parse(row)

    assert parsed["host"] == "human"
    assert parsed["tags"] == "a b"
    assert parsed["sex"] == "male"


def test_jattr_wins_on_key_collision():
    row = pd.Series({"jattr": '{"sex": "female"}', "attributes": "k=sex, v=male}"})

    parsed = SourceKeyParser().parse(row)

    assert parsed["sex"] == "female"


def test_missing_or_invalid_blobs_yield_empty():
    row = pd.Series({"jattr": float("nan"), "attributes": None})

    parsed = SourceKeyParser().parse(row)

    assert parsed == {}
```

- [ ] **Step 2: Run, verify FAIL** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# Engines/MetadataEngine/source_key_parser.py
from __future__ import annotations

import json
import re

import pandas as pd

_ATTR_PATTERN = re.compile(r"k\s*=\s*([^,}]+),\s*v\s*=\s*([^}]+)")


class SourceKeyParser:
    """Parses one metadata row's jattr/attributes blobs into a flat {key: value} dict."""

    def parse(self, row: pd.Series) -> dict[str, str]:
        merged = self._attributes(row.get("attributes"))
        merged.update(self._jattr(row.get("jattr")))
        return merged

    def _jattr(self, blob: object) -> dict[str, str]:
        if not isinstance(blob, str):
            return {}
        return {str(k): self._flatten(v) for k, v in self._load(blob).items() if v is not None}

    def _load(self, blob: str) -> dict:
        try:
            parsed = json.loads(blob)
        except (json.JSONDecodeError, TypeError):
            return {}
        return parsed if isinstance(parsed, dict) else {}

    def _flatten(self, value: object) -> str:
        if isinstance(value, list):
            return " ".join(str(item) for item in value)
        return str(value)

    def _attributes(self, blob: object) -> dict[str, str]:
        if not isinstance(blob, str):
            return {}
        return {key.strip(): value.strip() for key, value in _ATTR_PATTERN.findall(blob)}
```

- [ ] **Step 4: Run, verify PASS** (3 passed)
- [ ] **Step 5: Commit** — `git add Engines/MetadataEngine/source_key_parser.py Tests/unit/metadata/test_source_key_parser.py` → `feat(metadata): add jattr/attributes source-key parser`

---

## Task 4: MetadataExtractor

Expands the parsed blobs into per-sample columns. Output: one row per `acc`, base columns (minus `jattr`/`attributes`) plus one column per discovered key (`acc` is a column).

**Files:** Create `Engines/MetadataEngine/metadata_extractor.py`; Test `Tests/unit/metadata/test_metadata_extractor.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/metadata/test_metadata_extractor.py
import pandas as pd
from Engines.MetadataEngine.metadata_extractor import MetadataExtractor


def _raw():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2"],
        "bioproject": ["PRJ1", "PRJ1"],
        "jattr": ['{"host": "human", "tissue": "gut"}', '{"host": "human"}'],
        "attributes": ["k=sex, v=male}", "k=sex, v=female}"],
    })


def test_extract_expands_blobs_into_columns():
    out = MetadataExtractor().extract(_raw())

    assert {"host", "tissue", "sex"}.issubset(out.columns)
    assert "jattr" not in out.columns
    assert "attributes" not in out.columns
    srr1 = out[out["acc"] == "SRR1"].iloc[0]
    assert (srr1["host"], srr1["tissue"], srr1["sex"]) == ("human", "gut", "male")


def test_extract_fills_absent_keys_with_empty_string():
    out = MetadataExtractor().extract(_raw())

    srr2 = out[out["acc"] == "SRR2"].iloc[0]
    assert srr2["tissue"] == ""


def test_extract_without_blobs_returns_base_columns():
    raw = pd.DataFrame({"acc": ["SRR1"], "bioproject": ["PRJ1"]})

    out = MetadataExtractor().extract(raw)

    assert list(out.columns) == ["acc", "bioproject"]
```

- [ ] **Step 2: Run, verify FAIL** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# Engines/MetadataEngine/metadata_extractor.py
from __future__ import annotations

import pandas as pd

from .source_key_parser import SourceKeyParser

_BLOB_COLUMNS = ["jattr", "attributes"]


class MetadataExtractor:
    """Expands jattr/attributes blobs into real per-sample columns keyed by acc."""

    def __init__(self) -> None:
        self._parser = SourceKeyParser()

    def extract(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        base = self._base(raw_df)
        parsed = self._parsed(raw_df)
        for key in self._discovered(parsed, base):
            base[key] = self._column(key, parsed, base.index)
        return base.reset_index()

    def _base(self, raw_df: pd.DataFrame) -> pd.DataFrame:
        present_blobs = [c for c in _BLOB_COLUMNS if c in raw_df.columns]
        dropped = raw_df.drop(columns=present_blobs)
        return dropped.drop_duplicates(subset=["acc"]).set_index("acc")

    def _parsed(self, raw_df: pd.DataFrame) -> pd.Series:
        unique = raw_df.drop_duplicates(subset=["acc"]).set_index("acc")
        return unique.apply(self._parser.parse, axis=1)

    def _discovered(self, parsed: pd.Series, base: pd.DataFrame) -> list[str]:
        keys = {key for entry in parsed for key in entry}
        return sorted(k for k in keys if k not in base.columns and k != "acc")

    def _column(self, key: str, parsed: pd.Series, index: pd.Index) -> pd.Series:
        values = parsed.apply(lambda entry: entry.get(key, ""))
        return values.reindex(index).fillna("")
```

- [ ] **Step 4: Run, verify PASS** (3 passed)
- [ ] **Step 5: Commit** — `git add Engines/MetadataEngine/metadata_extractor.py Tests/unit/metadata/test_metadata_extractor.py` → `feat(metadata): add MetadataExtractor for blob expansion`

---

## Task 5: MetadataSummaryBuilder

**Files:** Create `Engines/MetadataEngine/metadata_summary_builder.py`; Test `Tests/unit/metadata/test_metadata_summary_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/metadata/test_metadata_summary_builder.py
import pandas as pd
from Engines.MetadataEngine.metadata_summary_builder import MetadataSummaryBuilder


def _extracted():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "host": ["human", "human", "mouse"],
    })


def test_summary_reports_core_metrics():
    summary = MetadataSummaryBuilder().build(_extracted(), ["host"])

    lookup = dict(zip(summary["metric"], summary["value"]))
    assert lookup["samples"] == 3
    assert lookup["projects"] == 2
    assert lookup["discovered_keys"] == 1
    assert lookup["discovered_key_names"] == "host"
```

- [ ] **Step 2: Run, verify FAIL** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# Engines/MetadataEngine/metadata_summary_builder.py
from __future__ import annotations

import pandas as pd


class MetadataSummaryBuilder:
    """Builds the high-level metadata summary table."""

    def build(self, metadata_df: pd.DataFrame, discovered_keys: list[str]) -> pd.DataFrame:
        metrics = {
            "samples": len(metadata_df),
            "projects": self._projects(metadata_df),
            "columns": len(metadata_df.columns),
            "discovered_keys": len(discovered_keys),
            "discovered_key_names": ", ".join(discovered_keys),
        }
        return pd.DataFrame({"metric": list(metrics), "value": list(metrics.values())})

    def _projects(self, metadata_df: pd.DataFrame) -> int:
        if "bioproject" not in metadata_df.columns:
            return 0
        return int(metadata_df["bioproject"].nunique())
```

- [ ] **Step 4: Run, verify PASS**
- [ ] **Step 5: Commit** — `git add Engines/MetadataEngine/metadata_summary_builder.py Tests/unit/metadata/test_metadata_summary_builder.py` → `feat(metadata): add MetadataSummaryBuilder`

---

## Task 6: DiscoveredKeysBuilder

Per-project key distributions plus a deduplicated cross-project rollup. A value is "populated" when it is non-empty and not the literal `"nan"`.

**Files:** Create `Engines/MetadataEngine/discovered_keys_builder.py`; Test `Tests/unit/metadata/test_discovered_keys_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/metadata/test_discovered_keys_builder.py
import pandas as pd
from Engines.MetadataEngine.discovered_keys_builder import DiscoveredKeysBuilder


def _extracted():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "host": ["human", "human", "mouse"],
        "tissue": ["gut", "skin", ""],
    })


def test_by_project_reports_population_and_uniqueness():
    by_project = DiscoveredKeysBuilder().by_project(_extracted(), ["host", "tissue"])

    prj1_host = by_project[(by_project["bioproject"] == "PRJ1") & (by_project["key_name"] == "host")].iloc[0]
    assert prj1_host["populated_samples"] == 2
    assert prj1_host["unique_values"] == 1
    prj2_tissue = by_project[(by_project["bioproject"] == "PRJ2") & (by_project["key_name"] == "tissue")].iloc[0]
    assert prj2_tissue["populated_samples"] == 0


def test_unique_rolls_up_across_projects():
    builder = DiscoveredKeysBuilder()
    by_project = builder.by_project(_extracted(), ["host", "tissue"])

    unique = builder.unique(by_project)

    host = unique[unique["key_name"] == "host"].iloc[0]
    assert host["projects"] == 2
    assert host["populated_samples"] == 3
    assert host["unique_values"] == 1
```

- [ ] **Step 2: Run, verify FAIL** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# Engines/MetadataEngine/discovered_keys_builder.py
from __future__ import annotations

import pandas as pd

_TOP_N = 5
_COLUMNS = ["bioproject", "key_name", "populated_samples", "unique_values", "top_values"]


class DiscoveredKeysBuilder:
    """Summarizes discovered metadata keys, per project and deduplicated."""

    def by_project(self, metadata_df: pd.DataFrame, discovered_keys: list[str]) -> pd.DataFrame:
        rows = [self._row(project, key, frame)
                for project, frame in self._projects(metadata_df)
                for key in discovered_keys]
        return pd.DataFrame(rows, columns=_COLUMNS)

    def unique(self, by_project_df: pd.DataFrame) -> pd.DataFrame:
        if by_project_df.empty:
            return pd.DataFrame(columns=["key_name", "projects", "populated_samples", "unique_values"])
        grouped = by_project_df.groupby("key_name", as_index=False).agg(
            projects=("bioproject", "nunique"),
            populated_samples=("populated_samples", "sum"),
            unique_values=("unique_values", "max"),
        )
        return grouped.sort_values("key_name").reset_index(drop=True)

    def _projects(self, metadata_df: pd.DataFrame) -> list:
        if "bioproject" not in metadata_df.columns:
            return [("", metadata_df)]
        return list(metadata_df.groupby("bioproject"))

    def _row(self, project: str, key: str, frame: pd.DataFrame) -> dict:
        populated = self._populated(frame[key])
        return {"bioproject": project, "key_name": key,
                "populated_samples": int(len(populated)),
                "unique_values": int(populated.nunique()),
                "top_values": self._top(populated)}

    def _populated(self, series: pd.Series) -> pd.Series:
        text = series.astype(str).str.strip()
        return text[(text != "") & (text.str.lower() != "nan")]

    def _top(self, populated: pd.Series) -> str:
        counts = populated.value_counts().head(_TOP_N)
        return " | ".join(f"{value} ({count})" for value, count in counts.items())
```

- [ ] **Step 4: Run, verify PASS** (2 passed)
- [ ] **Step 5: Commit** — `git add Engines/MetadataEngine/discovered_keys_builder.py Tests/unit/metadata/test_discovered_keys_builder.py` → `feat(metadata): add DiscoveredKeysBuilder`

---

## Task 7: MetadataCoverageBuilder

A `bioproject × discovered-key` matrix of the fraction of samples populated (0.0–1.0), `bioproject` as a column.

**Files:** Create `Engines/MetadataEngine/metadata_coverage_builder.py`; Test `Tests/unit/metadata/test_metadata_coverage_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/metadata/test_metadata_coverage_builder.py
import pandas as pd
from Engines.MetadataEngine.metadata_coverage_builder import MetadataCoverageBuilder


def _extracted():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "host": ["human", "human", "mouse"],
        "tissue": ["gut", "skin", ""],
    })


def test_coverage_fractions_per_project():
    coverage = MetadataCoverageBuilder().build(_extracted(), ["host", "tissue"])

    prj2 = coverage[coverage["bioproject"] == "PRJ2"].iloc[0]
    assert prj2["host"] == 1.0
    assert prj2["tissue"] == 0.0
    prj1 = coverage[coverage["bioproject"] == "PRJ1"].iloc[0]
    assert prj1["tissue"] == 1.0
```

- [ ] **Step 2: Run, verify FAIL** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# Engines/MetadataEngine/metadata_coverage_builder.py
from __future__ import annotations

import pandas as pd


class MetadataCoverageBuilder:
    """Builds a bioproject x key matrix of the fraction of samples populated."""

    def build(self, metadata_df: pd.DataFrame, discovered_keys: list[str]) -> pd.DataFrame:
        if not discovered_keys or "bioproject" not in metadata_df.columns:
            return pd.DataFrame(columns=["bioproject", *discovered_keys])
        grouped = metadata_df.groupby("bioproject")[discovered_keys]
        coverage = grouped.apply(lambda frame: self._fractions(frame, discovered_keys))
        return coverage.reset_index()

    def _fractions(self, frame: pd.DataFrame, keys: list[str]) -> pd.Series:
        return pd.Series({key: self._fraction(frame[key]) for key in keys})

    def _fraction(self, series: pd.Series) -> float:
        text = series.astype(str).str.strip()
        populated = (text != "") & (text.str.lower() != "nan")
        return round(float(populated.mean()), 3)
```

- [ ] **Step 4: Run, verify PASS**
- [ ] **Step 5: Commit** — `git add Engines/MetadataEngine/metadata_coverage_builder.py Tests/unit/metadata/test_metadata_coverage_builder.py` → `feat(metadata): add MetadataCoverageBuilder`

---

## Task 8: MetadataOverviewBuilder

Orchestrates the sub-builders. Discovered keys = columns not in `SRAMetadataSchema` and not `acc`.

**Files:** Create `Engines/MetadataEngine/metadata_overview_builder.py`; Test `Tests/unit/metadata/test_metadata_overview_builder.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/metadata/test_metadata_overview_builder.py
import pandas as pd
from Engines.MetadataEngine.metadata_overview_builder import MetadataOverviewBuilder


def _extracted():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "host": ["human", "human", "mouse"],
        "tissue": ["gut", "skin", ""],
    })


def test_overview_assembles_all_frames():
    overview = MetadataOverviewBuilder().build(_extracted())

    summary = dict(zip(overview.summary_df["metric"], overview.summary_df["value"]))
    assert summary["discovered_keys"] == 2
    projects = dict(zip(overview.projects_df["bioproject"], overview.projects_df["samples"]))
    assert projects == {"PRJ1": 2, "PRJ2": 1}
    assert set(overview.discovered_keys_unique_df["key_name"]) == {"host", "tissue"}


def test_overview_excludes_base_columns_from_discovered():
    overview = MetadataOverviewBuilder().build(_extracted())

    # bioproject and acc are base SRA columns, not discovered keys
    assert "bioproject" not in set(overview.discovered_keys_unique_df["key_name"])
```

- [ ] **Step 2: Run, verify FAIL** — `ModuleNotFoundError`

- [ ] **Step 3: Implement**

```python
# Engines/MetadataEngine/metadata_overview_builder.py
from __future__ import annotations

import pandas as pd

from Common.contracts.metadata_results import MetadataOverview
from Common.contracts.sra_schema import SRAMetadataSchema
from .discovered_keys_builder import DiscoveredKeysBuilder
from .metadata_coverage_builder import MetadataCoverageBuilder
from .metadata_summary_builder import MetadataSummaryBuilder

_BASE_COLUMNS = set(SRAMetadataSchema.__fields__.keys())


class MetadataOverviewBuilder:
    """Summarizes an extracted metadata table into a MetadataOverview."""

    def __init__(self) -> None:
        self._summary = MetadataSummaryBuilder()
        self._keys = DiscoveredKeysBuilder()
        self._coverage = MetadataCoverageBuilder()

    def build(self, metadata_df: pd.DataFrame) -> MetadataOverview:
        discovered = self._discovered(metadata_df)
        by_project = self._keys.by_project(metadata_df, discovered)
        return MetadataOverview(
            summary_df=self._summary.build(metadata_df, discovered),
            projects_df=self._projects(metadata_df),
            discovered_keys_df=by_project,
            discovered_keys_unique_df=self._keys.unique(by_project),
            coverage_matrix_df=self._coverage.build(metadata_df, discovered),
        )

    def _discovered(self, metadata_df: pd.DataFrame) -> list[str]:
        return sorted(c for c in metadata_df.columns if c not in _BASE_COLUMNS and c != "acc")

    def _projects(self, metadata_df: pd.DataFrame) -> pd.DataFrame:
        if "bioproject" not in metadata_df.columns:
            return pd.DataFrame(columns=["bioproject", "samples"])
        return metadata_df.groupby("bioproject", as_index=False).agg(samples=("acc", "count"))
```

- [ ] **Step 4: Run, verify PASS** (2 passed)
- [ ] **Step 5: Commit** — `git add Engines/MetadataEngine/metadata_overview_builder.py Tests/unit/metadata/test_metadata_overview_builder.py` → `feat(metadata): add MetadataOverviewBuilder`

---

## Task 9: MetadataEngine facade

**Files:** Create `Engines/MetadataEngine/__init__.py`; Test `Tests/unit/metadata/test_metadata_facade.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/metadata/test_metadata_facade.py
import pandas as pd
import Engines.MetadataEngine as metadata


def _raw():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2"],
        "bioproject": ["PRJ1", "PRJ1"],
        "jattr": ['{"host": "human"}', '{"host": "mouse"}'],
        "attributes": ["k=sex, v=male}", "k=sex, v=female}"],
    })


def test_extract_then_overview():
    extracted = metadata.extract(_raw())
    overview = metadata.overview(extracted)

    assert "host" in extracted.columns
    assert set(overview.discovered_keys_unique_df["key_name"]) == {"host", "sex"}
```

- [ ] **Step 2: Run, verify FAIL** — missing attribute / module

- [ ] **Step 3: Implement**

```python
# Engines/MetadataEngine/__init__.py
from __future__ import annotations

from pathlib import Path

import pandas as pd

from Accessors.MetadataAccessor.metadata_file_accessor import MetadataFileAccessor
from Common.contracts.metadata_results import MetadataOverview
from .metadata_extractor import MetadataExtractor
from .metadata_overview_builder import MetadataOverviewBuilder


def extract(source: str | Path | pd.DataFrame) -> pd.DataFrame:
    raw_df = source if isinstance(source, pd.DataFrame) else MetadataFileAccessor().read(Path(source))
    return MetadataExtractor().extract(raw_df)


def overview(metadata_df: pd.DataFrame) -> MetadataOverview:
    return MetadataOverviewBuilder().build(metadata_df)
```

- [ ] **Step 4: Run, verify PASS**; also run full metadata suite `python -m pytest Tests/unit/metadata -q`
- [ ] **Step 5: Commit** — `git add Engines/MetadataEngine/__init__.py Tests/unit/metadata/test_metadata_facade.py` → `feat(metadata): wire MetadataEngine facade functions`

---

## Task 10: Public `askslm.metadata` namespace

**Files:** Modify `askslm/__init__.py`, `askslm/contracts.py`; Test `Tests/unit/metadata/test_metadata_public_namespace.py`

- [ ] **Step 1: Write the failing test**

```python
# Tests/unit/metadata/test_metadata_public_namespace.py
from askslm import metadata
from askslm.contracts import MetadataOverview


def test_metadata_exposes_callables():
    assert callable(metadata.extract)
    assert callable(metadata.overview)


def test_contracts_reexports_metadata_overview():
    assert MetadataOverview.__name__ == "MetadataOverview"
```

- [ ] **Step 2: Run, verify FAIL** — `ImportError` (no `metadata` in askslm)

- [ ] **Step 3: Implement** — set `askslm/__init__.py` to EXACTLY:

```python
# askslm/__init__.py
from Engines import MetadataEngine as metadata
from Engines import TaxonomyEngine as taxonomy

__all__ = ["metadata", "taxonomy"]
```

Append `MetadataOverview` to `askslm/contracts.py` (keep existing taxonomy re-exports). Add `from Common.contracts.metadata_results import MetadataOverview` and add `"MetadataOverview"` to `__all__`.

- [ ] **Step 4: Run, verify PASS**; run the whole suite `python -m pytest Tests -q` (no regressions)
- [ ] **Step 5: Commit** — `git add askslm/__init__.py askslm/contracts.py Tests/unit/metadata/test_metadata_public_namespace.py` → `feat(askslm): expose public metadata namespace`

---

## Task 11: End-to-end metadata flow

**Files:** Test `Tests/e2e/test_metadata_flow.py`

- [ ] **Step 1: Write the end-to-end test**

```python
# Tests/e2e/test_metadata_flow.py
import pandas as pd
from askslm import metadata


def _raw():
    return pd.DataFrame({
        "acc": ["SRR1", "SRR2", "SRR3"],
        "bioproject": ["PRJ1", "PRJ1", "PRJ2"],
        "jattr": ['{"host": "human", "tissue": "gut"}', '{"host": "human", "tissue": "skin"}', '{"host": "mouse"}'],
        "attributes": ["k=sex, v=male}", "k=sex, v=female}", "k=sex, v=male}"],
    })


def test_extract_overview_and_write(tmp_path):
    extracted = metadata.extract(_raw())
    overview = metadata.overview(extracted)

    assert {"host", "tissue", "sex"}.issubset(extracted.columns)
    coverage = overview.coverage_matrix_df.set_index("bioproject")
    assert coverage.loc["PRJ2", "tissue"] == 0.0
    assert coverage.loc["PRJ1", "tissue"] == 1.0
    paths = overview.write(tmp_path)
    assert all(p.exists() for p in paths)
```

- [ ] **Step 2: Run, verify PASS**; then full suite `python -m pytest Tests -q`
- [ ] **Step 3: Commit** — `git add Tests/e2e/test_metadata_flow.py` → `test(metadata): end-to-end extract/overview/write flow`

---

## Self-Review (completed by plan author)

**Spec coverage:** `metadata.extract` (Tasks 2,3,4,9) parses jattr/attributes into columns, single-df output keyed by acc; `metadata.overview` (Tasks 5,6,7,8,9) single-df input → summary, projects, discovered keys (by-project + unique), coverage matrix; `MetadataOverview` DTO + `write` (Task 1); public namespace + contracts re-export (Task 10); e2e (Task 11). No MappingEngine, no network, no raw/enriched duality — matches spec §4.1/§4.2/§5.2.

**Placeholder scan:** none — every step has complete code.

**Type/name consistency:** `MetadataOverview(summary_df, projects_df, discovered_keys_df, discovered_keys_unique_df, coverage_matrix_df)` used identically across Tasks 1/8/9/11; `SourceKeyParser.parse`, `MetadataExtractor.extract`, builder method names (`by_project`, `unique`, `build`) consistent; discovered-key column schema `["bioproject","key_name","populated_samples","unique_values","top_values"]` consistent between Task 6 producer and its consumers.

**Note (pandas):** `MetadataCoverageBuilder` uses `groupby(...)[keys].apply(...)`; selecting key columns before `apply` avoids the pandas 2.2 grouping-column warning.
