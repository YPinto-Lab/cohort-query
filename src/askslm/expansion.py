"""What a field name for this question might look like.

A researcher writes "calprotectin". The submitting lab wrote `host_calpro_sam`,
`s100a8_sam`, or `calpro_ng_mg_sam` -- and a substring search for "calprotectin"
finds none of them. Curating a synonym list is endless and stale on arrival; the
model already knows calpro and S100A8/A9 ARE calprotectin, so it writes the list
per question instead.

Text only, like prompt.py, so an accuracy change can be attributed to a prompt diff.

Measured before this existed: `calpro` reaches 25 keys across 8,539 runs that the
literal word "calprotectin" never touches, and `s100a8` reaches one more. Terms that
match nothing cost nothing -- but GENERIC terms are expensive, which is why the
instruction forbids them and _generic_terms() drops them anyway if the model slips.
"""
from __future__ import annotations

MAX_TERMS = 12

SYSTEM_INSTRUCTION = """\
You expand a research question into fragments that might appear inside a database
FIELD NAME -- not values, not SQL.

For each measurement or phenotype the question names, include:
- the word itself, and shortened forms a submitter might type (calprotectin -> calpro)
- the underlying molecule, protein, or assay (calprotectin -> s100a8, s100a9)
- plausible misspellings

Do NOT include generic words that describe almost any sample: dna, sequence,
sequencing, sample, study, microbiome, metagenome, human, host, data. They match
thousands of unrelated fields and drown the useful ones.

Lowercase. No underscores or spaces -- fragments are matched as substrings.
Return JSON only: {"terms": ["...", "..."]}
"""
