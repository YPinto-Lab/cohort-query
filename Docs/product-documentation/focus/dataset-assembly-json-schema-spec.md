# DatasetAssemblyEngine JSON Schema Spec

This is the canonical field specification for pipeline JSON artifacts.

## Conventions

- `status` enum: `ok` | `error`
- `schema_version`: fixed string per artifact type
- `input_fingerprint`: SHA-256 hex of workspace input folder contents
- timestamps: ISO 8601 UTC (`YYYY-MM-DDTHH:MM:SSZ`)
- unknown fields: allowed, but required fields below must always be present

---

## 1) `enrichment_summary.json`

Path:

- `results/abundance_matrices/stage_01_enrichment/enrichment_summary.json`

Required fields:

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | must be `enrichment_summary_v1` |
| `stage_name` | string | must be `enrichment` |
| `status` | string | `ok` or `error` |
| `input_fingerprint` | string | current run fingerprint |
| `rows_in` | integer | source rows read |
| `rows_out` | integer | rows written |
| `output_files` | object | artifact map |
| `started_at` | string | ISO 8601 UTC |
| `finished_at` | string | ISO 8601 UTC |

Optional fields:

- `mapping_configs_used` (array of strings)
- `warnings` (array of strings)
- `error_message` (string; required when `status=error`)

Success example:

```json
{
  "schema_version": "enrichment_summary_v1",
  "stage_name": "enrichment",
  "status": "ok",
  "input_fingerprint": "8f4d...",
  "rows_in": 120,
  "rows_out": 120,
  "output_files": {
    "enriched_metadata_csv": "stage_01_enrichment/enriched_metadata.csv"
  },
  "mapping_configs_used": ["project_a.json"],
  "warnings": [],
  "started_at": "2026-04-30T10:00:00Z",
  "finished_at": "2026-04-30T10:00:02Z"
}
```

Error example:

```json
{
  "schema_version": "enrichment_summary_v1",
  "stage_name": "enrichment",
  "status": "error",
  "input_fingerprint": "8f4d...",
  "rows_in": 120,
  "rows_out": 0,
  "output_files": {},
  "error_message": "Missing required metadata column: acc",
  "started_at": "2026-04-30T10:00:00Z",
  "finished_at": "2026-04-30T10:00:01Z"
}
```

---

## 2) `taxonomy_resolution_summary.json`

Path:

- `results/abundance_matrices/stage_02_taxonomy_resolution/taxonomy_resolution_summary.json`

Required fields:

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | must be `taxonomy_resolution_summary_v1` |
| `stage_name` | string | must be `taxonomy_resolution` |
| `status` | string | `ok` or `error` |
| `input_fingerprint` | string | current run fingerprint |
| `merged_dump_path` | string | absolute or workspace-relative path |
| `merged_dump_rule_count` | integer | number of merged rules loaded |
| `input_rows` | integer | rows in source taxonomy |
| `resolved_rows` | integer | rows in resolved taxonomy |
| `rows_updated` | integer | rows affected by tax ID remap |
| `unique_old_tax_ids_updated` | integer | unique old IDs replaced |
| `output_files` | object | artifact map |
| `started_at` | string | ISO 8601 UTC |
| `finished_at` | string | ISO 8601 UTC |

Optional fields:

- `input_unique_tax_ids` (integer)
- `resolved_unique_tax_ids` (integer)
- `warnings` (array of strings)
- `error_message` (string; required when `status=error`)

---

## 3) `aggregation_summary.json`

Path:

- `results/abundance_matrices/stage_03_aggregation/aggregation_summary.json`

Required fields:

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | must be `aggregation_summary_v1` |
| `stage_name` | string | must be `aggregation` |
| `status` | string | `ok` or `error` |
| `input_fingerprint` | string | current run fingerprint |
| `input_rows` | integer | rows read from resolved taxonomy |
| `unique_samples` | integer | sample count |
| `unique_taxa` | integer | taxon key count |
| `output_files` | object | artifact map |
| `started_at` | string | ISO 8601 UTC |
| `finished_at` | string | ISO 8601 UTC |

Optional fields:

- `taxon_key_separator` (string)
- `warnings` (array of strings)
- `error_message` (string; required when `status=error`)

---

## 4) `merge_summary.json` (Final Assembly summary)

Path:

- `results/abundance_matrices/stage_04_final_assembly/merge_summary.json`

Required fields:

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | must be `final_assembly_summary_v1` |
| `stage_name` | string | must be `final_assembly` |
| `status` | string | `ok` or `error` |
| `input_fingerprint` | string | current run fingerprint |
| `metadata_rows` | integer | enriched metadata rows |
| `matrix_sample_rows` | integer | wide matrix row count |
| `matrix_taxa_columns` | integer | wide matrix taxa column count |
| `analysis_wide_rows` | integer | merged dataset rows |
| `output_files` | object | artifact map |
| `started_at` | string | ISO 8601 UTC |
| `finished_at` | string | ISO 8601 UTC |

Optional fields:

- `null_values_filled` (integer)
- `warnings` (array of strings)
- `error_message` (string; required when `status=error`)

Required `output_files` keys when `status=ok`:

- `abundance_matrix_csv`
- `abundance_maaslin_tsv`
- `analysis_wide_dataset_csv`

---

## 5) `accessor_summary.json`

Path:

- `results/abundance_matrices/stage_05_accessor/accessor_summary.json`

Required fields:

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | must be `accessor_summary_v1` |
| `stage_name` | string | must be `accessor` |
| `status` | string | `ok` or `error` |
| `input_fingerprint` | string | current run fingerprint |
| `source_lookup_rows` | integer | taxon lookup rows consumed |
| `indexed_records` | integer | records written/indexed |
| `output_files` | object | artifact map |
| `started_at` | string | ISO 8601 UTC |
| `finished_at` | string | ISO 8601 UTC |

Optional fields:

- `index_backend` (string)
- `warnings` (array of strings)
- `error_message` (string; required when `status=error`)

---

## 6) `pipeline_manifest.json`

Path:

- `results/abundance_matrices/manifests/pipeline_manifest.json`

Required fields:

| Field | Type | Notes |
|---|---|---|
| `schema_version` | string | must be `pipeline_manifest_v1` |
| `pipeline_version` | string | implementation version |
| `input_fingerprint` | string | current run fingerprint |
| `workspace_input_dir` | string | run input folder |
| `results_root_dir` | string | `results/abundance_matrices` |
| `stage_order` | array of strings | fixed order list |
| `stage_status` | object | stage -> `ok`/`error`/`skipped` |
| `stage_summaries` | object | stage -> summary path |
| `artifact_paths` | object | canonical artifact map |
| `run_started_at` | string | ISO 8601 UTC |
| `run_finished_at` | string | ISO 8601 UTC |

Optional fields:

- `resume_from_stage` (string)
- `warnings` (array of strings)
- `notes` (string)

Required `stage_order` value:

```json
[
  "enrichment",
  "taxonomy_resolution",
  "aggregation",
  "final_assembly",
  "accessor"
]
```

Required `artifact_paths` keys:

- `enriched_metadata_csv`
- `resolved_taxonomy_csv`
- `taxonomy_resolution_changes_csv`
- `counts_parquet`
- `taxon_lookup_csv`
- `abundance_matrix_csv`
- `abundance_maaslin_tsv`
- `analysis_wide_dataset_csv`
- `pipeline_manifest_json`

Manifest example:

```json
{
  "schema_version": "pipeline_manifest_v1",
  "pipeline_version": "1.0.0",
  "input_fingerprint": "8f4d...",
  "workspace_input_dir": "Workspaces/ABX/input",
  "results_root_dir": "Workspaces/ABX/results/abundance_matrices",
  "stage_order": [
    "enrichment",
    "taxonomy_resolution",
    "aggregation",
    "final_assembly",
    "accessor"
  ],
  "stage_status": {
    "enrichment": "ok",
    "taxonomy_resolution": "ok",
    "aggregation": "ok",
    "final_assembly": "ok",
    "accessor": "ok"
  },
  "stage_summaries": {
    "enrichment": "stage_01_enrichment/enrichment_summary.json",
    "taxonomy_resolution": "stage_02_taxonomy_resolution/taxonomy_resolution_summary.json",
    "aggregation": "stage_03_aggregation/aggregation_summary.json",
    "final_assembly": "stage_04_final_assembly/merge_summary.json",
    "accessor": "stage_05_accessor/accessor_summary.json"
  },
  "artifact_paths": {
    "enriched_metadata_csv": "stage_01_enrichment/enriched_metadata.csv",
    "resolved_taxonomy_csv": "stage_02_taxonomy_resolution/resolved_taxonomy.csv",
    "taxonomy_resolution_changes_csv": "stage_02_taxonomy_resolution/taxonomy_resolution_changes.csv",
    "counts_parquet": "stage_03_aggregation/counts.parquet",
    "taxon_lookup_csv": "stage_03_aggregation/taxon_lookup.csv",
    "abundance_matrix_csv": "stage_04_final_assembly/abundance_matrix.csv",
    "abundance_maaslin_tsv": "stage_04_final_assembly/abundance_maaslin.tsv",
    "analysis_wide_dataset_csv": "stage_04_final_assembly/analysis_wide_dataset.csv",
    "pipeline_manifest_json": "manifests/pipeline_manifest.json"
  },
  "run_started_at": "2026-04-30T10:00:00Z",
  "run_finished_at": "2026-04-30T10:00:12Z"
}
```

---

## Validation Rules Summary

- If stage summary is missing -> stage invalid
- If `status != ok` -> stage invalid
- If summary `input_fingerprint` differs from current hash -> stage invalid
- Final Assembly may run only when Enrichment, Taxonomy Resolution, and Aggregation are valid
- Manifest is written last for a successful run

