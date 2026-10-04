#!/usr/bin/env bash
set -euo pipefail
ROOT="${1:-data/raw/fx_histdata}"
mkdir -p "$ROOT"
declare -A SHA=(
 [EURUSD]=0dcd66dc67d7af4716404a5315d376ee1e7eaebe292afbda3c1003d2dfa16f57
 [GBPUSD]=e5ba3800e37fae0e326dbaa234952ca04e8f378c08b036530a2811206110c10b
 [USDJPY]=477a1f515586f06d67cb75b3662260160e1e29e63c51804a30a5e7d69b09df5f
 [XAUUSD]=a39c1ccaaeb022c83309685107c9e619c2bcff8b2fd94fbd7405a721a4fe70ff
)
for symbol in EURUSD GBPUSD USDJPY XAUUSD; do
  file="HISTDATA_COM_ASCII_${symbol}_M1_2017.zip"
  url="https://raw.githubusercontent.com/parrondo/deeptrading/master/data/raw/${symbol,,}/$file"
  curl --fail --location --retry 3 --output "$ROOT/$file" "$url"
  test "$(sha256sum "$ROOT/$file" | awk '{print $1}')" = "${SHA[$symbol]}"
done
printf 'Pinned HistData archives acquired under %s\n' "$ROOT"
