"""Accessor for ENVO term lookups via OLS4."""

from __future__ import annotations

import json
import re
from typing import Dict
from urllib.error import HTTPError, URLError
from urllib.parse import quote
from urllib.request import urlopen


ENVO_PATTERN = re.compile(r"\bENVO:\d{7,}\b", re.IGNORECASE)


class EnvoOntologyAccessor:
    """Fetch ENVO term label/definition from OLS4 with graceful fallback."""

    def fetch_term(self, envo_id: str, timeout_seconds: int = 8) -> Dict[str, str]:
        normalized = envo_id.strip().upper().replace("_", ":")
        if not ENVO_PATTERN.search(normalized):
            return {"id": normalized, "label": normalized, "definition": "", "source": "invalid"}

        numeric = normalized.split(":", 1)[1]
        iri = f"http://purl.obolibrary.org/obo/ENVO_{numeric}"
        encoded_iri = quote(iri, safe="")
        url = f"https://www.ebi.ac.uk/ols4/api/ontologies/envo/terms/{encoded_iri}"

        try:
            with urlopen(url, timeout=timeout_seconds) as response:
                payload = json.loads(response.read().decode("utf-8"))

            label = payload.get("label") or normalized
            definition = ""
            definitions = payload.get("description") or []
            if definitions:
                definition = str(definitions[0])

            return {
                "id": normalized,
                "label": str(label),
                "definition": definition,
                "source": "ols4",
            }
        except (URLError, HTTPError, TimeoutError, ValueError):
            return {
                "id": normalized,
                "label": normalized,
                "definition": "",
                "source": "fallback",
            }
