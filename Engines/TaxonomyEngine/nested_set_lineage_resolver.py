from __future__ import annotations

import pandas as pd

STANDARD_RANKS = ("superkingdom", "phylum", "class", "order", "family", "genus", "species")


class NestedSetLineageResolver:
    """Maps each tax_id to its ancestor name at every standard rank."""

    def resolve(self, taxonomy_df: pd.DataFrame) -> pd.DataFrame:
        records: dict[int, dict[str, str]] = {}
        for _, group in taxonomy_df.groupby("acc"):
            self._resolve_group(group, records)
        return self._to_frame(records)

    def _resolve_group(self, group: pd.DataFrame, records: dict[int, dict[str, str]]) -> None:
        nodes = group.to_dict("records")
        for node in nodes:
            self._resolve_node(node, nodes, records)

    def _resolve_node(self, node: dict, nodes: list[dict], records: dict[int, dict[str, str]]) -> None:
        tax_id = int(node["tax_id"])
        if tax_id in records:
            return
        records[tax_id] = self._ancestor_ranks(node, nodes)

    def _ancestor_ranks(self, node: dict, nodes: list[dict]) -> dict[str, str]:
        ancestors = [c for c in nodes if c["ileft"] <= node["ileft"] and c["iright"] >= node["iright"]]
        return {a["rank"]: a["name"] for a in ancestors if a["rank"] in STANDARD_RANKS}

    def _to_frame(self, records: dict[int, dict[str, str]]) -> pd.DataFrame:
        rows = [{"tax_id": tax_id, **ranks} for tax_id, ranks in records.items()]
        return pd.DataFrame(rows, columns=["tax_id", *STANDARD_RANKS])
