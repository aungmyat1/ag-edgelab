#!/usr/bin/env python3
"""Data completeness check + SHA-256 for the exported M5 bar CSV (feeds DATASET_MANIFEST).
Usage: python check_bars.py bars.csv out_report.json"""
import csv, sys, json, hashlib, pathlib, datetime as dt, collections
p = pathlib.Path(sys.argv[1]); raw = p.read_bytes()
rows = list(csv.DictReader(raw.decode("utf-8", "ignore").splitlines()))
F = "%Y.%m.%d %H:%M"
T = [dt.datetime.strptime(r["time_server_open"], F) for r in rows]
five = dt.timedelta(minutes=5)
dups = len(T) - len(set(T)); nonmono = sum(b <= a for a, b in zip(T, T[1:]))
bad = zero = 0
for r in rows:
    o,h,l,c = (float(r[k]) for k in ("open","high","low","close"))
    if not (l <= min(o,c) and h >= max(o,c) and h >= l): bad += 1
    if h == l: zero += 1
gaps = collections.Counter(); big = []
for a, b in zip(T, T[1:]):
    d = b - a
    if d > five:
        # weekend gap: Fri->Sun/Mon (> 40h) listed separately; intraday gaps are the concern
        if d >= dt.timedelta(hours=40): gaps["weekend_or_holiday_gap_ge_40h"] += 1
        else: gaps["intra_week_gap"] += 1; big.append((str(a), str(b), int(d.total_seconds()//60)-5))
missing_bars = sum(m for _,_,m in big)
wk = collections.defaultdict(list)
for t in T: wk[t.isocalendar()[:2]].append(t)
firsts = collections.Counter(min(v).strftime("%a %H:%M") for v in wk.values()); lasts = collections.Counter(max(v).strftime("%a %H:%M") for v in wk.values())
mf, ml = firsts.most_common(1)[0][0], lasts.most_common(1)[0][0]
odd = sorted([(f"{k[0]}-W{k[1]:02d}", min(v).strftime("%a %H:%M"), max(v).strftime("%a %H:%M")) for k, v in wk.items()
              if min(v).strftime("%a %H:%M") != mf or max(v).strftime("%a %H:%M") != ml])
rep = {"file": p.name, "sha256": hashlib.sha256(raw).hexdigest(), "rows": len(rows),
       "first_bar": str(T[0]), "last_bar": str(T[-1]), "duplicates": dups, "non_monotonic": nonmono,
       "ohlc_invalid": bad, "zero_range_bars": zero, "gap_counts": dict(gaps),
       "intra_week_missing_m5_bars_est": missing_bars, "largest_intra_week_gaps": sorted(big, key=lambda x: -x[2])[:15],
       "weekly_structure": {"modal_first_bar": mf, "modal_last_bar": ml, "weeks": len(wk), "weeks_deviating": odd[:30], "note": "NY-close-aligned servers: modal last bar Fri 23:55, first bar Mon 00:00 in BOTH seasons; deviations around the 2026-03-08 weekend or holidays need explanation"},
       "verdict_hint": "FAIL" if (dups or nonmono or bad) else "REVIEW_GAPS_AGAINST_MANIFEST_THRESHOLDS"}
pathlib.Path(sys.argv[2]).write_text(json.dumps(rep, indent=2)); print(json.dumps(rep, indent=2))
