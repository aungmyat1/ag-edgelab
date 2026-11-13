#!/usr/bin/env python3
"""Parse an MT5 tester journal for RESEARCH_SIGNAL lines -> signals.csv + summary.json (counts only).
Usage: python parse_signals.py <journal.log> <outdir> [--server-utc-offset-hours H]
Options: --server-utc-offset-hours H (fixed, ignores DST) OR --tz-rule us-ny-close (server = UTC+2 in US winter, UTC+3 in US DST;
  switch happens over the weekend: +3 from the Monday after the 2nd Sunday of March until the Monday after the 1st Sunday of Nov).
Logged time = open of the FORMING bar; signal bar open = logged - 5 min. Logs may be UTF-16 (handled)."""
import re, sys, json, csv, hashlib, pathlib, collections, datetime as dt
src, out = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2]); out.mkdir(parents=True, exist_ok=True)
off = float(sys.argv[sys.argv.index("--server-utc-offset-hours")+1]) if "--server-utc-offset-hours" in sys.argv else None
RULE = "--tz-rule" in sys.argv and sys.argv[sys.argv.index("--tz-rule")+1] == "us-ny-close"
def _nth_sunday(y, m, n):
    d = dt.date(y, m, 1); d += dt.timedelta(days=(6 - d.weekday()) % 7); return d + dt.timedelta(weeks=n-1)
def server_offset(ts):
    if not RULE: return off
    y = ts.year; start = _nth_sunday(y, 3, 2) + dt.timedelta(days=1); end = _nth_sunday(y, 11, 1) + dt.timedelta(days=1)
    return 3.0 if start <= ts.date() < end else 2.0
raw = src.read_bytes()
text = raw.decode("utf-16", "ignore") if raw[:2] in (b"\xff\xfe", b"\xfe\xff") else raw.decode("utf-8", "ignore")
pat = re.compile(r"RESEARCH_SIGNAL,([^,]+),(\d{4}\.\d{2}\.\d{2} \d{2}:\d{2}),(-?1),NO_EDGE_CLAIM")
rows, seen = [], set()
for m in pat.finditer(text):
    sym, ts, d = m.group(1), dt.datetime.strptime(m.group(2), "%Y.%m.%d %H:%M"), int(m.group(3))
    if (sym, ts) in seen: continue
    seen.add((sym, ts)); rows.append((sym, ts, d))
rows.sort(key=lambda r: r[1])
with open(out/"signals.csv", "w", newline="") as f:
    w = csv.writer(f); w.writerow(["symbol","logged_server_time","signal_bar_open_server_time","direction","logged_utc","signal_bar_open_utc"])
    for sym, ts, d in rows:
        o_ = server_offset(ts); u = (ts - dt.timedelta(hours=o_)) if o_ is not None else None
        w.writerow([sym, ts, ts - dt.timedelta(minutes=5), d, u or "", (u - dt.timedelta(minutes=5)) if u else ""])
bars = [r[1] for r in rows]
summary = {
  "label": "SIGNAL_COUNT_DIAGNOSTIC", "ECONOMIC_METRICS": "NOT_ESTIMABLE", "EDGE_CLAIM": "NONE",
  "journal": src.name, "journal_sha256": hashlib.sha256(raw).hexdigest(),
  "total_signals": len(rows), "long": sum(r[2] > 0 for r in rows), "short": sum(r[2] < 0 for r in rows),
  "consecutive_bar_signals": sum((b - a) == dt.timedelta(minutes=5) for a, b in zip(bars, bars[1:])),
  "by_weekday_server": dict(collections.Counter(r[1].strftime("%a") for r in rows)),
  "by_hour_server": dict(sorted(collections.Counter(r[1].hour for r in rows).items())),
  "first": str(bars[0]) if rows else None, "last": str(bars[-1]) if rows else None,
  "orders_blocked_lines": text.count("V2_ORDER_BLOCKED_UNVERIFIED_GATES"),
  "utc_offset_applied_hours": off, "tz_rule": "us-ny-close" if RULE else None,
}
(out/"summary.json").write_text(json.dumps(summary, indent=2)); print(json.dumps(summary, indent=2))
