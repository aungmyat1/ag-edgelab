FX_SweepRetest_V2_Research — MT5 BACKTEST READINESS ADDENDUM (documentation + templates only)

Purpose: additive files that define the minimum requirements for an MT5 Strategy Tester
SIGNAL-COUNT diagnostic of FX_SweepRetest_V2_Research. NOTHING in the original package is modified.
V2 identity preserved: Experts/FX_SweepRetest_Research.mq5 SHA-256 be1695b3...39b1 (verify with tools/verify_package.py).

Status: NOT READY. No dataset is registered, no window is authorized, no compile or tester run has occurred.
All templates carry placeholders (<<OWNER_FILL>>) and the INI is deliberately unrunnable until filled.

Scope this addendum supports : SIGNAL_ONLY (EA prints RESEARCH_SIGNAL then returns; no orders exist).
Scope it does NOT support    : trade backtest, PF/DD/expectancy, economic claims. Those need a separately
                               versioned EA successor (see REQUIREMENTS.md section 6).

See DECISIONS_PROPOSED.md for the adopted (proposed) window, partitions and tester model.
Workflow: export history (mql5/) -> check_bars.py -> fill manifest/contract -> owner sign-off -> compile -> tester (INI template) -> parse_signals.py -> parity_check.py.
Self-tests of the python tools were run on synthetic data only; the .mq5 export script has NOT been compiled.

PATH LENGTH (Windows 260-char limit): this package uses short names on purpose. Extract it to a SHORT folder such as C:\mt5\
(not inside ...\MetaQuotes\Terminal\<hash>\...). If you use "Extract All", the zip name is repeated as a folder (C:\mt5\FXSR2_BT\FXSR2_BT\...), still short enough.
Optional: enable Win32 long paths (LongPathsEnabled=1 under HKLM\SYSTEM\CurrentControlSet\Control\FileSystem, then reboot); some tools still ignore it.
