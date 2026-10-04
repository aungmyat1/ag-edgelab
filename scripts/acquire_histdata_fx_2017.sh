#!/usr/bin/env bash
# Acquire the four pinned HistData ASCII M1 2017 archives (EURUSD, GBPUSD,
# USDJPY, XAUUSD) and verify their sha256 against the identities frozen by
# the SESSION_TRADE_V2 campaign (PR #10). Zips are NOT committed to git.
#
# Usage: scripts/acquire_histdata_fx_2017.sh [dest_dir]
#   dest_dir defaults to data/external/histdata_fx_2017
#
# NOTE: raw.githubusercontent.com may be unreachable in sandboxes; the
# GitHub contents API with "Accept: application/vnd.github.raw" works.
set -euo pipefail

DEST="${1:-data/external/histdata_fx_2017}"
mkdir -p "$DEST"

declare -A SHA=(
  [EURUSD]=0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57
  [GBPUSD]=e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b
  [USDJPY]=477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f
  [XAUUSD]=a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff
)

for SYM in EURUSD GBPUSD USDJPY XAUUSD; do
  sym=$(echo "$SYM" | tr '[:upper:]' '[:lower:]')
  FILE="$DEST/HISTDATA_COM_ASCII_${SYM}_M1_2017.zip"
  if [[ ! -s "$FILE" ]]; then
    echo "downloading $SYM ..."
    gh api "repos/parrondo/deeptrading/contents/data/raw/${sym}/HISTDATA_COM_ASCII_${SYM}_M1_2017.zip" \
      -H "Accept: application/vnd.github.raw" > "$FILE"
  fi
  GOT=$(sha256sum "$FILE" | cut -d' ' -f1)
  if [[ "$GOT" != "${SHA[$SYM]}" ]]; then
    echo "BLOCKED_DATA_AUTHORITY: $SYM sha256 mismatch" >&2
    echo "  expected ${SHA[$SYM]}" >&2
    echo "  got      $GOT" >&2
    exit 2
  fi
  echo "verified $SYM $GOT"
done
echo "DATASET_HASHES_VERIFIED=YES"
