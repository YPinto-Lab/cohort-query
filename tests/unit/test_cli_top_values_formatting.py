"""Unit tests for metadata-overview top_values formatting behavior."""

from __future__ import annotations

import unittest

from cli import _format_top_values_with_counts


class TestCliTopValuesFormatting(unittest.TestCase):
    def test_includes_counts_in_rendered_values(self) -> None:
        rendered = _format_top_values_with_counts(
            [
                {"value": "A", "count": 4},
                {"value": "B", "count": 2},
            ],
            sample_count=10,
        )

        self.assertIn("A (4)", rendered)
        self.assertIn("B (2)", rendered)

    def test_high_uniqueness_truncates_with_more_marker(self) -> None:
        values = [{"value": f"v{i}", "count": 1} for i in range(120)]
        rendered = _format_top_values_with_counts(values, sample_count=120)

        self.assertIn("... (+", rendered)

    def test_repeated_value_distribution_shows_many_without_truncation(self) -> None:
        values = [{"value": f"subject_{i}", "count": 14} for i in range(60)]
        rendered = _format_top_values_with_counts(values, sample_count=840)

        self.assertNotIn("... (+", rendered)
        self.assertIn("subject_0 (14)", rendered)
        self.assertIn("subject_59 (14)", rendered)


if __name__ == "__main__":
    unittest.main()
