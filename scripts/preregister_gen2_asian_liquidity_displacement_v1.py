#!/usr/bin/env python
"""Emit the GENERATION 2 preregistration + strategy contract.

Run and COMMIT this BEFORE any DEVELOPMENT replay produces a result.
No dataset is opened by this script.
"""
from __future__ import annotations

import json
import subprocess
from pathlib import Path

from ag_edgelab.data.fingerprint import canonical_json
from ag_edgelab.strategies.asian_liquidity_displacement_prereg import preregistration
from ag_edgelab.strategies.asian_liquidity_displacement_v1 import (
    contract_hashes,
    strategy_contract,
)

OUT = Path("data/artifacts/gen2_asian_liquidity_displacement_v1")


def _git(*args: str) -> str:
    return subprocess.run(["git", *args], capture_output=True, text=True, check=True).stdout.strip()


def write_json(path: Path, payload: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def main() -> None:
    head = _git("rev-parse", "HEAD")
    contract = strategy_contract()
    contract["contract_hashes"] = contract_hashes()
    doc = preregistration(implementation_sha=head, base_commit=head)
    write_json(OUT / "strategy_contract.json", contract)
    write_json(OUT / "preregistration.json", doc)
    print("PREREGISTRATION_HASH =", doc["preregistration_hash"])
    print("STRATEGY_HASH        =", contract["contract_hashes"]["strategy_contract_hash"])
    print("CODE_HASH            =", contract["contract_hashes"]["strategy_code_hash"])
    print("canonical bytes      =", len(canonical_json(doc)))


if __name__ == "__main__":
    main()
