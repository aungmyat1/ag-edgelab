#!/usr/bin/env bash
# ST_CRYPTO_MTF_SMC_V1 R0 — real-data acquisition bootstrap (network-enabled hosts ONLY).
#
# This sandbox session could NOT execute this script: egress to
# data.binance.vision / api.bybit.com is blocked here, and no authoritative
# exchange-origin dataset ships inside the repository (verified: no crypto
# OHLCV files on any branch, PR ref, or donor repo). That is exactly why the
# dev run uses the deterministic SYNTHETIC fixture.
#
# Usage (on a host with network access):
#   bash scripts/acquire_btcusdt_perp_m5.sh START_YYYYMM END_YYYYMM OUT_DIR
# Example:
#   bash scripts/acquire_btcusdt_perp_m5.sh 2024-06 2025-05 data/artifacts/btcusdt_perp_real
#
# It downloads Binance USDⓈ-M futures BTCUSDT 5m kline monthly bulk zips
# (public, first-party exchange data), verifies zip integrity, concatenates
# and SHA-256 pins the canonical CSV, then prints the manifest lines needed
# for the dataset manifest. The dev runner accepts the resulting CSV via
# --bars; quality gates, TF derivation, strategy, replay, and analysis are
# IDENTICAL to the synthetic fixture lane — swap capability by design.
set -euo pipefail

START="${1:?start YYYYMM}"
END="${2:?end YYYYMM}"
OUT="${3:?out dir}"
SYMBOL="BTCUSDT"
INTERVAL="5m"
BASE_URL="https://data.binance.vision/data/futures/um/monthly/klines/${SYMBOL}/${INTERVAL}"

mkdir -p "${OUT}/raw_zips" "${OUT}/csv_monthly"

ym="${START}"
while true; do
  zip="${OUT}/raw_zips/${SYMBOL}-${INTERVAL}-${ym}.zip"
  csv="${OUT}/csv_monthly/${SYMBOL}-${INTERVAL}-${ym}.csv"
  url="${BASE_URL}/${SYMBOL}-${INTERVAL}-${ym}.zip"
  echo "fetch ${url}"
  curl -fSL --retry 3 --retry-delay 5 -o "${zip}" "${url}"
  # Verify zip integrity BEFORE trusting content.
  python3 - "$zip" <<'PY'
import sys, zipfile
z = zipfile.ZipFile(sys.argv[1])
bad = z.testzip()
if bad is not None:
    raise SystemExit(f"corrupt member: {bad}")
Z = True
PY
  unzip -o -q "${zip}" -d "${OUT}/csv_monthly/"
  ym=$(python3 - "$ym" <<'PY'
import sys
y, m = int(sys.argv[1][:4]), int(sys.argv[1][4:6])
m += 1
if m == 13:
    y, m = y + 1, 1
print(f"{y:04d}{m:02d}")
PY
)
  [ "${ym}" \> "${END}" ] && break
done

CANON="${OUT}/${SYMBOL}_${INTERVAL}_${START}_${END}.csv"
{
  echo "timestamp,open,high,low,close,volume"
  for f in "${OUT}"/csv_monthly/${SYMBOL}-${INTERVAL}-*.csv; do
    # Binance kline columns: open_time,open,high,low,close,volume,close_time,...
    # Convert ms-epoch open_time to RFC3339 UTC; keep first 6 columns only.
    # Any row whose open_time column contains non-digits (header) is dropped.
    awk -F, 'NR==FNR || $1 ~ /^[0-9]+$/ {
      if ($1 ~ /^[0-9]+$/) {
        ts = strftime("%Y-%m-%dT%H:%M:%S+00:00", $1/1000, 1)
        print ts "," $2 "," $3 "," $4 "," $5 "," $6
      }
    }' "$f" "$f"
  done
} > "${CANON}"

SHA=$(sha256sum "${CANON}" | cut -d' ' -f1)
ROWS=$(($(wc -l < "${CANON}") - 1))
FIRST=$(sed -n '2p' "${CANON}" | cut -d, -f1)
LAST=$(tail -1 "${CANON}" | cut -d, -f1)

cat <<JSON
DATASET_ID: ${SYMBOL}_PERP_${INTERVAL}_${START}_${END}
PATH: ${CANON}
SHA: ${SHA}
SYMBOL: ${SYMBOL}
VENUE: BINANCE_USDM_FUTURES
TIMEFRAME: M5
START: ${FIRST}
END: ${LAST}
ROWS: ${ROWS}
SHA256: ${SHA}
SEALED: true
PROVENANCE: first-party exchange bulk klines from $BASE_URL (monthly zips integrity-checked)
GAP_AUDIT: run data quality gate (scripts/run_st_crypto_mtf_smc_dev.py prints it via audit_bars)
USABLE_FOR_DEV: true
JSON

echo "next: PYTHONPATH=src .venv/bin/python scripts/run_st_crypto_mtf_smc_dev.py --bars ${CANON}"
