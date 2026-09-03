#!/bin/bash
#
# Downloads the Metalog inputs build_all.sh needs, straight from Metalog's own
# public downloads page (https://metalog.embl.de/downloads) -- no login, no
# scraping, just the site's direct static files. Lays them out exactly as
# --metalog-dir expects: a "Metadata" and a "Taxonomic Profiles" subdirectory.
#
# Usage: ./fetch_metalog.sh /path/to/Metalog
#
# Metadata files are the "extended wide" tier (core + partially-harmonized
# fields, one row per sample) -- the only variant step3_assemble_mirror.py's
# glob (*_extended_wide_*.tsv.gz) reads. Taxonomic profiles cover the three
# profilers the mirror unions (mOTUs 3.0, MetaPhlAn 4.0 all-levels, SPIRE
# mOTUs); the MetaPhlAn species-only variant is skipped -- nothing reads it.

set -euo pipefail

BASE_URL="https://metalog.embl.de/static/download"
DOMAINS=(human animal ocean environmental)
PROFILES=(motus3 metaphlan4 spire_motus)

[ "$#" -eq 1 ] || { echo "Usage: $0 /path/to/Metalog" >&2; exit 1; }
METALOG_DIR=$1

mkdir -p "$METALOG_DIR/Metadata"
for domain in "${DOMAINS[@]}"; do
    mkdir -p "$METALOG_DIR/Taxonomic Profiles/${domain^}"
done

echo "== Metadata =="
for domain in "${DOMAINS[@]}"; do
    dest="$METALOG_DIR/Metadata/${domain}_extended_wide_$(date +%F).tsv.gz"
    echo "-> $dest"
    curl -fsSL "$BASE_URL/metadata/${domain}_extended_wide_latest.tsv.gz" -o "$dest"
done

echo "== Taxonomic profiles =="
for domain in "${DOMAINS[@]}"; do
    domain_dir="$METALOG_DIR/Taxonomic Profiles/${domain^}"
    for profile in "${PROFILES[@]}"; do
        dest="$domain_dir/${domain}_${profile}_$(date +%F).tsv.gz"
        echo "-> $dest"
        curl -fsSL "$BASE_URL/profiles/${domain}_${profile}_latest.tsv.gz" -o "$dest"
    done
done

echo "Done. $METALOG_DIR is ready for build_all.sh --metalog-dir."
