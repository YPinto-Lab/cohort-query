"""Formatting utilities for metadata overview."""

from typing import List


def format_top_values_with_counts(values_with_counts: List[dict], sample_count: int) -> str:
    """Format value samples as `value (count)` with adaptive truncation.

    Show many/all values when cardinality is meaningfully lower than sample count,
    and truncate only for near one-value-per-record fields.
    """
    normalized = []
    for item in values_with_counts:
        value = str(item.get("value", ""))
        try:
            count = int(item.get("count", 0))
        except (TypeError, ValueError):
            count = 0
        normalized.append({"value": value, "count": count})

    normalized.sort(key=lambda x: -x["count"])
    unique_values_count = len(normalized)
    denominator = max(int(sample_count), 1)
    uniqueness_ratio = unique_values_count / denominator

    # Near one-value-per-record fields can explode in size; trim those.
    if uniqueness_ratio >= 0.8:
        limit = 30
    else:
        # For repeated cohorts (e.g., many tests per subject), show far more values.
        limit = 500

    visible = normalized[:limit]
    rendered = " | ".join(f"{item['value']} ({item['count']})" for item in visible)
    if unique_values_count > limit:
        rendered += f" | ... (+{unique_values_count - limit} more)"
    return rendered

