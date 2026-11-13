# Preregistration — FX_SweepRetest_V2_Research signal-count diagnostic (commit BEFORE run)
- Registered (UTC): <<>>   Registrant: <<>>
- Hypothesis: none about profitability. Diagnostic question only: how many `RESEARCH_SIGNAL` events (long/short) does the frozen V2 proxy emit on EURUSD-VIP M5 over the frozen window, and do they match an offline recomputation from the registered bars?
- Identities: strategy/source/.set/.ex5/INI/manifest/contract hashes (copy from contract).
- Window and partition: DEVELOPMENT 2025-11-13..2026-08-31 (proposed); OOS 2026-09-01..09-30 and SEALED_HOLDOUT 2026-10-01..11-12 unopened. Tester Model=1.
- Primary outputs: total signals; long/short counts; counts by hour and weekday; consecutive-bar signal count; signals per week.
- Parity check (pre-specified): offline recomputation of the same rule from the registered raw bars on a FULL recomputation (tools/parity_check.py) over every signal bar in the window; zero mismatches required, else run flagged INVALID.
- Prohibited: PF, drawdown, expectancy, win rate, any edge/profit statement; parameter changes; re-running after viewing counts without a new preregistration.
- Stop rule: if history quality/completeness fails manifest thresholds (<<OWNER_FILL>>), run is void.
