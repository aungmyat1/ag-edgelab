#!/usr/bin/env bash
# Acquire the pinned multi-year Dukascopy FX tick archives (EURUSD, GBPUSD,
# USDJPY, XAUUSD; 2011-2018) from the FX-Data GitHub mirror.
#
# Every (symbol, year) is fetched at an IMMUTABLE COMMIT SHA taken from
# config/data_authority/dukascopy_fx31337_pins.json — never at a branch
# name, because branches move.
#
# Raw archives are NOT committed to git. They are written under
# data/external/dukascopy_fx/ (gitignored) and their identity is recorded by
# scripts/build_fx_data_authority.py as a Merkle root over the extracted CSV
# member contents (tar/gzip framing is not byte-stable, member content is).
#
# Usage: scripts/acquire_dukascopy_fx_multiyear.sh [dest_dir] [parallel]
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DEST="${1:-$ROOT/data/external/dukascopy_fx}"
PAR="${2:-4}"
PINS="$ROOT/config/data_authority/dukascopy_fx31337_pins.json"

mkdir -p "$DEST"
command -v gh >/dev/null || { echo "BLOCKED_ACQUISITION: gh CLI required" >&2; exit 2; }
TOKEN="$(gh auth token)"

fetch_one() {
  local repo="$1" commit="$2" symbol="$3" year="$4" dest="$5" token="$6"
  local out="$dest/${symbol}_${year}_${commit:0:12}.tar.gz"
  if [[ -s "$out" ]]; then echo "cached   $symbol $year"; return 0; fi
  local tmp="$out.part"
  if ! curl -fsSL -H "Authorization: token $token" \
       -o "$tmp" "https://api.github.com/repos/$repo/tarball/$commit"; then
    echo "BLOCKED_ACQUISITION: $symbol $year download failed" >&2
    rm -f "$tmp"; return 1
  fi
  # Structural check: the archive must contain the expected symbol/year path.
  if ! tar -tzf "$tmp" | grep -q "/${symbol}/${year}/"; then
    echo "BLOCKED_ACQUISITION: $symbol $year archive lacks ${symbol}/${year}/ members" >&2
    rm -f "$tmp"; return 1
  fi
  mv "$tmp" "$out"
  echo "fetched  $symbol $year $(stat -c%s "$out") bytes"
}
export -f fetch_one

python3 - "$PINS" <<'PY' > "$DEST/.joblist"
import json, sys
pins = json.load(open(sys.argv[1]))["pins"]
for p in pins:
    print(f'{p["repo"]} {p["commit"]} {p["symbol"]} {p["year"]}')
PY

xargs -a "$DEST/.joblist" -P "$PAR" -L1 bash -c \
  'fetch_one "$0" "$1" "$2" "$3" "'"$DEST"'" "'"$TOKEN"'"'

echo "DUKASCOPY_FX_ACQUISITION_COMPLETE dest=$DEST"
