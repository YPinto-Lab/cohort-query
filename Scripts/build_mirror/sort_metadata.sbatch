#!/bin/bash
#SBATCH --job-name=just-ask-sort-metadata
#SBATCH --partition=cpu512G-48h
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=12:00:00
#SBATCH --output=/private/pinto-lab/tools/just-ask/logs/sort-metadata-%j.out
#SBATCH --error=/private/pinto-lab/tools/just-ask/logs/sort-metadata-%j.err
#
# Rewrites sra_metadata (39.1M rows, biosample unclustered) into the same table
# sorted by biosample, so a cohort filter prunes row groups instead of touching
# all 319. Never touches the source; writes a new file alongside the mirror.
#
# Submit:  sbatch sort_metadata.sbatch
# Watch:   squeue -u $USER ; tail -f logs/sort-metadata-<jobid>.out

set -euo pipefail

ROOT=/private/pinto-lab/tools/just-ask
MIRROR=$ROOT/mirror/askslm_mirror.duckdb
OUT=$ROOT/mirror/sra_metadata_sorted.duckdb
TMP=$ROOT/duckdb_tmp_sort_metadata
MIN_FREE_GB=200   # output (~46GB) + sort spill (up to 1x) + headroom

echo "=== job $SLURM_JOB_ID on $(hostname) at $(date) ==="
echo "cpus=$SLURM_CPUS_PER_TASK mem=${SLURM_MEM_PER_NODE:-?}"

# --- preflight -------------------------------------------------------------
free_gb=$(df -BG --output=avail "$ROOT" | tail -1 | tr -dc '0-9')
echo "free space on the share: ${free_gb}G (need >= ${MIN_FREE_GB}G)"
if [ "$free_gb" -lt "$MIN_FREE_GB" ]; then
    echo "ABORT: not enough free space. This volume is shared with the whole lab;"
    echo "filling it would break other people's jobs, not just this one."
    exit 1
fi
test -r "$MIRROR" || { echo "ABORT: cannot read $MIRROR"; exit 1; }

mkdir -p "$ROOT/mirror" "$TMP"
trap 'rm -rf "$TMP"' EXIT      # spill files are large; never leave them behind

# --- build + verify ----------------------------------------------------------
time /home/dsi/tamamya/.conda/envs/askslm/bin/python3.12 \
    "$ROOT/scripts/build_sorted_metadata.py" \
    --mirror       "$MIRROR" \
    --out          "$OUT" \
    --threads      "$SLURM_CPUS_PER_TASK" \
    --memory-limit 380GB \
    --temp-dir     "$TMP"

echo "=== result ==="
ls -lh "$OUT"
df -BG --output=avail "$ROOT" | tail -1
echo "=== done at $(date) ==="
echo "NOT cut over automatically. Review the 'row groups touched' lines above first:"
echo "  sorted should be ~1-2 for 64 biosamples, source ~64. If they match, the sort"
echo "  bought nothing and the cutover is not worth doing."
echo "Cutover, once satisfied, is against a WRITABLE copy of the mirror:"
echo "  ATTACH '\$OUT' AS sorted_meta (READ_ONLY);"
echo "  DROP TABLE sra_metadata;"
echo "  CREATE VIEW sra_metadata AS SELECT * FROM sorted_meta.metadata_fact;"
echo "  INSERT INTO mirror_config VALUES ('sra_metadata_path', '\$OUT');"
