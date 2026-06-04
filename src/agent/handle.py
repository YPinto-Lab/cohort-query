from __future__ import annotations
from typing import Annotated, TypeVar, get_args, get_origin

T = TypeVar("T")

class _HandleMarker:
    """Marker so unwrap_handle_arg can recognize Handle[T] forms."""


class _HandleFactory:
    def __getitem__(self, item):
        return Annotated[str, _HandleMarker, item]


Handle = _HandleFactory()  # type: ignore[assignment]


def unwrap_handle_arg(annotation) -> type | None:
    """Return T if annotation is Handle[T], else None."""
    if get_origin(annotation) is None:
        return None
    args = get_args(annotation)
    if len(args) >= 3 and args[0] is str and args[1] is _HandleMarker:
        return args[2]
    return None
