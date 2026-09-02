#!/bin/bash
# Build every askslm artifact from a fresh SRA download.
#
#   1. sra_taxonomy_sorted.duckdb   tax_raw sorted by acc, narrowed to 4 columns   (~2 h)
#   2. sra_metadata_sorted.duckdb   metadata_raw sorted by biosample, all columns  (~10 min)
#   3. askslm_mirror.duckdb         views over 1 and 2 + Metalog tables + indexes  (~15 min)
#   4. + attribute_keys             every jattr key, so a phenotype can be found    (~10 min)
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
#   build_all.sh --sra-db PATH --metalog-dir PATH --out-dir PATH [--stage STAGE]
#   sbatch build_all.sh --sra-db ... --metalog-dir ... --out-dir ...
#
#   --sra-db        the SRA DuckDB you downloaded (holds metadata_raw and tax_raw)
#   --metalog-dir   the Metalog download (must contain "Metadata" and "Taxonomic Profiles")
#   --out-dir       where the three .duckdb files go; needs ~600 GB free
#   --stage         all (default) | sidecars (1-2) | mirror (3-6) | enrich (4-6 only)
#   --python        interpreter to use (default: python3)
#   --threads       (default: SLURM_CPUS_PER_TASK, else 8)
#   --memory-limit  DuckDB memory limit (default: 80% of --mem, else 32GB)
#
# Re-running is safe: each step builds into a "<target>.building" file and renames it
# over the target only after its checks pass, so an existing artifact survives a failure.
#
#SBATCH --job-name=askslm-build-all
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=48:00:00
#SBATCH --open-mode=append

set -euo pipefail
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)

SRA_DB=""; METALOG_DIR=""; OUT_DIR=""; STAGE=all
PY=python3; THREADS=""; MEMORY_LIMIT=""

die() { echo "ERROR: $*" >&2; echo "Run with --help for usage." >&2; exit 1; }
usage() { sed -n '2,25p' "${BASH_SOURCE[0]}" | sed 's/^# \{0,1\}//'; exit 0; }

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
case "$STAGE" in
    all|sidecars) [ -n "$SRA_DB" ] || die "--sra-db is required for stage '$STAGE'" ;;
esac
case "$STAGE" in
    all|mirror) [ -n "$METALOG_DIR" ] || die "--metalog-dir is required for stage '$STAGE'" ;;
esac

case "$STAGE" in all|sidecars) [ -r "$SRA_DB" ] || die "cannot read --sra-db: $SRA_DB" ;; esac
if [ "$STAGE" = all ] || [ "$STAGE" = mirror ]; then
    [ -d "$METALOG_DIR" ] || die "--metalog-dir is not a directory: $METALOG_DIR"
    for sub in "Metadata" "Taxonomic Profiles"; do
        [ -d "$METALOG_DIR/$sub" ] || die "--metalog-dir has no '$sub' subdirectory: $METALOG_DIR"
    done
fi
command -v "$PY" >/dev/null || die "--python not executable: $PY"
"$PY" -c "import duckdb" 2>/dev/null || die "$PY cannot import duckdb"

mkdir -p "$OUT_DIR"
OUT_DIR=$(cd -- "$OUT_DIR" && pwd)
TAXONOMY=$OUT_DIR/sra_taxonomy_sorted.duckdb
METADATA=$OUT_DIR/sra_metadata_sorted.duckdb
MIRROR=$OUT_DIR/askslm_mirror.duckdb
TMP=$OUT_DIR/duckdb_tmp_build_all
mkdir -p "$TMP"; trap 'rm -rf "$TMP"' EXIT

# Space needed scales with YOUR download, not with the Pinto lab's. The sorted
# sidecars together came to ~0.25x the source (the taxonomy is narrowed to 4 of 9
# columns, and sorting compresses better); 0.6x leaves room for the merge-sort spill.
free_gb=$(df -BG --output=avail "$OUT_DIR" | tail -1 | tr -dc '0-9')
case "$STAGE" in
    enrich) need=5 ;;                                  # adds a few small tables in place
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
    time "$PY" "$HERE/build_sorted_taxonomy.py" --sra-db "$SRA_DB" --out "$TAXONOMY" \
        --threads "$THREADS" --memory-limit "$MEMORY_LIMIT" --temp-dir "$TMP"

    echo "--- 2/6 sorted metadata -> $METADATA"
    time "$PY" "$HERE/build_sorted_metadata.py" --sra-db "$SRA_DB" --out "$METADATA" \
        --threads "$THREADS" --memory-limit "$MEMORY_LIMIT" --temp-dir "$TMP"
fi

if [ "$STAGE" = all ] || [ "$STAGE" = mirror ]; then
    for f in "$TAXONOMY" "$METADATA"; do
        [ -r "$f" ] || die "missing $f -- run with --stage sidecars first"
    done
    echo "--- 3/6 mirror -> $MIRROR"
    time "$PY" "$HERE/build_duckdb.py" --metalog-dir "$METALOG_DIR" \
        --sorted-taxonomy "$TAXONOMY" --sorted-metadata "$METADATA" --out "$MIRROR" \
        --threads "$THREADS" --memory-limit "$MEMORY_LIMIT" --temp-dir "$TMP"
fi

if [ "$STAGE" = all ] || [ "$STAGE" = mirror ] || [ "$STAGE" = enrich ]; then
    [ -r "$MIRROR" ] || die "missing $MIRROR -- run with --stage mirror first"
    # These three WRITE INTO the mirror, in this order: concept embeddings read both
    # attribute_keys and schema_catalog, so they must come last.
    echo "--- 4/6 attribute index"
    time "$PY" "$HERE/build_attribute_index.py" --db "$MIRROR"
    echo "--- 5/6 schema catalog"
    time "$PY" "$HERE/build_schema_catalog.py" --db "$MIRROR"
    echo "--- 6/6 concept embeddings (local SapBERT, no API key)"
    time "$PY" "$HERE/build_concept_embeddings.py" --db "$MIRROR"
fi

echo "--- verifying the mirror is complete"
"$PY" - "$MIRROR" "$HERE" <<'PYEOF'
import sys, duckdb
sys.path.insert(0, f"{sys.argv[2]}/../../src")
from askslm.adapters import missing_tables, REQUIRED_TABLES   # one definition, shared
con = duckdb.connect(sys.argv[1], read_only=True)
absent = missing_tables(con)
if absent:
    raise SystemExit(f"INCOMPLETE MIRROR -- missing: {absent}")
print(f"  all {len(REQUIRED_TABLES)} required tables/views present")
PYEOF'
import sys, duckdb
con = duckdb.connect(sys.argv[1], read_only=True)
present = {r[0] for r in con.execute("SELECT table_name FROM duckdb_tables()").fetchall()}
present |= {r[0] for r in con.execute("SELECT view_name FROM duckdb_views() WHERE NOT internal").fetchall()}
required = {"sra_metadata", "sra_taxonomy", "stat_coverage", "metalog_metadata",
            "metalog_metaphlan4", "metalog_motus3", "metalog_spire_motus", "mirror_config",
            "attribute_keys", "schema_catalog",
            "attribute_key_embeddings", "column_value_embeddings"}
missing = sorted(required - present)
if missing:
    raise SystemExit(f"INCOMPLETE MIRROR -- missing: {missing}")
print(f"  all {len(required)} required tables/views present")
PYEOF

echo "=== done at $(date -Is) ==="
ls -lh "$OUT_DIR"/*.duckdb
echo
echo "Point askslm at the mirror:  askslm.config(db='$MIRROR')"
