"""Formatting only -- no prompting, no state. Kept separate from session.py so the
parts worth testing do not require driving a terminal."""
from __future__ import annotations

from askslm.plan import CohortPreview
from askslm.sources import Source

NARROW = 50            # a plain threshold, not a model judgement (HLD C.0.2)


def preview_line(preview: CohortPreview) -> str:
    """`412 biosamples · STAT 380 · METAPHLAN 228 · MOTUS 222`"""
    parts = [f"{preview.union} biosamples"]
    parts += [f"{source.name} {count}"
              for source, count in preview.by_profile_source.items()]
    return " · ".join(parts)


def narrow_warning(preview: CohortPreview) -> str | None:
    if preview.union >= NARROW:
        return None
    return f"{preview.union} samples -- narrow. Try widening the question."


def overlap_rows(preview: CohortPreview, winner: Source) -> list[tuple[str, str, str]]:
    """The trust screen (HLD C.1.3): who has which samples, and who wins the overlap."""
    counts = preview.by_metadata_source
    rows = [(source.name, str(count), "") for source, count in counts.items()]
    rows.append(("shared", str(preview.shared), f"<- {winner.name} wins these"))
    return rows
