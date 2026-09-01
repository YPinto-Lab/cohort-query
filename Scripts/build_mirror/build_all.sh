#!/bin/bash
# Build every askslm artifact from a fresh SRA download, in dependency order.
#
#   1. sra_taxonomy_sorted.duckdb   tax_raw sorted by acc, narrowed to 4 columns   (~2 h)
#   2. sra_metadata_sorted.duckdb   metadata_raw sorted by biosample, all columns  (~7 min)
#   3. askslm_mirror.duckdb         views over 1 and 2 + Metalog tables + indexes  (~1 h)
#
# Steps 1 and 2 read the SRA download and nothing else, so they are independent -- but
# step 3 needs both, because it creates its views against them and derives stat_coverage
# from the taxonomy.
#
# Why sorted sidecars rather than tables inside the mirror: sort order IS the index in a
# column store. Sorted by its read key, a cohort filter prunes row groups instead of
# scanning. Measured on a 3,573-biosample cohort, the metadata read went 1,772s -> 50s
# (20 of 319 row groups touched), and 17.8s once jattr is left unprojected.
#
# Usage:
#   bash   Scripts/build_mirror/build_all.sh          # everything, in the foreground
#   sbatch Scripts/build_mirror/build_all.sh          # ... or as one Slurm job
#   sbatch Scripts/build_mirror/build_all.sh mirror   # just step 3 (sidecars exist)
#
# Override any path from the environment: SRA_DB, METALOG_DIR, MIRROR_DIR, PY.
#
#SBATCH --job-name=just-ask-build-all
#SBATCH --partition=cpu512G-48h
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=48:00:00
#SBATCH --output=build-all-%j.out
#SBATCH --error=build-all-%j.err
#SBATCH --open-mode=append

set -euo pipefail

# Repo root, so the script works from a clone anywhere. Everything below can be
# overridden from the environment -- the defaults are the Pinto lab's paths.
HERE=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
ROOT=$(cd -- "$HERE/../.." && pwd)
PY=${PY:-python3}

SRA_DB=${SRA_DB:-/private/pinto-lab/STAT/sra_processed.duckdb}
METALOG_DIR=${METALOG_DIR:-$HOME/Downloads/Metalog}
MIRROR_DIR=${MIRROR_DIR:-$ROOT/mirror}
OUT_LOGS=${OUT_LOGS:-$ROOT/logs}
TMP=${TMP:-$MIRROR_DIR/duckdb_tmp_build_all}
MIN_FREE_GB=600          # 128 (tax) + 31 (meta) + 13 (mirror) + spill + headroom

STAGE=${1:-all}
mkdir -p "$MIRROR_DIR" "$OUT_LOGS" "$TMP"
trap 'rm -rf "$TMP"' EXIT

echo "=== job ${SLURM_JOB_ID:-local} on $(hostname) at $(date -Is) ==="
echo "stage=$STAGE  sra_db=$SRA_DB  metalog=$METALOG_DIR"

free_gb=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9')
echo "free space: ${free_gb}G (need >= ${MIN_FREE_GB}G)"
[ "$free_gb" -ge "$MIN_FREE_GB" ] || { echo "ABORT: not enough free space on a shared volume"; exit 1; }
test -r "$SRA_DB" || { echo "ABORT: cannot read $SRA_DB"; exit 1; }

if [ "$STAGE" = all ]; then
    echo "--- 1/3 sorted taxonomy"
    time $PY "$HERE/build_sorted_taxonomy.py" \
        --sra-db "$SRA_DB" --out "$MIRROR_DIR/sra_taxonomy_sorted.duckdb" \
        --threads "${SLURM_CPUS_PER_TASK:-8}" --memory-limit 380GB --temp-dir "$TMP"

    echo "--- 2/3 sorted metadata"
    time $PY "$HERE/build_sorted_metadata.py" \
        --sra-db "$SRA_DB" --out "$MIRROR_DIR/sra_metadata_sorted.duckdb" \
        --threads "${SLURM_CPUS_PER_TASK:-8}" --memory-limit 380GB --temp-dir "$TMP"
fi

echo "--- 3/3 mirror"
for f in sra_taxonomy_sorted.duckdb sra_metadata_sorted.duckdb; do
    test -r "$MIRROR_DIR/$f" || { echo "ABORT: $MIRROR_DIR/$f missing -- run without 'mirror'"; exit 1; }
done
time $PY "$HERE/build_duckdb.py" \
    --metalog-dir      "$METALOG_DIR" \
    --sorted-taxonomy  "$MIRROR_DIR/sra_taxonomy_sorted.duckdb" \
    --sorted-metadata  "$MIRROR_DIR/sra_metadata_sorted.duckdb" \
    --out              "$MIRROR_DIR/askslm_mirror.duckdb" \
    --threads "${SLURM_CPUS_PER_TASK:-8}" --memory-limit 380GB --temp-dir "$TMP"

echo "=== result ==="
ls -lh "$MIRROR_DIR"
df -BG --output=avail "$ROOT" | tail -1
echo "=== done at $(date -Is) ==="
echo
echo "The mirror records the two sidecar paths in mirror_config and the package"
echo "re-attaches them on connect. Moving a sidecar means rebuilding the mirror,"
echo "or updating its mirror_config row -- the views resolve by path."
