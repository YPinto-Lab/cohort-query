#!/bin/bash

# Usage:
#   ./logan_download.sh ACC1 ACC2 ACC3 ...
#   ./logan_download.sh -f acc_list.txt   # one ACC per line

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_DIR="${OUTPUT_DIR:-$SCRIPT_DIR/output}"
mkdir -p "$OUTPUT_DIR"

LOG_FILE="${OUTPUT_DIR}/logan_download_$(date +%Y%m%d_%H%M%S).log"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

declare -a processed_accs=()
declare -a downloaded_items=()
declare -a skipped_items=()
declare -a missing_items=()

print_summary() {
  echo
  echo "===== SUMMARY ====="
  echo "Log file: $LOG_FILE"
  echo "Total accessions processed: ${#processed_accs[@]}"

  if [ "${#downloaded_items[@]}" -gt 0 ]; then
    echo
    echo "✅ Downloaded:"
    for item in "${downloaded_items[@]}"; do
      echo "  - $item"
    done
  fi

  if [ "${#skipped_items[@]}" -gt 0 ]; then
    echo
    echo "⏭️  Skipped (already existed):"
    for item in "${skipped_items[@]}"; do
      echo "  - $item"
    done
  fi

  if [ "${#missing_items[@]}" -gt 0 ]; then
    echo
    echo "❌ Missing on S3:"
    for item in "${missing_items[@]}"; do
      echo "  - $item"
    done
  fi

  echo "===== END SUMMARY ====="
}

trap print_summary EXIT

download_one_acc() {
  acc="$1"
  echo "Processing $acc ..."
  processed_accs+=("$acc")

  acc_dir="$OUTPUT_DIR/$acc"
  mkdir -p "$acc_dir"
  pushd "$acc_dir" >/dev/null || exit 1

  # --- UNITIGS ---
  if [ -f "${acc}_unitigs.fa" ]; then
    echo "Skipping UNITIGS (already exists)"
    skipped_items+=("$acc UNITIGS")
  else
    echo "Downloading UNITIGS..."
    aws s3 cp "s3://logan-pub/u/$acc/${acc}.unitigs.fa.zst" . --no-sign-request || true
    if [ -f "${acc}.unitigs.fa.zst" ]; then
      echo "Extracting UNITIGS..."
      zstd -d "${acc}.unitigs.fa.zst" -o "${acc}_unitigs.fa"
      rm "${acc}.unitigs.fa.zst"
      downloaded_items+=("$acc UNITIGS")
    else
      echo "❌ UNITIGS not found for $acc"
      missing_items+=("$acc UNITIGS")
    fi
  fi

  # --- CONTIGS ---
  if [ -f "${acc}_contigs.fa" ]; then
    echo "Skipping CONTIGS (already exists)"
    skipped_items+=("$acc CONTIGS")
  else
    echo "Downloading CONTIGS..."
    aws s3 cp "s3://logan-pub/c/$acc/${acc}.contigs.fa.zst" . --no-sign-request || true
    if [ -f "${acc}.contigs.fa.zst" ]; then
      echo "Extracting CONTIGS..."
      zstd -d "${acc}.contigs.fa.zst" -o "${acc}_contigs.fa"
      rm "${acc}.contigs.fa.zst"
      downloaded_items+=("$acc CONTIGS")
    else
      echo "❌ CONTIGS not found for $acc"
      missing_items+=("$acc CONTIGS")
    fi
  fi

  popd >/dev/null

  # delete empty folder if nothing was downloaded
  if [ -z "$(ls -A "$acc_dir")" ]; then
    echo "Deleting empty folder: $acc_dir"
    rmdir "$acc_dir"
  fi

  echo "✅ Done: $acc"
  echo "---------------------------"
}

# --- input handling ---

if [ "$#" -eq 0 ]; then
  echo "Usage:"
  echo "  $0 ACC1 ACC2 ..."
  echo "  $0 -f acc_list.txt"
  exit 1
fi

if [ "$1" = "-f" ]; then
  file="$2"
  while IFS= read -r acc; do
    [ -z "$acc" ] && continue
    download_one_acc "$acc"
  done < "$file"
else
  for acc in "$@"; do
    download_one_acc "$acc"
  done
fi