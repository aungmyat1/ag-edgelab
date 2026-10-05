#!/usr/bin/env python
"""MISSION 3B-A PHASE 11 — the single V2.1 replay command.

PREPARED BUT NOT EXECUTED. Invoking it today terminates at the data
authorization gate, because the four CONTRACT_AMBIGUITIES recorded by the
engine have not been resolved by the contract owner and a SYNTHETIC policy is
refused against a real partition.

    python scripts/run_gen2_ald_v2_1_replay.py --execute-frozen-v2-1

Order of operations (every step fails closed):
  1 identity          2 preregistration      3 contract hash
  4 dataset binding   5 data authorization   6 refuse if unauthorized
  7 execute once      8 immutable ledger     9 funnel
 10 robustness       11 final_return.json
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime, timezone
from pathlib import Path

from ag_edgelab.governance import v2_1_data_authorization as GATE
from ag_edgelab.strategies import asian_liquidity_displacement_v2_1 as V
from ag_edgelab.strategies import asian_liquidity_displacement_v2_1_prereg as P
from ag_edgelab.strategies import v2_1_engine as E
from ag_edgelab.strategies import v2_1_funnel as F

OUT = Path("data/artifacts/gen2_ald_v2_1")
PREREG = OUT / "preregistration.json"

EXPECTED = {
    "contract": "2c5cfa8c1608cbed20d66606292bb90c6049310665afc59ee5079ce86bbb86d9",
    "preregistration": "3dac1c0c3bcf9cf3404218690e0caf6681be57a5c596f93adb144392dea669ba",
    "dataset_binding": "d030952440d2cfa34f541fff7cdfbf344fdc4959d0ee3826ba349636d566b483",
}


def verify_identity() -> dict:
    """Steps 1-4. Returns a report; `ok` False means stop."""
    checks = {
        "contract_hash_matches_preregistration":
            V.contract_hash() == EXPECTED["contract"],
        "preregistration_hash_matches":
            P.preregistration_hash() == EXPECTED["preregistration"],
        "dataset_binding_hash_matches":
            P.dataset_binding_hash() == EXPECTED["dataset_binding"],
        "preregistration_artifact_present": PREREG.exists(),
        "identity_not_a_forbidden_reuse":
            V.STRATEGY_ID not in V.FORBIDDEN_IDENTITY_REUSE,
        "edge_not_claimed": V.EDGE_VERIFIED is False,
        "economic_edge_not_estimable": V.ECONOMIC_EDGE == "NOT_ESTIMABLE",
        "exactly_two_branches": len(list(V.Branch)) == 2,
    }
    return {"ok": all(checks.values()), "checks": checks,
            "contract_hash": V.contract_hash(),
            "preregistration_hash": P.preregistration_hash(),
            "dataset_binding_hash": P.dataset_binding_hash()}


def build_request(policy_provenance: str) -> GATE.DataRequest:
    binding = P.dataset_binding()
    years = tuple(binding["dev_years"])
    symbols = tuple(binding["symbol_universe"])
    pairs = tuple((s, y) for s in symbols for y in years)
    return GATE.DataRequest(
        symbols=symbols,
        symbol_years=pairs,
        date_range=(f"{min(years)}-01-01", f"{max(years)}-09-01"),
        role="DEVELOPMENT",
        contract_hash=V.contract_hash(),
        preregistration_hash=P.preregistration_hash(),
        dataset_binding_hash=P.dataset_binding_hash(),
        policy_provenance=policy_provenance,
    )


def load_owner_policy() -> E.ReplayPolicy | None:
    """The owner-resolved policy module, once the ambiguities are answered.

    It does not exist yet, and this function must NOT invent one.
    """
    try:
        from ag_edgelab.strategies import v2_1_owner_policy  # type: ignore
    except ImportError:
        return None
    return v2_1_owner_policy.POLICY


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--execute-frozen-v2-1", action="store_true",
                    help="actually run the replay (requires owner-resolved policy)")
    ap.add_argument("--dry-run", action="store_true",
                    help="report readiness without touching any dataset")
    args = ap.parse_args()

    report: dict = {
        "command": "run_gen2_ald_v2_1_replay",
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "REAL_HISTORICAL_REPLAY_EXECUTED": "NO",
    }

    # ---- steps 1-4 ------------------------------------------------------
    identity = verify_identity()
    report["identity"] = identity
    if not identity["ok"]:
        report["STATUS"] = "BLOCKED_IDENTITY_MISMATCH"
        print(json.dumps(report, indent=2))
        return 2

    # ---- the contract must be unambiguous before a policy can exist -----
    policy = load_owner_policy()
    report["CONTRACT_AMBIGUITIES"] = [a["id"] for a in E.CONTRACT_AMBIGUITIES]
    if policy is None:
        report["STATUS"] = "BLOCKED_CONTRACT_AMBIGUITY"
        report["reason"] = (
            "No owner-resolved replay policy exists. The engine will not "
            "choose a reading for the unfrozen contract decisions "
            f"{[a['id'] for a in E.CONTRACT_AMBIGUITIES]}."
        )
        report["ambiguities"] = list(E.CONTRACT_AMBIGUITIES)
        print(json.dumps(report, indent=2))
        return 3

    # ---- step 5-6: authorization ---------------------------------------
    request = build_request(policy.provenance)
    # NOTE: the real governance state is assembled by the caller from the
    # registries. Reaching this line requires an owner-resolved policy, which
    # does not exist during the preparation mission.
    report["STATUS"] = "BLOCKED_GOVERNANCE_STATE_NOT_SUPPLIED"
    report["reason"] = (
        "Authorization requires the real registry state. Mission 3B-A "
        "forbids assembling it, because doing so may record a dataset access."
    )
    report["request"] = {"symbol_years_n": len(request.symbol_years),
                         "date_range": list(request.date_range)}
    if args.dry_run or not getattr(args, "execute_frozen_v2_1", False):
        print(json.dumps(report, indent=2))
        return 0
    print(json.dumps(report, indent=2))
    return 4


if __name__ == "__main__":
    raise SystemExit(main())
