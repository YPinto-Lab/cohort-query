from __future__ import annotations

from pathlib import Path
import tempfile
import unittest

import pandas as pd

from Accessors.TaxonomyAccessor import TaxonomyDumpAccessor
from Engines.DatasetAssemblyEngine import TaxonomyResolver


class TestDeprecatedTaxonomyResolution(unittest.TestCase):
    def test_load_merged_taxid_map_parses_ncbi_format(self) -> None:
        with tempfile.TemporaryDirectory() as tmp_dir:
            merged_path = Path(tmp_dir) / "merged.dmp"
            merged_path.write_text("100\t|\t200\t|\n101\t|\t201\t|\n", encoding="utf-8")

            mapping = TaxonomyDumpAccessor(merged_path).load_merged_taxid_map()

        self.assertEqual(mapping, {100: 200, 101: 201})

    def test_resolve_and_aggregate_merges_counts_by_sample_and_taxid(self) -> None:
        taxonomy_df = pd.DataFrame(
            {
                "acc": ["S1", "S1", "S1", "S2"],
                "tax_id": [100, 300, 999, 100],
                "rank": ["species", "species", "species", "species"],
                "name": ["old_a", "already_active", "old_b", "old_a"],
                "total_count": [10, 5, 7, 2],
            }
        )

        # 100 and 999 are historical IDs merged into 200.
        resolver = TaxonomyResolver({100: 200, 999: 200})
        resolved_df = resolver.resolve(taxonomy_df)

        s1_rows = resolved_df[resolved_df["acc"] == "S1"].set_index("tax_id")
        s2_rows = resolved_df[resolved_df["acc"] == "S2"].set_index("tax_id")

        self.assertEqual(float(s1_rows.loc["200", "total_count"]), 17.0)
        self.assertEqual(float(s1_rows.loc["300", "total_count"]), 5.0)
        self.assertEqual(float(s2_rows.loc["200", "total_count"]), 2.0)

    def test_resolve_and_aggregate_raises_for_missing_required_columns(self) -> None:
        resolver = TaxonomyResolver({})
        bad_df = pd.DataFrame({"acc": ["S1"], "tax_id": [1]})

        with self.assertRaises(ValueError) as ctx:
            resolver.resolve(bad_df)

        self.assertIn("total_count", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
