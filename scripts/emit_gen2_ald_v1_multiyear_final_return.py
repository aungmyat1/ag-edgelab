#!/usr/bin/env python
"""Emit the mission FINAL RETURN block from the committed evidence.

Separate from the replay on purpose. Re-running the replay today would re-read
``candidate_contamination_registry.json`` *after* this experiment appended its
own 17 DEVELOPMENT_KNOWN records, which would silently relabel the
preregistered FRESH_DEVELOPMENT windows. The evidence is sealed, so the FINAL
RETURN is projected from it instead: every value is copied, none recomputed.

Rewrites ``final_return.json`` and refreshes ``artifact_manifest.json`` so the
manifest keeps covering every file in the bundle.
"""
from __future__ import annotations

import json
from pathlib import Path

from ag_edgelab.data.fingerprint import sha256_file
from ag_edgelab.strategies.asian_liquidity_displacement_multiyear_analysis import (
    FINAL_RETURN_FIELDS,
    final_return_block,
)

ART = Path("data/artifacts/gen2_asian_liquidity_displacement_v1_multiyear")


def main() -> None:
    final = json.loads((ART / "final_report.json").read_text())
    comparison = json.loads((ART / "v1_narrow_vs_multiyear.json").read_text())
    block = final_return_block(final, comparison)

    payload = {
        "contract": "GEN2_ALD_V1_MULTIYEAR_DEV_FINAL_RETURN_V1",
        "experiment_id": final["EXPERIMENT_ID"],
        "derived_from": {
            name: sha256_file(ART / name)
            for name in ("final_report.json", "v1_narrow_vs_multiyear.json")},
        "derivation": ("every field is copied from the artifacts above by "
                       "asian_liquidity_displacement_multiyear_analysis.final_return_block; "
                       "no value is recomputed, rounded or retyped here"),
        "FINAL_RETURN": block,
    }
    (ART / "final_return.json").write_text(
        json.dumps(payload, indent=2, sort_keys=False) + "\n", encoding="utf-8")

    manifest_path = ART / "artifact_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["files"] = {
        p.name: {"sha256": sha256_file(p), "bytes": p.stat().st_size}
        for p in sorted(ART.iterdir())
        if p.is_file() and p.name != "artifact_manifest.json"}
    manifest["final_return_contract"] = "final_return.json"
    manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")

    print(json.dumps(block, indent=2))
    print(f"\n{len(FINAL_RETURN_FIELDS)} contract fields emitted; "
          f"manifest now covers {len(manifest['files'])} files")


if __name__ == "__main__":
    main()
