#!/usr/bin/env python3
"""Offline recomputation of the V2 signal rule from exported bars; compares with the tester's signals.csv.
Usage: python parity_check.py bars.csv signals.csv out.json --from 2025.11.13 --to 2026.08.31 [--lookback 24 --slow 36]
Rule (mirrors EA, indices by bar position, ignoring calendar gaps exactly as CopyRates does):
  signal bar = B[i]; range = B[i-L .. i-1]; long if low<min_low & close>min_low & close>open; else short if high>max_high & close<max_high & close<open.
  Logged time = open time of B[i+1] (the forming bar). Needs CopyRates count >= max(L+5,S+5) -> i >= need-2.
Result PASS only with zero mismatches."""
import csv, sys, json, datetime as dt
a = sys.argv; arg = lambda k, d=None: a[a.index(k)+1] if k in a else d
L = int(arg("--lookback", 24)); S = int(arg("--slow", 36)); need = max(L+5, S+5)
F = "%Y.%m.%d %H:%M"
lo_d = dt.datetime.strptime(arg("--from"), "%Y.%m.%d"); hi_d = dt.datetime.strptime(arg("--to"), "%Y.%m.%d") + dt.timedelta(days=1)
B = [(dt.datetime.strptime(r["time_server_open"], F), float(r["open"]), float(r["high"]), float(r["low"]), float(r["close"]))
     for r in csv.DictReader(open(a[1]))]
exp = {}
for i in range(need-2, len(B)-1):
    t, o, h, l, c = B[i]
    win = B[i-L:i]; hi = max(x[2] for x in win); lo = min(x[3] for x in win)
    d = 1 if (l < lo and c > lo and c > o) else (-1 if (h > hi and c < hi and c < o) else 0)
    if d:
        lt = B[i+1][0]
        if lo_d <= lt < hi_d: exp[lt] = d
got = {}
for r in csv.DictReader(open(a[2])):
    lt = dt.datetime.strptime(r["logged_server_time"], "%Y-%m-%d %H:%M:%S")
    if lo_d <= lt < hi_d: got[lt] = int(r["direction"])
missing = sorted(set(exp) - set(got)); extra = sorted(set(got) - set(exp))
wrong = sorted(t for t in set(exp) & set(got) if exp[t] != got[t])
res = {"expected": len(exp), "tester": len(got), "missing_in_tester": [str(t) for t in missing[:50]], "extra_in_tester": [str(t) for t in extra[:50]],
       "direction_mismatch": [str(t) for t in wrong[:50]], "mismatch_total": len(missing)+len(extra)+len(wrong),
       "verdict": "PASS" if not (missing or extra or wrong) else "FAIL_INVALID_RUN",
       "note": "window-edge signals depend on pre-window history; export must start >=2 days before --from"}
open(a[3], "w").write(json.dumps(res, indent=2)); print(json.dumps(res, indent=2))
