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
