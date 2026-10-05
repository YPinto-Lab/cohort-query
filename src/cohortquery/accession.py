"""The sample key. Its own module because both cohort.py and jattr_concepts.py
need it and importing it from either would create a cycle."""
from __future__ import annotations

from typing import NewType

Accession = NewType("Accession", str)
