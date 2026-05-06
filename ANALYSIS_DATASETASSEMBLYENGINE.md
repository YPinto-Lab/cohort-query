# DatasetAssemblyEngine Architecture Analysis

## Overview
The DatasetAssemblyEngine orchestrates a multi-stage data processing pipeline that converts raw biological sequencing data into analysis-ready datasets. It currently spans **8 files** across 2 directories with a distributed caching/stamping pattern.

---

## File-by-File Breakdown

### **Top Level (DatasetAssemblyEngine/)**

#### 1. `__init__.py`
**What it does:** Barrel export file for the module.
**Why:** Exposes public API (`compute_taxonomy_matrices`, `compute_analysis_wide_dataset`, `DeprecatedTaxonomyResolutionEngine`, `DatasetAssemblyRuntimeEngine`) to consumers.
**Why it exists:** Clean module interface; simplifies client imports.

---

#### 2. `dataset_assembly_engine.py` 
**What it does:** Pure computational functions (NO FILE I/O):
- `compute_taxonomy_matrices()` - Transforms raw taxonomy data → sample×taxon abundance matrix + taxon lookup table
- `compute_analysis_wide_dataset()` - Merges enriched metadata with abundance matrix

**Why it exists:** Separation of concerns. Computation is decoupled from caching/orchestration logic. These functions are **pure transformations** that don't manage state.

**Observation:** This is good practice—the actual transformation logic is isolated.

---

#### 3. `DeprecatedTaxonomyResolutionEngine.py`
**What it does:** Handles NCBI taxonomy ID consolidation:
- Maps deprecated tax IDs → active tax IDs using `merged.dmp` 
- Re-aggregates counts when a deprecated ID is resolved
- Tracks resolution statistics/changes for audit trail

**Why it exists:** NCBI periodically merges old tax IDs into new ones. Historical SRA records can reference deprecated IDs. Without resolution, the same organism could be split across multiple tax IDs, underestimating abundance.

**Observation:** This is pure computation (no file I/O) but is **stage-specific**. It's not reused elsewhere.

---

#### 4. `runtime_assembly_engine.py`
**What it does:** Simple re-export of `DatasetAssemblyRuntimeEngine` from `runtime_assembly/engine.py`.

**Why it exists:** Module structure indirection—probably for backwards compatibility or planned refactoring.

**Observation:** Could be eliminated; direct import from `runtime_assembly.engine` would work.

---

#### 5. `runtime_assembly_models.py`
**What it does:** Dataclass definitions for request/configuration:
- `RuntimeAssemblyPaths` - Directory structure definition
- `EnrichmentStageRequest` - Config for enrichment stage
- `TaxonomyStageRequest` - Config for taxonomy stage
- `MergeStageRequest` - Config for merge stage
- `TaxonomyAccessorRequest` - Config for lineage DB construction

**Why it exists:** Type-safe request objects instead of loose parameter passing.

**Observation:** Good practice. Makes function signatures clear.

---

#### 6. `runtime_assembly_services.py`
**What it does:** Another barrel re-export of runner classes from `runtime_assembly/`.

**Why it exists:** Module indirection.

**Observation:** Could be eliminated; consumers could import directly from `runtime_assembly`.

---

### **Subdirectory: runtime_assembly/**

#### 7. `base.py`
**What it does:** Base class `RuntimeAssemblyStageBase` with utilities:
- `_file_state()` - Tracks file metadata (exists, size, mtime_ns) for cache invalidation
- `_read_json()` / `_write_json()` - JSON serialization helpers
- `_cache_matches()` - Compares current computation hash against saved stamp

**Why it exists:** Shared caching infrastructure for all stage runners.

**Observation:** This is the **core cache mechanism**. Each stage computes a "stamp" (hash) of inputs and compares against saved stamps.

---

#### 8. `engine.py`
**What it does:** Orchestrator class `DatasetAssemblyRuntimeEngine`:
- Creates instances of all 4 stage runners (enrichment, taxonomy, merge, accessor)
- Validates that required directories exist
- Routes requests to correct stage via `run_enrichment_stage()`, `run_taxonomy_stage()`, etc.

**Why it exists:** Central entry point for the pipeline.

**Observation:** Thin orchestrator. Good separation.

---

#### 9. `enrichment.py`
**What it does:** Stage 1: `EnrichmentStageRunner`
- **Input:** Raw metadata.csv + mapping configs per BioProject
- **Process:** For each project, apply mapping config to enrich metadata with new columns
- **Output:** Enriched metadata + list of mapped columns + list of projects without configs
- **Caching:** Stamps based on metadata file mtime, all config file mtimes, and view_name

**Why it exists:** Metadata enrichment is a distinct phase that can be expensive (depends on many configs).

**Observations:**
- Stamp includes individual file states for **all project configs** → very granular invalidation
- Has a "template refresh" fallback if config missing

---

#### 10. `taxonomy.py`
**What it does:** Stage 2: `TaxonomyStageRunner`
- **Input:** Raw taxonomy.csv + merged.dmp file
- **Process:** 
  1. Load merged tax ID mapping from merged.dmp
  2. Resolve deprecated tax IDs using DeprecatedTaxonomyResolutionEngine
  3. Compute abundance matrix (sample × taxon) and taxon lookup table
  4. Output resolution summary and changes log
- **Output:** Abundance matrix, taxon lookup table, resolution artifacts
- **Caching:** Stamps based on taxonomy.csv mtime, merged.dmp mtime, and taxon_key_sep

**Why it exists:** Taxonomy processing is computationally intensive (especially the resolution step).

**Observations:**
- Complex with lots of "backfill" logic (handles cases where old caches exist without resolution artifacts)
- **Code quality issue:** Lines 87-94 are formatted poorly (multiple statements on one line)
- Has two code paths: cache hit (with resolution backfill) and rebuild

---

#### 11. `merge.py`
**What it does:** Stage 3: `MergeStageRunner`
- **Input:** Enriched metadata + abundance matrix
- **Process:** Join metadata columns with taxon abundance features
- **Output:** Analysis-wide dataset (one row per sample, columns = metadata + taxa)
- **Caching:** Stamps based on enrichment AND taxonomy stage stamps (depends on both!)

**Why it exists:** Final assembly of features for analysis.

**Observations:**
- Depends on outputs from both enrichment AND taxonomy stages
- Has a "compat" cache stamp (schema_version "combined_v2") which seems redundant

---

#### 12. `accessor.py`
**What it does:** Stage 4: `TaxonomyAccessorRunner`
- **Input:** Taxon lookup table from taxonomy stage
- **Process:** Build SQLite database for lineage lookups (enable fast ancestor/descendant queries)
- **Output:** TaxonomyAccessor object (wraps SQLite DB)
- **Caching:** Stamps based on taxonomy stage stamp

**Why it exists:** Lazy construction of query object—only built if needed; cached because it's expensive.

**Observations:**
- Depends on taxonomy stage completing first
- Requires checking for taxonomy stage stamp existence

---

## Current Caching Pattern

Each stage (except accessor) independently tracks:
1. **Input file states** (mtime_ns, size)
2. **Parameters** (view_name, etc.)
3. Compares against saved "stamp" JSON files in `assembly_db_dir/`

**Problems with current approach:**
- ❌ **Scattered:** 4 different stage runners each implement similar cache logic
- ❌ **Fragile:** File metadata is used as proxy for "content changed" (works but brittle)
- ❌ **Input folder changes not tracked:** If a file is DELETED from input folder, stamp won't invalidate
- ❌ **Redundant:** Multiple stages duplicate the stamp-comparison pattern
- ❌ **Implicit dependencies:** Merge stage depends on enrichment + taxonomy, but this is buried in its `_current_stamp()` logic

---

## What Should Be Deleted (Code Smell Markers)

1. **`runtime_assembly_engine.py`** → Direct re-export; import from `runtime_assembly.engine` directly
2. **`runtime_assembly_services.py`** → Same; just a barrel file that re-exports from `runtime_assembly`
3. **Backfill logic in `taxonomy.py`** (lines 58-61) → Handles edge case of old caches; if we redesign caching, this becomes unnecessary
4. **"compat" stamp in `merge.py`** → Seems like historical versioning; if we consolidate, remove it
5. **`_file_state()` method** → File mtime-based invalidation is indirect; we should track input folder digest/hash instead

---

## Proposed Redesign: Unified Caching System

### Core Idea
**"One roof" = Single CacheManager that:**
1. **Hashes entire input folders** (not individual files) at pipeline start
2. **Maintains a unified cache registry** with dependencies
3. **Invalidates atomically** when any input changes
4. **Tracks explicit stage dependencies** (merge depends on enrichment+taxonomy)

### New Architecture

```
Engines/DatasetAssemblyEngine/
  ├── dataset_assembly_engine.py (keep: pure computation)
  ├── DeprecatedTaxonomyResolutionEngine.py (keep: pure computation)
  ├── cache/
  │   ├── __init__.py
  │   ├── cache_manager.py (NEW: unified cache system)
  │   ├── cache_models.py (NEW: CacheEntry, StageDependency)
  │   └── input_tracker.py (NEW: folder hash tracking)
  ├── stages/
  │   ├── __init__.py
  │   ├── base.py (simplified: remove file_state logic)
  │   ├── enrichment.py (refactored to use CacheManager)
  │   ├── taxonomy.py (refactored)
  │   ├── merge.py (refactored)
  │   └── accessor.py (refactored)
  └── runtime_assembly_engine.py (convert to simple import)
```

### Key Changes

1. **InputTracker** - Hash entire input folder:
   ```python
   tracker = InputTracker(workspace_input_dir)
   input_digest = tracker.compute_digest()  # SHA256 hash of all files
   ```

2. **CacheManager** - Centralized entry point:
   ```python
   cache = CacheManager(assembly_db_dir)
   
   # Check if stage is valid given inputs
   is_valid = cache.is_stage_valid(
       stage="enrichment",
       input_digest=input_digest,
       params={"view_name": "v1", "configs_digest": configs_hash}
   )
   
   # If valid, load; else recompute & save
   if is_valid:
       result = cache.load("enrichment")
   else:
       result = compute_enrichment(...)
       cache.save("enrichment", result, input_digest, params)
   ```

3. **Explicit Dependencies**:
   ```python
   # In registry
   {
       "enrichment": {
           "inputs": ["metadata_digest"],
           "outputs": ["enriched_metadata.csv"],
       },
       "taxonomy": {
           "inputs": ["taxonomy_digest", "merged_dump_digest"],
           "outputs": ["abundance_matrix.csv"],
       },
       "merge": {
           "depends_on": ["enrichment", "taxonomy"],
           "inputs": ["enrichment_digest", "taxonomy_digest"],
           "outputs": ["analysis_wide_dataset.csv"],
       },
       "accessor": {
           "depends_on": ["taxonomy"],
       }
   }
   ```

4. **Stage Runners** - Simplified:
   ```python
   class EnrichmentStageRunner(RuntimeAssemblyStageBase):
       def run(self, request):
           cache = self.cache_manager  # Now injected
           if cache.is_valid("enrichment"):
               return cache.load("enrichment")
           result = self._compute(request)
           cache.save("enrichment", result)
           return result
       
       def _compute(self, request):
           # Only the actual logic here
   ```

---

## Benefits of Unified Caching

✅ **Single source of truth** → No duplicated stamp logic  
✅ **Folder-level tracking** → Detects deletions automatically  
✅ **Explicit dependency graph** → Merge automatically invalidates if enrichment/taxonomy change  
✅ **Cleaner stage code** → Focus on computation, not caching  
✅ **Easier to test** → Mock CacheManager, not file I/O  
✅ **Atomic invalidation** → If input folder changes, entire pipeline knows  

---

## Code to Delete/Simplify

| File | Action | Reason |
|------|--------|--------|
| `runtime_assembly_engine.py` | Delete | Simple re-export |
| `runtime_assembly_services.py` | Delete | Simple re-export |
| Backfill logic in `taxonomy.py` (lines 58-61) | Delete | Not needed with unified cache |
| "compat" stamp in `merge.py` | Delete | Redundant versioning |
| `_file_state()` in `base.py` | Delete | Replaced by folder hash |
| Multiple stamp comparisons | Consolidate | Into CacheManager |

---

## Implementation Order

1. Create `cache/cache_manager.py` and `cache/input_tracker.py`
2. Create `cache/cache_models.py` with data classes
3. Refactor `base.py` to use CacheManager (remove _file_state, _read_json, _write_json)
4. Update each stage runner (enrichment, taxonomy, merge, accessor)
5. Delete redundant re-export files
6. Delete DeprecatedTaxonomyResolutionEngine? (Keep for now—it's good code, just used by taxonomy.py)


