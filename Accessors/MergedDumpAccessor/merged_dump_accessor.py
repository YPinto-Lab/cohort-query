from __future__ import annotations

from pathlib import Path


class MergedDumpAccessor:
    """Parses NCBI merged.dmp into an old_taxid -> new_taxid map."""

    def load(self, path: Path) -> dict[int, int]:
        mapping: dict[int, int] = {}
        for line in Path(path).read_text(encoding="utf-8").splitlines():
            self._add_line(line, mapping)
        return mapping

    def _add_line(self, line: str, mapping: dict[int, int]) -> None:
        parts = line.strip().split("\t|\t")
        if len(parts) < 2:
            return
        self._add_pair(parts[0], parts[1], mapping)

    def _add_pair(self, old_raw: str, new_raw: str, mapping: dict[int, int]) -> None:
        old_clean = old_raw.strip()
        new_clean = new_raw.replace("\t|", "").strip()
        if not old_clean.isdigit() or not new_clean.isdigit():
            return
        mapping[int(old_clean)] = int(new_clean)
