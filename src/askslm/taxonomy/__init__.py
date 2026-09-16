from __future__ import annotations

from collections.abc import Iterable

import pandas as pd
from ete3 import NCBITaxa


def lineage_table(tax_ids: Iterable[int]) -> pd.DataFrame:
    """One row per tax_id: name, rank, full lineage (taxids), and the ancestor NAME at each rank."""
    ids = [int(t) for t in tax_ids]
    ncbi = NCBITaxa()
    lineages = ncbi.get_lineage_translator(ids)
    ancestors = [anc for lineage in lineages.values() for anc in lineage]
    ranks = ncbi.get_rank(ancestors)
    names = ncbi.get_taxid_translator(set(ids) | set(ancestors))
    rows = {t: _feature_row(t, lineages.get(t, []), ranks, names) for t in ids}
    return pd.DataFrame.from_dict(rows, orient="index")


def _feature_row(tax_id: int, lineage: list[int], ranks: dict, names: dict) -> dict:
    return {
        "name": names.get(tax_id),
        "rank": ranks.get(tax_id),
        "lineage": tuple(lineage),
        "ranks": {ranks[anc]: names.get(anc, anc) for anc in lineage if anc in ranks},
    }
