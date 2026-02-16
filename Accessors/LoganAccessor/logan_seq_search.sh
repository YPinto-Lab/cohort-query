#!/bin/bash
# logan_seq_search.sh (no min-length filter)
# Usage:
#   ./logan_seq_search.sh -q query.fa -R ref_root [-o hits.tsv] [-P min_pid] [-t threads]
# Inputs:
#   -q   Query FASTA (nucleotide)
#   -R   Root folder with ACC subfolders containing *_unitigs.fa and/or *_contigs.fa
#   -o   Output TSV (default: hits.tsv)
#   -P   Minimum percent identity (default: 99)
#   -t   Threads for minimap2 (default: 8)
# Requires: minimap2, awk, sort, coreutils

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
OUTPUT_ROOT="${OUTPUT_ROOT:-$SCRIPT_DIR/output}"
mkdir -p "$OUTPUT_ROOT"

RUN_ID="seq_search_$(date +%Y%m%d_%H%M%S)"
RUN_DIR="${OUTPUT_RUN_DIR:-$OUTPUT_ROOT/$RUN_ID}"
mkdir -p "$RUN_DIR"

LOG_FILE="$RUN_DIR/logan_seq_search.log"
touch "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

declare -a summary_msgs=()
add_summary() { summary_msgs+=("$1"); }

print_summary() {
  echo
  echo "===== SUMMARY ====="
  echo "Log file: $LOG_FILE"
  echo "Run directory: $RUN_DIR"
  if [ ${#summary_msgs[@]} -gt 0 ]; then
    for msg in "${summary_msgs[@]}"; do
      echo "- $msg"
    done
  fi
  echo "===== END SUMMARY ====="
}

trap print_summary EXIT

# defaults
QUERY=""
REF_ROOT=""
OUTPUT="hits.tsv"
MIN_PID=99 #the minimum percent identity threshold for reporting hits
THREADS=8

while getopts "q:R:o:P:t:" opt; do
  case $opt in
    q) QUERY="$OPTARG" ;;
    R) REF_ROOT="$OPTARG" ;;
    o) OUTPUT="$OPTARG" ;;
    P) MIN_PID="$OPTARG" ;;
    t) THREADS="$OPTARG" ;;
    *) echo "Usage: $0 -q query.fa -R ref_root [-o hits.tsv] [-P min_pid] [-t threads]" >&2; exit 1 ;;
  esac
done

[[ -z "$QUERY" || -z "$REF_ROOT" ]] && { echo "ERROR: missing -q and/or -R"; exit 1; }
[[ ! -f "$QUERY" ]] && { echo "ERROR: query file not found: $QUERY"; exit 1; }
[[ ! -d "$REF_ROOT" ]] && { echo "ERROR: ref_root directory not found: $REF_ROOT"; exit 1; }

if [[ "$OUTPUT" = /* ]]; then
  mkdir -p "$(dirname "$OUTPUT")"
else
  OUTPUT="$RUN_DIR/$OUTPUT"
  mkdir -p "$(dirname "$OUTPUT")"
fi

add_summary "Query: $QUERY"
add_summary "Reference root: $REF_ROOT"

REF_FA="$REF_ROOT/_logan_all.fa"
REF_IDX="$REF_ROOT/_logan_all.mmi"

# Build combined reference FASTA if missing or outdated
REBUILD=false
if [[ ! -f "$REF_FA" ]]; then
  REBUILD=true
else
  latest_src=$(find "$REF_ROOT" -type f \( -name "*_unitigs.fa" -o -name "*_contigs.fa" \) -print0 | xargs -0 ls -t 2>/dev/null | head -n1 || true)
  if [[ -n "$latest_src" && "$latest_src" -nt "$REF_FA" ]]; then
    REBUILD=true
  fi
fi

if $REBUILD; then
  tmpfa=$(mktemp "$RUN_DIR/refcat.XXXXXX")
  : > "$tmpfa"
  shopt -s nullglob
  while IFS= read -r -d '' f; do
    acc=$(basename "$(dirname "$f")")
    awk -v a="$acc" 'BEGIN{OFS=""} /^>/{print ">", a, "|", substr($0,2); next} {print}' "$f" >> "$tmpfa"
  done < <(find "$REF_ROOT" -type f \( -name "*_unitigs.fa" -o -name "*_contigs.fa" \) -print0 | sort -z)
  mv "$tmpfa" "$REF_FA"
  add_summary "Rebuilt combined FASTA: $REF_FA"
else
  add_summary "Using existing combined FASTA: $REF_FA"
fi

# Build minimap2 index if needed
if [[ ! -f "$REF_IDX" || "$REF_FA" -nt "$REF_IDX" ]]; then
  minimap2 -d "$REF_IDX" "$REF_FA"
  add_summary "Rebuilt minimap2 index: $REF_IDX"
else
  add_summary "Using existing minimap2 index: $REF_IDX"
fi

# Run alignment
PAF=$(mktemp "$RUN_DIR/paf.XXXXXX")
minimap2 -x asm5 -t "$THREADS" -c "$REF_IDX" "$QUERY" > "$PAF"

# Post-process PAF → single TSV (filter by PID only), sorted by PID, query coverage, then aln_len
# PAF cols used: 1 qname,2 qlen,3 qstart,4 qend,5 strand,6 tname,7 tlen,8 tstart,9 tend,10 nmatch,11 alen,12 mapq
echo -e "query\tq_len\tq_start\tq_end\tacc\tassembly_seq\tt_len\tt_start\tt_end\tpid\taln_len\tqcov\tstrand\tmapq" > "$OUTPUT"
awk -v MP="$MIN_PID" 'BEGIN{OFS="\t"}
{
  qname=$1; qlen=$2; qstart=$3; qend=$4; strand=$5;
  tname=$6; tlen=$7; tstart=$8; tend=$9; nmatch=$10; alen=$11; mapq=$12;
  pid  = (alen>0) ? (100.0*nmatch/alen) : 0;
  qcov = (qlen>0) ? (100.0*(qend-qstart)/qlen) : 0;

  if (pid >= MP) {
    acc=tname; asm=tname; sep=index(tname,"|");
    if (sep>0){ acc=substr(tname,1,sep-1); asm=substr(tname,sep+1); }
    printf "%s\t%d\t%d\t%d\t%s\t%s\t%d\t%d\t%d\t%.3f\t%d\t%.3f\t%s\t%d\n",
           qname, qlen, qstart, qend, acc, asm, tlen, tstart, tend, pid, alen, qcov, strand, mapq;
  }
}' "$PAF" \
| sort -t$'\t' -k10,10gr -k12,12gr -k11,11gr >> "$OUTPUT"

rm -f "$PAF"

HITS_COUNT=0
if [[ -f "$OUTPUT" ]]; then
  total_lines=$(wc -l < "$OUTPUT")
  if (( total_lines > 1 )); then
    HITS_COUNT=$((total_lines - 1))
  fi
fi

add_summary "Results file: $OUTPUT"
add_summary "Hits ≥ ${MIN_PID}% PID: $HITS_COUNT"
add_summary "Threads: $THREADS"

echo "Results → $OUTPUT"