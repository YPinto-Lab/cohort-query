#!/bin/bash
#SBATCH --job-name=fetch_sra_raw
#SBATCH --partition=cpu192G-48h
#SBATCH --cpus-per-task=8
#SBATCH --mem=32G
#SBATCH --time=48:00:00
#SBATCH --output=fetch_sra_raw_%j.out
#SBATCH --error=fetch_sra_raw_%j.err
#
# Pulls NCBI's own public SRA metadata and STAT taxonomic-classification
# parquet from AWS Open Data (no AWS account needed -- --no-sign-request),
# then assembles them into the sra_processed.duckdb that build_all.sh's
# --sra-db expects. This is NCBI's full SRA metadata + STAT results, so it's
# large (hundreds of GB) and the sync alone runs for hours; that's inherent
# to the dataset, not something this script can shrink.
#
# Usage:      ./fetch_sra_raw.sh /path/with/space
# Or:         sbatch fetch_sra_raw.sh /path/with/space
#
# Requires the `aws` CLI (no credentials/account needed -- --no-sign-request)
# and Python with duckdb installed.

set -euo pipefail

[ "$#" -eq 1 ] || { echo "Usage: $0 /path/with/space" >&2; exit 1; }
OUT_DIR=$1
PY=${PY:-python3}

mkdir -p "$OUT_DIR/sra_metadata" "$OUT_DIR/sra_tax_analysis"

echo "== syncing sra/metadata =="
aws s3 sync s3://sra-pub-metadata-us-east-1/sra/metadata/ "$OUT_DIR/sra_metadata" \
    --no-sign-request --request-payer requester --region us-east-1

echo "== syncing sra_tax_analysis_tool/tax_analysis =="
aws s3 sync s3://sra-pub-metadata-us-east-1/sra_tax_analysis_tool/tax_analysis/ "$OUT_DIR/sra_tax_analysis" \
    --no-sign-request --request-payer requester --region us-east-1

echo "== assembling sra_processed.duckdb =="
"$PY" -c "
import duckdb

con = duckdb.connect('$OUT_DIR/sra_processed.duckdb')
con.sql(\"CREATE OR REPLACE TABLE tax_raw AS SELECT * FROM read_parquet('$OUT_DIR/sra_tax_analysis/*')\")
con.sql(\"CREATE OR REPLACE TABLE metadata_raw AS SELECT * FROM read_parquet('$OUT_DIR/sra_metadata/*')\")
con.close()
"

echo "Done: $OUT_DIR/sra_processed.duckdb is ready for build_all.sh --sra-db."
