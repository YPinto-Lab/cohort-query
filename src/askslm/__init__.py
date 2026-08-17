"""askslm — a read-only package that turns a research question into a feature table.

The pre-pivot workspace/agent/web code has been removed. The facade specified in the
architecture doc (config, ask, load_plan) is not built yet; what survives here is the
material the new package reuses:

    sra_schema  — SRA column contracts, the seed for SchemaCatalog's LLM prompt
    taxonomy    — lineage_table, the ete3 tax_id -> lineage builder STAT profiles need

Design: Docs/superpowers/specs/2026-06-17-askslm-architecture-hld-lld.html
"""
