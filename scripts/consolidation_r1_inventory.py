#!/usr/bin/env python3
"""CONSOLIDATION R1 — remote branch inventory generator.

Produces config/consolidation/branch_inventory.json: one record per remote
branch with topology (HEAD, tree, fork point, ahead/behind vs main), changed
source/test/artifact files vs the fork point, artifact volume, candidate and
dataset identities found in the branch's artifacts/sources, the branch's
reported status, and the consolidation classification.

Read-only with respect to git history: this script never merges, deletes, or
rewrites anything. Re-runnable at any time; identities are recomputed from
the object database, never hand-copied.
"""

from __future__ import annotations

import json
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.fingerprint import sha256_json  # noqa: E402

MAIN = "main"
OUT = ROOT / "config" / "consolidation" / "branch_inventory.json"

# Classification and supersession judgments (CONSOLIDATION R1 decisions —
# see config/consolidation/integration_graph.json for full rationale).
CLASSIFICATION = {
    "main": "CANONICAL",
    "arena/01a1073e-ag-edgelab": "CANONICAL",
    "arena/01a105f9-ag-edgelab": "SUPERSEDED",
    "arena/01a1041d-ag-edgelab": "PARTIALLY_REUSED",
    "arena/01a101e6-ag-edgelab": "PARTIALLY_REUSED",
    "arena/01a1015a-ag-edgelab": "PARTIALLY_REUSED",
    "arena/01a100ce-ag-edgelab": "SUPERSEDED",
    "arena/01a1007a-ag-edgelab": "MERGED",
    "integration/r0-foundation-into-main": "MERGED",
    "feat/r0-foundation": "MERGED",
    "feat/r3-r7-funnel-optimization-production": "MERGED",
    "feat/universal-three-funnel-analyzer-v0-2": "PARTIALLY_REUSED",
    "feat/strategy-verification": "SUPERSEDED",
    "feat/r2-robustness": "PARTIALLY_REUSED",
    "feat/r1-nautilus-adapter": "INDEPENDENT",
    "feat/crypto-btc-economic-verification": "INDEPENDENT",
    "feat/crypto-btc-breakout-candidate": "INDEPENDENT",
    "feat/crypto-btc-h1-candidate": "INDEPENDENT",
    "feat/crypto-btc-spot-candidate": "INDEPENDENT",
    "feat/fx-asian-sweep-candidate": "INDEPENDENT",
    "feat/fx-cycle2-breakout": "INDEPENDENT",
    "feat/fx-edge-candidate": "INDEPENDENT",
    "feat/fx-lny-candidate": "INDEPENDENT",
    "codex/conduct-adversarial-audit-for-pr-#6": "PARTIALLY_REUSED",
}

SUPERSEDED_BY = {
    "arena/01a1073e-ag-edgelab":
        "consolidation PR (canonical universal research line V0.3-V0.6.2)",
    "arena/01a105f9-ag-edgelab":
        "arena/01a1073e-ag-edgelab (tip 8d13235 is an ancestor of 9c94c77)",
    "arena/01a1041d-ag-edgelab":
        "none (merged into consolidation mainline; branch retained as archive)",
    "arena/01a101e6-ag-edgelab":
        "none (merged into consolidation mainline; branch retained as archive)",
    "arena/01a1015a-ag-edgelab":
        "none (merged into consolidation mainline; branch retained as archive)",
    "arena/01a100ce-ag-edgelab":
        "arena/01a1015a-ag-edgelab (merged into it; content also merged to "
        "mainline via consolidation)",
    "feat/universal-three-funnel-analyzer-v0-2":
        "none (merged into consolidation mainline as the strategy-agnostic "
        "funnel diagnostic authority)",
    "feat/strategy-verification":
        "main R8/R8.1 verification authority (PR#6, merged 45a647f); SSC "
        "GEN001 verdicts recorded in candidate ledger",
    "feat/r2-robustness":
        "statistics/performance.py superseded by main (crypto-lane evolution "
        "of the same R2 module); monte_carlo.py unmerged (no canonical "
        "consumer)",
    "feat/r1-nautilus-adapter":
        "none (execution adapter deliberately excluded: consolidation "
        "mandate forbids adding execution capability)",
    "feat/crypto-btc-economic-verification":
        "none (Bybit acquisition code fails the merge contract: no missing-"
        "bar validation, no byte-level provenance/checksums)",
    "feat/crypto-btc-breakout-candidate":
        "none (donor-strategy development screen; archived)",
    "feat/crypto-btc-h1-candidate":
        "none (donor-strategy development screen; archived)",
    "feat/crypto-btc-spot-candidate":
        "none (Binance screen fails the merge contract: no gap validation, "
        "no provenance; archived)",
    "feat/fx-asian-sweep-candidate":
        "none (donor-strategy development screen; archived)",
    "feat/fx-cycle2-breakout":
        "none (donor-strategy development screen; archived)",
    "feat/fx-edge-candidate":
        "none (donor-strategy development screen; SSC GEN001 verdict "
        "recorded in candidate ledger)",
    "feat/fx-lny-candidate":
        "none (donor-strategy development screen; archived)",
    "codex/conduct-adversarial-audit-for-pr-#6":
        "none (blocked-audit record merged into docs/audits/; no findings)",
}

# Reported status per branch (extracted from each branch's own sealed
# artifacts; pointers recorded so nothing here is invented).
REPORTED_STATUS = {
    "main": "R0-R8.1 foundation + PR#9 crypto synthetic lane (ST_CRYPTO_MTF_SMC_V1, synthetic fixture)",
    "arena/01a1073e-ag-edgelab": "V0.6.2 sealed structural OOS COMPLETE: TARGET_POLICY_C3_V1 verdict C STRUCTURAL_GENERALIZATION_FAILS",
    "arena/01a105f9-ag-edgelab": "V0.6 natural target + runner policy research complete (pre-OOS freeze)",
    "arena/01a1041d-ag-edgelab": "direction daily bias lab BLOCKED (BLOCKED_NO_AUTHORIZED_ASIAN_DEV_LINEAGE), DEVELOPMENT_ONLY",
    "arena/01a101e6-ag-edgelab": "MTF_CONTROL_SHIFT_V1 (ST_MTF_CONTROL_SHIFT_V1 1.0.0) COMPLETE, no DEV survivor cells, OOS NOT_RUN, holdout untouched",
    "arena/01a1015a-ag-edgelab": "STV2 strategy funnel analyzer COMPLETE (analysis of SESSION_TRADE_V2 economic matrix)",
    "arena/01a100ce-ag-edgelab": "SESSION_TRADE_V2_v2.0.0 economic campaign COMPLETE: FROZEN_FOR_OOS, OOS_PASS=false, EDGE_VERIFIED=false, BRANCH_A REJECT (fails OOS)",
    "arena/01a1007a-ag-edgelab": "merged via PR#9 (R0 crypto lane mission)",
    "integration/r0-foundation-into-main": "merged via PR#8",
    "feat/r0-foundation": "merged via PR#1",
    "feat/r3-r7-funnel-optimization-production": "merged via PR#6 (R3-R7 + R8/R8.1 verification hardening)",
    "feat/universal-three-funnel-analyzer-v0-2": "tool contract complete (no campaign, no edge authority)",
    "feat/strategy-verification": "FX SSC GEN001 NO_EDGE baseline + crypto sweep retest INSUFFICIENT_EVIDENCE recorded (pre-R8 verification layer)",
    "feat/r2-robustness": "deterministic Monte Carlo + R-based performance metrics (tests green on branch)",
    "feat/r1-nautilus-adapter": "NautilusTrader 2.x lazy adapter boundary + CI smoke (unmerged)",
    "feat/crypto-btc-economic-verification": "Bybit public-archive BTC economic verifier + funding stress (CI-driven; no committed evidence population)",
    "feat/crypto-btc-breakout-candidate": "preregistered BTC breakout development screen (CI)",
    "feat/crypto-btc-h1-candidate": "preregistered H4-H1 BTC development screen (CI)",
    "feat/crypto-btc-spot-candidate": "Binance spot monthly-archive development screen (CI)",
    "feat/fx-asian-sweep-candidate": "preregistered Asian range sweep development screen (CI)",
    "feat/fx-cycle2-breakout": "preregistered cycle2 H4-H1 breakout development screen",
    "feat/fx-edge-candidate": "bounded development-only funnel screen (SSC GEN001 donor strategy)",
    "feat/fx-lny-candidate": "preregistered final LNY development screen (CI)",
    "codex/conduct-adversarial-audit-for-pr-#6": "AUDIT_VERDICT = BLOCKED (re-audit target 7f0b061 absent from checkout)",
}


def git(*args: str) -> str:
    return subprocess.run(["git", *args], cwd=ROOT, check=True,
                          capture_output=True, text=True).stdout


def branch_names() -> list[str]:
    out = git("for-each-ref", "--format=%(refname:short)",
              "refs/remotes/origin")
    return [b for b in out.splitlines()
            if b != "origin/HEAD" and b.startswith("origin/")]


def diff_names(base: str, tip: str) -> list[str]:
    out = git("diff", "--name-only", base, tip)
    return [l for l in out.splitlines() if l]


def artifact_volume(tip: str) -> dict:
    out = git("ls-tree", "-r", "-l", tip)
    total = 0
    files = 0
    for line in out.splitlines():
        if "\t" not in line:
            continue
        left, path = line.split("\t", 1)
        fields = left.split()
        if len(fields) < 4 or not path.startswith(("artifacts/", "data/")):
            continue
        files += 1
        try:
            total += int(fields[3])
        except ValueError:
            pass
    return {"artifact_files": files, "artifact_bytes": total,
            "artifact_mb": round(total / 1048576.0, 2)}


def candidate_ids(tip: str, changed: list[str]) -> list[str]:
    ids: list[str] = []
    patterns = (re.compile(r'CANDIDATE_ID["\s:=]+"([A-Za-z0-9_.@-]+)"'),
                re.compile(r'candidate_id["\s:=]+"([A-Za-z0-9_.@-]+)"'),
                re.compile(r'strategy_id["\s:=]+"([A-Z0-9_]+)"'))
    for path in changed:
        if not (path.startswith(("artifacts/", "data/", "src/", "docs/"))
                and path.endswith((".json", ".py", ".md"))):
            continue
        try:
            text = git("show", f"{tip}:{path}", )
        except subprocess.CalledProcessError:
            continue
        for pat in patterns:
            for m in pat.finditer(text):
                v = m.group(1)
                if v and v not in ids:
                    ids.append(v)
        if len(ids) > 12:
            break
    return sorted(ids)[:12]


def dataset_ids(tip: str, changed: list[str]) -> list[str]:
    found: list[str] = []
    for path in changed:
        if "dataset" not in path and "DATASET" not in path:
            continue
        if not path.endswith(".json"):
            continue
        try:
            text = git("show", f"{tip}:{path}")
        except subprocess.CalledProcessError:
            continue
        m = re.search(r'"dataset_id"["\s:=]+"([A-Za-z0-9_.-]+)"', text)
        if m and m.group(1) not in found:
            found.append(m.group(1))
        for mm in re.finditer(r'"source":\s*"(HISTDATA[^"]+)"', text):
            if mm.group(1) not in found:
                found.append(mm.group(1))
    return sorted(found)[:6]


def main() -> int:
    branches = branch_names()
    main_sha = git("rev-parse", MAIN).strip()
    records = []
    for ref in branches:
        name = ref[len("origin/"):]
        tip = git("rev-parse", ref).strip()
        tree = git("rev-parse", f"{tip}^{{tree}}").strip()
        fork = git("merge-base", MAIN, tip).strip()
        ahead = int(git("rev-list", "--count", f"{fork}..{tip}").strip())
        behind = int(git("rev-list", "--count", f"{tip}..{MAIN}").strip())
        changed = diff_names(fork, tip)
        src = sorted(p for p in changed if p.startswith("src/"))
        tests = sorted(p for p in changed if p.startswith("tests/"))
        scripts = sorted(p for p in changed if p.startswith("scripts/"))
        vol = artifact_volume(tip)
        in_canonical = subprocess.run(
            ["git", "merge-base", "--is-ancestor", tip,
             "origin/arena/01a1073e-ag-edgelab"],
            cwd=ROOT, capture_output=True).returncode == 0
        records.append({
            "name": name,
            "head": tip,
            "tree": tree,
            "fork_point_from_main": fork,
            "commits_ahead_of_fork": ahead,
            "main_commits_behind": behind,
            "tip_ancestor_of_consolidation_branch": in_canonical,
            "changed_source_files": src,
            "changed_test_files": tests,
            "changed_script_files": scripts,
            "changed_files_total": len(changed),
            "artifact_volume": vol,
            "candidate_identities": candidate_ids(tip, changed),
            "dataset_identities": dataset_ids(tip, changed),
            "reported_status": REPORTED_STATUS.get(name, "unknown"),
            "classification": CLASSIFICATION.get(name, "UNCLASSIFIED"),
            "likely_superseded_by": SUPERSEDED_BY.get(name, "none"),
        })
    inventory = {
        "generated_by": "scripts/consolidation_r1_inventory.py",
        "main_at_inventory_time": main_sha,
        "canonical_consolidation_branch":
            "arena/01a1073e-ag-edgelab@9c94c7779aaac6ed84e40be2874d47f296789ce4",
        "branch_count": len(records),
        "branches": sorted(records, key=lambda r: r["name"]),
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(inventory, indent=2, sort_keys=False) + "\n",
                   encoding="utf-8")
    print(f"wrote {OUT} ({len(records)} branches)")
    for r in sorted(records, key=lambda x: x["name"]):
        print(f"  {r['classification']:>16s}  {r['name']} "
              f"(+{r['commits_ahead_of_fork']}/-{r['main_commits_behind']}, "
              f"{r['artifact_volume']['artifact_mb']}MB artifacts)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
