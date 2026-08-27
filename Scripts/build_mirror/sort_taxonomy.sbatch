#!/bin/bash
#SBATCH --job-name=just-ask-sort-taxonomy
#SBATCH --partition=cpu512G-48h
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=48:00:00
#SBATCH --output=/private/pinto-lab/tools/just-ask/logs/sort-taxonomy-%j.out
#SBATCH --error=/private/pinto-lab/tools/just-ask/logs/sort-taxonomy-%j.err
#
# Rewrites tax_raw (13.6B rows, no index, acc unclustered) into a narrow table
# sorted by acc, on cpu512G-48h. Never touches the source. See
# Docs/superpowers/plans/2026-08-18-taxonomy-sort.html for the full plan,
# including the fallback (bucketed sort) if this blows the wall clock.
#
# Submit:  sbatch sort_taxonomy.sbatch
# Watch:   squeue -u $USER ; tail -f logs/sort-taxonomy-<jobid>.out

set -euo pipefail

ROOT=/private/pinto-lab/tools/just-ask
SRA_DB=/private/pinto-lab/STAT/sra_processed.duckdb
OUT=$ROOT/mirror/sra_taxonomy_sorted.duckdb
TMP=$ROOT/duckdb_tmp_sort
MIN_FREE_GB=400   # output (~100-200GB, estimate) + sort spill (up to 1x) + headroom

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
test -r "$SRA_DB" || { echo "ABORT: cannot read $SRA_DB"; exit 1; }

mkdir -p "$ROOT/mirror" "$TMP"
trap 'rm -rf "$TMP"' EXIT      # spill files are large; never leave them behind

# --- build + verify ----------------------------------------------------------
time python3 "$ROOT/scripts/build_sorted_taxonomy.py" \
    --sra-db      "$SRA_DB" \
    --out         "$OUT" \
    --threads     "$SLURM_CPUS_PER_TASK" \
    --memory-limit 380GB \
    --temp-dir    "$TMP"

echo "=== result ==="
ls -lh "$OUT"
df -BG --output=avail "$ROOT" | tail -1
echo "=== done at $(date) ==="
echo "NOT cut over automatically -- cutover is the two mirror_config statements"
echo "in section 8 of the plan, run by hand after reviewing this job's output."
