#!/bin/bash
#SBATCH --job-name=just-ask-mirror
#SBATCH --partition=cpu512G-48h
#SBATCH --cpus-per-task=16
#SBATCH --mem=400G
#SBATCH --time=24:00:00
#SBATCH --output=/private/pinto-lab/tools/just-ask/logs/mirror-%j.out
#SBATCH --error=/private/pinto-lab/tools/just-ask/logs/mirror-%j.err
#
# Builds the askslm mirror on the cluster. CPU, not GPU, and deliberately:
# Anna Shafir's benchmarking (July 2026) found the bottleneck for large STAT
# queries is I/O, not computation -- GPU (cuDF) cut 29 min to 103 s but stayed
# 4x slower than Athena because Parquet file I/O dominated. A build is even more
# I/O-bound than her query, so GPU would accelerate the part that is not the
# problem. What this build does instead is make the expensive scan happen ONCE
# (stat_coverage) so queries never repeat it.
#
# Submit:  sbatch build_mirror.sbatch
# Watch:   squeue -u $USER ; tail -f logs/mirror-<jobid>.out

set -euo pipefail

ROOT=/private/pinto-lab/tools/just-ask
SRA_DB=/private/pinto-lab/STAT/sra_processed.duckdb
OUT=$ROOT/mirror/askslm_mirror.duckdb
TMP=$ROOT/duckdb_tmp
MIN_FREE_GB=150          # abort rather than fill a shared 90%-full volume

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
test -d "$ROOT/Metalog/Metadata" || { echo "ABORT: Metalog not staged at $ROOT/Metalog"; exit 1; }

mkdir -p "$ROOT/mirror" "$TMP"
trap 'rm -rf "$TMP"' EXIT      # spill files are large; never leave them behind

# --- build -----------------------------------------------------------------
time python3 "$ROOT/scripts/build_duckdb.py" \
    --metalog-dir "$ROOT/Metalog" \
    --sra-db      "$SRA_DB" \
    --out         "$OUT" \
    --threads     "$SLURM_CPUS_PER_TASK" \
    --memory-limit 380GB \
    --temp-dir    "$TMP"

echo "=== schema catalog ==="
time python3 "$ROOT/scripts/build_schema_catalog.py" --db "$OUT"

echo "=== result ==="
ls -lh "$OUT"
df -BG --output=avail "$ROOT" | tail -1
echo "=== done at $(date) ==="
