#!/bin/bash
# Build every askslm artifact from a fresh SRA download.
#
#   1. sra_taxonomy_sorted.duckdb   tax_raw sorted by acc, narrowed to 4 columns   (~2 h)
#   2. sra_metadata_sorted.duckdb   metadata_raw sorted by biosample, all columns  (~10 min)
#   3. askslm_mirror.duckdb         views over 1 and 2 + Metalog tables + indexes  (~15 min)
#   4. + attribute_keys_index/      jattr presence + content, embedded and written  (~4-6 h,
#      attribute_values_index       into LanceDB with an IVF_PQ index for search --
#                                    extraction+embedding dominates the time, not
#                                    indexing; unlike the DuckDB HNSW index this
#                                    replaced, the IVF_PQ build itself is cheap on
#                                    memory, ~2GB RSS measured live 2026-09-14)
#   5. + schema_catalog             columns and value vocabularies for the prompt   (~1 min)
#   6. + *_embeddings               local SapBERT vectors for concept search        (~10 min)
#
# Steps 4-6 add tables INTO the mirror from step 3 and are not optional: without them
# the LLM has no column vocabulary, no attribute lookup and no concept search, so
# discovery fails on questions that name a phenotype. They used to be run by hand.
#
# Only #3 is passed to askslm.config(db=...). It records the paths of #1 and #2 and
# re-attaches them on connect, so all three must stay where you built them.
#
# Usage:
#   build_all.sh --out-dir PATH [--sra-db PATH] [--metalog-dir PATH] [--stage STAGE]
#   sbatch build_all.sh --out-dir ...
#
#   --out-dir       where everything goes: raw/ (fetched inputs) + the three .duckdb
#                    files; needs ~600 GB free, more if it's also doing the fetch
#   --sra-db        an SRA DuckDB you already have (holds metadata_raw and tax_raw).
#                    Omit it and fetch_sra_raw.sh fetches one into --out-dir/raw first.
#   --metalog-dir   a Metalog download you already have (must contain "Metadata" and
#                    "Taxonomic Profiles"). Omit it and fetch_metalog.sh fetches one
#                    into --out-dir/raw/Metalog first.
#   --stage         all (default) | sidecars (1-2) | mirror (3-6) | enrich (4-6 only)
#   --python        interpreter to use (default: python3)
#   --threads       (default: SLURM_CPUS_PER_TASK, else 8)
#   --memory-limit  DuckDB memory limit (default: 80% of --mem, else 32GB)
#
# With no --sra-db/--metalog-dir this is the whole thing end to end: one command,
# a long wait (the SRA fetch alone is hours), and a finished mirror.
#
# Re-running is safe: each step builds into a "<target>.building" file and renames it
# over the target only after its checks pass, so an existing artifact survives a failure.
#
#SBATCH --job-name=askslm-build-all
#SBATCH --cpus-per-task=16
#SBATCH --mem=450G
#SBATCH --time=48:00:00
#SBATCH --open-mode=append

set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

SRA_DB=""; METALOG_DIR=""; OUT_DIR=""; STAGE=all
PY=python3; THREADS=""; MEMORY_LIMIT=""

die() { echo "ERROR: $*" >&2; echo "Run with --help for usage." >&2; exit 1; }
usage() { sed -n '2,38p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

while [ $# -gt 0 ]; do
    case "$1" in
        --sra-db)       SRA_DB=${2:-}; shift 2 ;;
        --metalog-dir)  METALOG_DIR=${2:-}; shift 2 ;;
        --out-dir)      OUT_DIR=${2:-}; shift 2 ;;
        --stage)        STAGE=${2:-}; shift 2 ;;
        --python)       PY=${2:-}; shift 2 ;;
        --threads)      THREADS=${2:-}; shift 2 ;;
        --memory-limit) MEMORY_LIMIT=${2:-}; shift 2 ;;
        -h|--help)      usage ;;
        *)              die "unknown argument: $1" ;;
    esac
done

THREADS=${THREADS:-${SLURM_CPUS_PER_TASK:-8}}
if [ -z "$MEMORY_LIMIT" ]; then
    if [ -n "${SLURM_MEM_PER_NODE:-}" ]; then MEMORY_LIMIT="$(( SLURM_MEM_PER_NODE * 8 / 10 ))MB"
    else MEMORY_LIMIT=32GB; fi
fi

# --- validate before doing hours of work ------------------------------------
case "$STAGE" in all|sidecars|mirror|enrich) ;; *) die "--stage must be all, sidecars, mirror or enrich" ;; esac
[ -n "$OUT_DIR" ] || die "--out-dir is required"
command -v "$PY" >/dev/null || die "--python not executable: $PY"
"$PY" -c "import duckdb" 2>/dev/null || die "$PY cannot import duckdb"

mkdir -p "$OUT_DIR"
OUT_DIR=$(cd -- "$OUT_DIR" && pwd)
RAW_DIR=$OUT_DIR/raw
TAXONOMY=$OUT_DIR/sra_taxonomy_sorted.duckdb
METADATA=$OUT_DIR/sra_metadata_sorted.duckdb
MIRROR=$OUT_DIR/askslm_mirror.duckdb
TMP=$OUT_DIR/duckdb_tmp_build_all
mkdir -p "$TMP"; trap 'rm -rf "$TMP"' EXIT

# --- fetch what wasn't handed to us ------------------------------------------
# --sra-db/--metalog-dir are optional: leave them out and we fetch both straight
# from their public sources into --out-dir/raw. Already fetched (from a previous
# run) is detected and not repeated.
if [ "$STAGE" = all ] || [ "$STAGE" = sidecars ]; then
    if [ -z "$SRA_DB" ]; then
        SRA_DB=$RAW_DIR/sra_processed.duckdb
        if [ ! -r "$SRA_DB" ]; then
            echo "--- fetching raw SRA metadata + STAT (no --sra-db given; this is hours) ---"
            mkdir -p "$RAW_DIR"
            "$HERE/fetch_sra_raw.sh" "$RAW_DIR"
        fi
    fi
    [ -r "$SRA_DB" ] || die "cannot read --sra-db: $SRA_DB"
fi

if [ "$STAGE" = all ] || [ "$STAGE" = mirror ]; then
    if [ -z "$METALOG_DIR" ]; then
        METALOG_DIR=$RAW_DIR/Metalog
        if [ ! -d "$METALOG_DIR/Metadata" ]; then
            echo "--- fetching Metalog (no --metalog-dir given) ---"
            "$HERE/fetch_metalog.sh" "$METALOG_DIR"
        fi
    fi
    [ -d "$METALOG_DIR" ] || die "--metalog-dir is not a directory: $METALOG_DIR"
    for sub in "Metadata" "Taxonomic Profiles"; do
        [ -d "$METALOG_DIR/$sub" ] || die "--metalog-dir has no '$sub' subdirectory: $METALOG_DIR"
    done
fi

# Space needed scales with YOUR download, not with the Pinto lab's. The sorted
# sidecars together came to ~0.25x the source (the taxonomy is narrowed to 4 of 9
# columns, and sorting compresses better); 0.6x leaves room for the merge-sort spill.
free_gb=$(df -BG --output=avail "$OUT_DIR" | tail -1 | tr -dc '0-9')
case "$STAGE" in
    # attribute_values_index's ~45GB of embeddings (14.9M rows x 768 floats,
    # measured on the real mirror 2026-09-12) is now stored TWICE -- once in its
    # DuckDB staging table, once in the LanceDB dataset built from it -- plus a
    # ~1.5GB IVF_PQ index (measured live 2026-09-14). The rest of this stage's
    # tables are small by comparison.
    enrich) need=110 ;;
    mirror) need=$(( $(du -BG -s "$TAXONOMY" 2>/dev/null | tr -dc '0-9' || echo 50) / 5 + 5 )) ;;
    *)      need=$(( $(du -BG -s "$SRA_DB" | tr -dc '0-9') * 6 / 10 + 5 )) ;;
esac
[ "$free_gb" -ge "$need" ] || die "only ${free_gb}G free at $OUT_DIR; stage '$STAGE' needs ~${need}G (use a different --out-dir)"
echo "  space: ${free_gb}G free, ~${need}G needed"

echo "=== askslm build_all on $(hostname) at $(date -Is) ==="
echo "  stage=$STAGE threads=$THREADS memory_limit=$MEMORY_LIMIT"
echo "  out-dir=$OUT_DIR (${free_gb}G free)"

if [ "$STAGE" = all ] || [ "$STAGE" = sidecars ]; then
    echo "--- 1/6 sorted taxonomy -> $TAXONOMY"
    time "$PY" "$HERE/steps/step1_sort_taxonomy.py" --sra-db "$SRA_DB" --out "$TAXONOMY" \
        --threads "$THREADS" --memory-limit "$MEMORY_LIMIT" --temp-dir "$TMP"

    echo "--- 2/6 sorted metadata -> $METADATA"
    time "$PY" "$HERE/steps/step2_sort_metadata.py" --sra-db "$SRA_DB" --out "$METADATA" \
        --threads "$THREADS" --memory-limit "$MEMORY_LIMIT" --temp-dir "$TMP"
fi

if [ "$STAGE" = all ] || [ "$STAGE" = mirror ]; then
    for f in "$TAXONOMY" "$METADATA"; do
        [ -r "$f" ] || die "missing $f -- run with --stage sidecars first"
    done
    echo "--- 3/6 mirror -> $MIRROR"
    time "$PY" "$HERE/steps/step3_assemble_mirror.py" --metalog-dir "$METALOG_DIR" \
        --sorted-taxonomy "$TAXONOMY" --sorted-metadata "$METADATA" --out "$MIRROR" \
        --threads "$THREADS" --memory-limit "$MEMORY_LIMIT" --temp-dir "$TMP"
fi

if [ "$STAGE" = all ] || [ "$STAGE" = mirror ] || [ "$STAGE" = enrich ]; then
    [ -r "$MIRROR" ] || die "missing $MIRROR -- run with --stage mirror first"
    # These three WRITE INTO the mirror. step7 doesn't depend on the other two and
    # could run in any order, but runs first here since it's by far the longest.
    echo "--- 4/6 attribute_keys_index / attribute_values_index"
    time "$PY" "$HERE/steps/step7_build_attribute_indexes.py" --db "$MIRROR" \
        --threads "$THREADS" --memory-limit "$MEMORY_LIMIT" --temp-dir "$TMP"
    echo "--- 5/6 schema catalog"
    time "$PY" "$HERE/steps/step5_catalog_schema.py" --db "$MIRROR"
    echo "--- 6/6 concept embeddings (local SapBERT, no API key)"
    time "$PY" "$HERE/steps/step6_embed_concepts.py" --db "$MIRROR"
fi

echo "--- verifying the mirror is complete"
"$PY" - "$MIRROR" "$HERE" <<'PYEOF'
import sys, duckdb
from pathlib import Path
sys.path.insert(0, f"{sys.argv[2]}/../../src")
from askslm.adapters import missing_tables, missing_lance_tables, REQUIRED_TABLES, REQUIRED_LANCE_TABLES
con = duckdb.connect(sys.argv[1], read_only=True)
absent = missing_tables(con) + [f"{name}.lance" for name in missing_lance_tables(Path(sys.argv[1]).parent)]
if absent:
    raise SystemExit(f"INCOMPLETE MIRROR -- missing: {absent}")
print(f"  all {len(REQUIRED_TABLES) + len(REQUIRED_LANCE_TABLES)} required tables/views present")
PYEOF

echo "=== done at $(date -Is) ==="
ls -lh "$OUT_DIR"/*.duckdb
echo
echo "Point askslm at the mirror:  askslm.config(db='$MIRROR')"
