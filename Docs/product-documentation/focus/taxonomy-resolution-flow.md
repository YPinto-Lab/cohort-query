# Taxonomy Resolution Flow (Runner + CLI)

This page answers:
- Are tax IDs updated in runner outputs?
- Are tax IDs updated in Workspaces/<workspace>/results/abundance_matrix/abundance_matrix.csv?
- What is the exact stage order?
- Where to find detailed run summaries?

## Short Answers

1. Runner taxonomy output (`Ask_SLM_Taxon_Abundance_Matrix.csv`) uses resolved tax IDs.
2. CLI `abundance-matrix` output (`abundance_matrix/abundance_matrix.csv`) does not run merged.dmp tax ID resolution.
3. Stage order is enrichment -> taxonomy resolution + matrix build -> merge -> lineage DB.
4. Detailed taxonomy-resolution artifacts are written into results:
   - `Ask_SLM_Taxonomy_Resolution_Summary.json`
   - `Ask_SLM_Taxonomy_Resolution_Changes.csv`

`Ask_SLM_Taxonomy_Resolution_Changes.csv` schema:
- `old_tax_id`
- `resolved_tax_id`
- `samples` (unique samples/acc values affected by this mapping pair)
- `total_count_sum` (sum of total_count across affected rows)

## Stage Order and What Happens

1. Enrichment stage:
   - Inputs: metadata.csv + mapping configs.
   - Output: enriched metadata cache artifacts and enrichment stamp.

2. Taxonomy stage:
   - Inputs: taxonomy.csv + explicit merged.dmp path.
   - Resolve historical tax IDs using merged.dmp.
   - Aggregate duplicate (acc, resolved_tax_id) rows by summing total_count.
   - Build and save:
     - `Ask_SLM_Taxon_Abundance_Matrix.csv`
     - `Ask_SLM_Taxon_Lookup.csv`
   - Save detailed resolution report artifacts:
     - `Ask_SLM_Taxonomy_Resolution_Summary.json`
     - `Ask_SLM_Taxonomy_Resolution_Changes.csv`

3. Merge stage:
   - Left-join enriched metadata with abundance matrix.
   - Save `Ask_SLM_Analysis_Wide_Dataset.csv` and metadata columns JSON.

4. Lineage accessor stage:
   - Build/load lineage DB from taxonomy lookup.

## Why Runner and CLI Differ

The runner taxonomy path resolves merged IDs before matrix assembly.

The CLI `abundance-matrix` command currently pivots directly from taxonomy rows by `name`:
- File produced: `Workspaces/<workspace>/results/abundance_matrix/abundance_matrix.csv`
- It is a name-based matrix and does not apply merged.dmp resolution in the current implementation.

## Where to Inspect Implementation

- Runner taxonomy stage orchestration and artifact writing:
  - `Engines/DatasetAssemblyEngine/runtime_assembly_engine.py`
- Tax ID resolution logic and summary calculations:
  - `Engines/DatasetAssemblyEngine/DeprecatedTaxonomyResolutionEngine.py`
- CLI abundance-matrix command behavior:
  - `cli.py` (function `cmd_abundance_matrix`)