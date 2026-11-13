# PROPOSED_FXSR2_PHASE2_ARTIFACT_REFERENCES

## Conflict

The operational prompt `strategies/FXSR2_AGENT_PROMPT.md` names the addendum files `README.txt` and `mql5/ExportHistory.mq5`. The extracted, hash-verified addendum instead contains `README_ADDENDUM.txt` and `mql5/FX_SweepRetest_ExportHistory.mq5`. Its own `RUN_CHECKLIST.md` names the latter exporter. The files named by the prompt are absent from the extracted package.

The selected exporter is read-only and has the frozen inputs `EURUSD-VIP`, warm-up start `2025.11.01 00:00`, and exclusive end `2026.09.01 00:00`. No script has been copied to the terminal, compiled, or run in this turn.

## Options

1. Owner confirms that the hash-listed `mql5/FX_SweepRetest_ExportHistory.mq5` and `README_ADDENDUM.txt` are the intended package artifacts, and updates the operational prompt references in a later controlled documentation change.
2. Owner supplies the missing files `README.txt` and `mql5/ExportHistory.mq5` with their approved hashes.
3. Keep Phase 2 blocked until the authority of these references is resolved.

## Recommendation

Choose option 1 only after checking the exact exporter hash against `SHA256SUMS_ADDENDUM.txt`. Do not rename or alter the pinned payload, and do not export history until the conflict is resolved.

## Status

OWNER RULING — 2026-11-13: OPTION 1 APPROVED. The hash-listed `mql5/FX_SweepRetest_ExportHistory.mq5` and `README_ADDENDUM.txt` are the intended artifacts. Do not rename or edit these package files. The owner states that the prompt references are byte-identical aliases on the author's side. This ruling authorizes Phase 2 DEV-only work under the existing gate and scope; OOS and SEALED_HOLDOUT remain closed.
