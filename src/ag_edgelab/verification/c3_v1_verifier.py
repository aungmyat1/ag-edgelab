"""Independent verifier for the TARGET_POLICY_C3_V1 frozen candidate bundle.

This module NEVER imports the candidate builder
(ag_edgelab.universal.candidate_c3_v1): it re-states the frozen facts
independently, re-implements canonical serialization from scratch (hash
PATH B), resolves content-addressed evidence from RAW BYTES (never trusting
object properties), re-validates every accounting identity from the
serialized ledger, and (when bars are supplied) re-derives every trade
outcome with its own bar-scan implementation.

Verdict policy: fail-closed. A bundle is OK only if EVERY check passes.
Any substitution of contract fields, evidence content, ledger rows,
population, dataset role, censoring or collision policy must produce at
least one failing check.
"""

from __future__ import annotations

import hashlib
import json
import math
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Mapping, Sequence

# ---------------------------------------------------------------------------
# Independently re-stated frozen facts (mission-level constants)
# ---------------------------------------------------------------------------

EXPECTED_CANDIDATE_ID = "TARGET_POLICY_C3_V1"
EXPECTED_RESEARCH_HORIZON = 96
EXPECTED_FIRST_OBJECTIVE_PCT = 50
EXPECTED_RUNNER_PCT = 50
EXPECTED_COLLISION_POLICY_ID = "SAME_BAR_STOP_FIRST_FROZEN_V0_3"
EXPECTED_SAME_BAR_COLLISION_POLICY = "STOP_FIRST_FROZEN_V0_3_SINGLE_RULE"
EXPECTED_FIRST_TARGET_POLICY_ID = "FIRST_VALID_CAUSAL_OBJECTIVE_V0_5"
EXPECTED_RUNNER_TARGET_POLICY_ID = "FURTHEST_VALID_CAUSAL_OBJECTIVE_C3_V0_6"
EXPECTED_RUNNER_STOP_POLICY = "R0_ORIGINAL_FROZEN_SL_RETAINED_BY_RUNNER_LEG"
EXPECTED_FRICTION_MODEL_ID = "FX_2017_FRICTION_AUTHORITY_ABSENT_FAIL_CLOSED_V1"
EXPECTED_DATASET_ROLE = "DEVELOPMENT"
EXPECTED_POPULATION_N = 3183
EXPECTED_T1_SUBSET_N = 379
EXPECTED_SYMBOLS = ("EURUSD", "GBPUSD", "USDJPY", "XAUUSD")
EXPECTED_DEV_WINDOW = ("2017-01-01T00:00:00+00:00", "2017-09-01T00:00:00+00:00")
EXPECTED_HORIZON_UNIT = "M15_BARS"
EXPECTED_HORIZON_ANCHOR = "ENTRY_BAR_CLOSE_TIME"
FAIL_CLOSED_FAMILY = "NT05_NEXT_VALID_ORDER_BLOCK"   # CONTRACT_INCOMPLETE

TRADED_STATUSES = ("STOPPED_BEFORE_FIRST", "FIRST_PLUS_RUNNER_TARGET",
                   "FIRST_PLUS_RUNNER_STOP", "FIRST_PLUS_RUNNER_HORIZON",
                   "HORIZON_BEFORE_FIRST")
NOT_APPLICABLE_STATUSES = ("NOT_APPLICABLE_NO_OBJECTIVE",
                           "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE")
CENSORED_STATUS = "RIGHT_CENSORED_DATA_BOUNDARY"

MANIFEST_NAME = "artifact_manifest.json"
CONTRACT_NAME = "canonical_contract.json"
LEDGER_NAME = "dev_resolution_ledger.jsonl"
ACCOUNTING_NAME = "dev_accounting.json"
MANIFEST_COVERED_FILES = (
    "dev_resolution_ledger.jsonl",
    "dev_accounting.json",
    "causality_audit.json",
    "determinism_report.json",
    "parent_reproduction.json",
    "friction_authority.json",
)


# ---------------------------------------------------------------------------
# PATH B — independent canonical serialization (from scratch)
# ---------------------------------------------------------------------------

def canonical_serialize(value: Any) -> str:
    """Canonical JSON: keys sorted (by codepoint), separators ',' ':',
    ensure_ascii escaping, ints exact, floats via repr (shortest round-trip
    float64), no NaN/Infinity. Implemented without json.dumps so that
    agreement with PATH A is a genuine two-path reproduction."""
    if value is None:
        return "null"
    if value is True:
        return "true"
    if value is False:
        return "false"
    if isinstance(value, str):
        return _escape(value)
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        if not math.isfinite(value):
            raise ValueError("non-finite float is not canonicalizable")
        return repr(value)
    if isinstance(value, Mapping):
        items = sorted(value.items(), key=lambda kv: str(kv[0]))
        return "{" + ",".join(
            f"{_escape(str(k))}:{canonical_serialize(v)}" for k, v in items) + "}"
    if isinstance(value, (list, tuple)):
        return "[" + ",".join(canonical_serialize(v) for v in value) + "]"
    raise TypeError(f"unsupported canonical value: {type(value).__name__}")


def _escape(s: str) -> str:
    out = ['"']
    for ch in s:
        if ch == '"':
            out.append('\\"')
        elif ch == "\\":
            out.append("\\\\")
        elif ch == "\n":
            out.append("\\n")
        elif ch == "\r":
            out.append("\\r")
        elif ch == "\t":
            out.append("\\t")
        elif ch == "\b":
            out.append("\\b")
        elif ch == "\f":
            out.append("\\f")
        elif ord(ch) < 0x20:
            out.append(f"\\u{ord(ch):04x}")
        elif ord(ch) > 0x7E:               # ensure_ascii equivalent
            code = ord(ch)
            if code > 0xFFFF:
                code -= 0x10000
                hi = 0xD800 + (code >> 10)
                lo = 0xDC00 + (code & 0x3FF)
                out.append(f"\\u{hi:04x}\\u{lo:04x}")
            else:
                out.append(f"\\u{code:04x}")
        else:
            out.append(ch)
    out.append('"')
    return "".join(out)


def sha256_bytes(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


def canonical_sha256(value: Any) -> str:
    """PATH B hash: sha256 of the UTF-8 encoding of canonical_serialize."""
    return sha256_bytes(canonical_serialize(value).encode("utf-8"))


# ---------------------------------------------------------------------------
# Content-addressed raw-byte store (mission section 9)
# ---------------------------------------------------------------------------

class RawContentStore:
    """Content-addressed store over RAW BYTES.

    insertion:  put(content) -> key, requires key == sha256(content)
    resolution: resolve(key) -> content, RECOMPUTES sha256(content) and
                requires recomputed == key. Object properties are never
                consulted (R8.1-style forgery protection)."""

    def __init__(self) -> None:
        self._records: dict[str, bytes] = {}

    def put(self, content: bytes) -> str:
        if not isinstance(content, (bytes, bytearray)):
            raise TypeError("RawContentStore stores raw bytes only")
        content = bytes(content)
        key = sha256_bytes(content)
        existing = self._records.get(key)
        if existing is not None and existing != content:
            raise ValueError("sha256 collision in content store")
        self._records[key] = content
        return key

    def resolve(self, key: str) -> bytes:
        if not isinstance(key, str) or len(key) != 64 \
                or any(c not in "0123456789abcdef" for c in key):
            raise LookupError(f"invalid content address: {key!r}")
        content = self._records.get(key)
        if content is None:
            raise LookupError(f"unknown evidence hash: {key}")
        if sha256_bytes(content) != key:
            raise LookupError("stored content no longer matches its address")
        return content

    def __contains__(self, key: str) -> bool:
        return key in self._records

    def __len__(self) -> int:
        return len(self._records)


# ---------------------------------------------------------------------------
# Manifest helpers (used by the freeze runner AND the adversarial audit)
# ---------------------------------------------------------------------------

def build_manifest_entries(bundle_dir: Path) -> list[dict]:
    """Ordered manifest entries over the covered evidence set."""
    entries: list[dict] = []
    covered = sorted(
        str(p.relative_to(bundle_dir).as_posix())
        for p in (bundle_dir / "evidence").glob("*.json"))
    for name in MANIFEST_COVERED_FILES:
        covered.append(name)
    for rel in sorted(covered):
        path = bundle_dir / rel
        entries.append({"artifact": rel, "sha256": sha256_bytes(path.read_bytes())})
    return entries


def manifest_hash(entries: Sequence[dict]) -> str:
    return canonical_sha256(list(entries))


def write_manifest(bundle_dir: Path) -> str:
    entries = build_manifest_entries(bundle_dir)
    (bundle_dir / MANIFEST_NAME).write_text(
        canonical_serialize(entries) + "\n", encoding="utf-8")
    return manifest_hash(entries)


# ---------------------------------------------------------------------------
# Independent trade re-derivation (deep verification)
# ---------------------------------------------------------------------------

def _v_hit_stop(bar, bull: bool, stop: float) -> bool:
    return bar.low <= stop if bull else bar.high >= stop


def _v_hit_target(bar, bull: bool, price: float) -> bool:
    return bar.high >= price if bull else bar.low <= price


def derive_trade_outcome(bars: Sequence, *, direction: str, entry_price: float,
                         stop_price: float, first_price: float | None,
                         runner_price: float | None, horizon_bars: int):
    """Independent re-implementation of the frozen candidate semantics.

    Returns (status, first_leg, runner_leg, horizon_close) with
    first_leg/runner_leg = (exit_bar, exit_price, exit_reason, leg_r)."""
    bull = direction == "BULL"
    f = 0.5
    rf = 0.5
    if len(bars) < horizon_bars:
        return (CENSORED_STATUS, (None, None, None, None),
                (None, None, None, None), None)
    window = bars[:horizon_bars]
    horizon_close = window[-1].close
    risk = abs(entry_price - stop_price)

    def sgn(price: float) -> float:
        return (price - entry_price) / risk if bull else (entry_price - price) / risk

    t1 = stop_bar = None
    for t, bar in enumerate(window, start=1):
        if _v_hit_stop(bar, bull, stop_price):
            stop_bar = t
            break
        if first_price is not None and _v_hit_target(bar, bull, first_price):
            t1 = t
            break
    if stop_bar is not None:
        return ("STOPPED_BEFORE_FIRST", (stop_bar, stop_price, "SL", f * -1.0),
                (stop_bar, stop_price, "SL", rf * -1.0), horizon_close)
    if t1 is None:
        hr = sgn(horizon_close)
        return ("HORIZON_BEFORE_FIRST",
                (horizon_bars, horizon_close, "HORIZON_CLOSE", f * hr),
                (horizon_bars, horizon_close, "HORIZON_CLOSE", rf * hr),
                horizon_close)

    first_r = sgn(first_price)
    first_leg = (t1, first_price, "FIRST_OBJECTIVE", f * first_r)

    t2 = stop2 = None
    for t in range(t1, horizon_bars + 1):
        bar = window[t - 1]
        if _v_hit_stop(bar, bull, stop_price):
            stop2 = t
            break
        if runner_price is not None and _v_hit_target(bar, bull, runner_price):
            t2 = t
            break
    if t2 is not None:
        runner_r = sgn(runner_price)
        return ("FIRST_PLUS_RUNNER_TARGET", first_leg,
                (t2, runner_price, "RUNNER_TARGET", rf * runner_r), horizon_close)
    if stop2 is not None:
        return ("FIRST_PLUS_RUNNER_STOP", first_leg,
                (stop2, stop_price, "SL", rf * -1.0), horizon_close)
    hr = sgn(horizon_close)
    return ("FIRST_PLUS_RUNNER_HORIZON", first_leg,
            (horizon_bars, horizon_close, "HORIZON_CLOSE", rf * hr), horizon_close)


# ---------------------------------------------------------------------------
# Accounting validation over raw ledger rows
# ---------------------------------------------------------------------------

def _parse_ts(value: str) -> datetime:
    return datetime.fromisoformat(value)


def validate_ledger_rows(rows: Sequence[dict], contract: dict) -> list[str]:
    """Per-row accounting identities + causality + dataset-role windows."""
    failures: list[str] = []
    horizon = contract["research_horizon"]
    f_pct = contract["first_objective_pct"] / 100.0
    r_pct = contract["runner_pct"] / 100.0
    dev_start = _parse_ts(contract["dataset_partitions"]["DEVELOPMENT"][0])
    dev_end = _parse_ts(contract["dataset_partitions"]["DEVELOPMENT"][1])
    t1_ids: set[str] = set()

    for row in rows:
        rid = row.get("entry_id", "<missing>")
        entry_time = _parse_ts(row["entry_time"])
        if not (dev_start <= entry_time < dev_end):
            failures.append(f"{rid}: entry_time outside DEVELOPMENT window")
        if row.get("dataset_role") not in (None, EXPECTED_DATASET_ROLE):
            failures.append(f"{rid}: row dataset role is not DEVELOPMENT")
        if row.get("is_t1"):
            t1_ids.add(rid)

        # objective causality (future-created target substitution, A1/A6)
        for key in ("first_objective", "runner_objective"):
            obj = row.get(key)
            if obj is not None:
                created = _parse_ts(obj["created_time"])
                if created > entry_time:
                    failures.append(
                        f"{rid}: {key} created_time {obj['created_time']} is "
                        f"AFTER entry_time {row['entry_time']} (future target)")
                if obj.get("family") == FAIL_CLOSED_FAMILY:
                    failures.append(
                        f"{rid}: {key} uses fail-closed family {FAIL_CLOSED_FAMILY}")
        first_obj, runner_obj = row.get("first_objective"), row.get("runner_objective")
        if first_obj is not None and runner_obj is not None:
            if not runner_obj["target_r"] > first_obj["target_r"]:
                failures.append(f"{rid}: runner objective not strictly beyond first")

        status = row.get("status")
        first_leg, runner_leg = row.get("first_leg"), row.get("runner_leg")

        if status in NOT_APPLICABLE_STATUSES:
            if first_leg is not None or runner_leg is not None:
                failures.append(f"{rid}: NOT_APPLICABLE row carries legs")
            if row.get("gross_trade_r") is not None:
                failures.append(f"{rid}: NOT_APPLICABLE row carries gross R")
            if status == "NOT_APPLICABLE_NO_RUNNER_OBJECTIVE" \
                    and first_obj is None:
                failures.append(f"{rid}: no-runner-objective row has no first objective")
            continue
        if status == CENSORED_STATUS:
            if not row.get("censored"):
                failures.append(f"{rid}: censored status without censored flag")
            continue
        if status not in TRADED_STATUSES:
            failures.append(f"{rid}: unknown status {status!r}")
            continue

        # ---- traded rows: full accounting identities
        if first_leg is None or runner_leg is None:
            failures.append(f"{rid}: traded row missing legs")
            continue
        if not math.isclose(first_leg["pct"] + runner_leg["pct"], 1.0,
                            rel_tol=0.0, abs_tol=1e-12):
            failures.append(f"{rid}: first_pct + runner_pct != 1")
        if not math.isclose(first_leg["pct"], f_pct, rel_tol=0.0, abs_tol=1e-12) \
                or not math.isclose(runner_leg["pct"], r_pct, rel_tol=0.0, abs_tol=1e-12):
            failures.append(f"{rid}: leg fractions differ from contract fractions")
        for leg_name, leg in (("first_leg", first_leg), ("runner_leg", runner_leg)):
            bar_t, price, reason, leg_r = (leg["exit_bar"], leg["exit_price"],
                                           leg["exit_reason"], leg["leg_r"])
            if not (isinstance(bar_t, int) and 1 <= bar_t <= horizon):
                failures.append(f"{rid}: {leg_name} exit bar {bar_t} outside 1..{horizon}")
                continue
            expected_r = _leg_r(row, leg["pct"], price)
            if expected_r is None or not math.isclose(leg_r, expected_r,
                                                      rel_tol=0.0, abs_tol=1e-12):
                failures.append(
                    f"{rid}: {leg_name} R {leg_r} != pct*signed_move "
                    f"{expected_r}")
            _check_exit_consistency(failures, rid, leg_name, row, status,
                                    leg, first_obj, runner_obj, horizon)

        # gross identity
        gross = row.get("gross_trade_r")
        if gross is None or not math.isclose(
                gross, first_leg["leg_r"] + runner_leg["leg_r"],
                rel_tol=0.0, abs_tol=1e-12):
            failures.append(f"{rid}: gross_trade_r != first_leg_R + runner_leg_R")

        # ordering: no runner payoff before the first objective
        if runner_leg["exit_reason"] == "RUNNER_TARGET" \
                and runner_leg["exit_bar"] < first_leg["exit_bar"]:
            failures.append(f"{rid}: runner payoff before first objective")

        # no target payoff after SL
        stop_bars = [leg["exit_bar"] for leg in (first_leg, runner_leg)
                     if leg["exit_reason"] == "SL"]
        target_bars = [leg["exit_bar"] for leg in (first_leg, runner_leg)
                       if leg["exit_reason"] in ("FIRST_OBJECTIVE", "RUNNER_TARGET")]
        if stop_bars and target_bars and max(target_bars) > min(stop_bars):
            failures.append(f"{rid}: target payoff after SL")

        # net economics fail closed while friction authority is absent
        if row.get("net_trade_r") is not None:
            failures.append(f"{rid}: net_trade_r claimed without friction authority")

    return failures


def _leg_r(row: dict, pct: float, exit_price: float) -> float | None:
    entry = row["entry_price"]
    stop = row["stop_price"]
    risk = abs(entry - stop)
    if risk <= 0:
        return None
    if row["direction"] == "BULL":
        return pct * ((exit_price - entry) / risk)
    return pct * ((entry - exit_price) / risk)


def _check_exit_consistency(failures, rid, leg_name, row, status, leg,
                            first_obj, runner_obj, horizon) -> None:
    bar_t, price, reason = leg["exit_bar"], leg["exit_price"], leg["exit_reason"]
    stop = row["stop_price"]
    horizon_close = row.get("horizon_close")
    if reason == "SL":
        if not math.isclose(price, stop, rel_tol=0.0, abs_tol=1e-12):
            failures.append(f"{rid}: {leg_name} SL exit price != frozen SL")
    elif reason == "FIRST_OBJECTIVE":
        if first_obj is None or not math.isclose(
                price, first_obj["price"], rel_tol=0.0, abs_tol=1e-12):
            failures.append(f"{rid}: {leg_name} exit price != first objective price")
    elif reason == "RUNNER_TARGET":
        if runner_obj is None or not math.isclose(
                price, runner_obj["price"], rel_tol=0.0, abs_tol=1e-12):
            failures.append(f"{rid}: {leg_name} exit price != runner objective price")
    elif reason == "HORIZON_CLOSE":
        if horizon_close is None or not math.isclose(
                price, horizon_close, rel_tol=0.0, abs_tol=1e-12):
            failures.append(f"{rid}: {leg_name} exit price != horizon close")
        if bar_t != horizon:
            failures.append(f"{rid}: {leg_name} horizon exit bar != research horizon")
    else:
        failures.append(f"{rid}: {leg_name} unknown exit reason {reason!r}")
    # status/leg structure coherence
    if status == "STOPPED_BEFORE_FIRST":
        if leg_name == "first_leg" and reason != "SL":
            failures.append(f"{rid}: STOPPED_BEFORE_FIRST first leg is not SL")
        if leg_name == "runner_leg" and reason != "SL":
            failures.append(f"{rid}: STOPPED_BEFORE_FIRST runner leg is not SL")
    if status == "HORIZON_BEFORE_FIRST" and reason != "HORIZON_CLOSE":
        failures.append(f"{rid}: HORIZON_BEFORE_FIRST leg is not HORIZON_CLOSE")
    if status == "FIRST_PLUS_RUNNER_TARGET" and leg_name == "runner_leg" \
            and reason != "RUNNER_TARGET":
        failures.append(f"{rid}: FIRST_PLUS_RUNNER_TARGET runner leg is not RUNNER_TARGET")
    if status == "FIRST_PLUS_RUNNER_STOP" and leg_name == "runner_leg" \
            and reason != "SL":
        failures.append(f"{rid}: FIRST_PLUS_RUNNER_STOP runner leg is not SL")
    if status == "FIRST_PLUS_RUNNER_HORIZON" and leg_name == "runner_leg" \
            and reason != "HORIZON_CLOSE":
        failures.append(f"{rid}: FIRST_PLUS_RUNNER_HORIZON runner leg is not HORIZON_CLOSE")
    if leg_name == "first_leg" and status.startswith("FIRST_PLUS") \
            and reason != "FIRST_OBJECTIVE":
        failures.append(f"{rid}: first leg did not exit at FIRST_OBJECTIVE")


def recompute_aggregates(rows: Sequence[dict]) -> dict:
    counts: dict[str, int] = {}
    for row in rows:
        counts[row["status"]] = counts.get(row["status"], 0) + 1
    traded = [r for r in rows if r["status"] in TRADED_STATUSES]
    censored_ids = sorted(r["entry_id"] for r in rows
                          if r["status"] == CENSORED_STATUS)
    gross = [r["gross_trade_r"] for r in traded]
    return {
        "population_n": len(rows),
        "t1_subset_n": sum(1 for r in rows if r.get("is_t1")),
        "traded_n": len(traded),
        "not_applicable_n": sum(counts.get(s, 0) for s in NOT_APPLICABLE_STATUSES),
        "censored_n": counts.get(CENSORED_STATUS, 0),
        "censored_entry_ids": censored_ids,
        "status_counts": dict(sorted(counts.items())),
        "gross_r_sum": sum(gross) if gross else 0.0,
        "gross_r_mean": (sum(gross) / len(gross)) if gross else None,
    }


# ---------------------------------------------------------------------------
# Bundle verification
# ---------------------------------------------------------------------------

def verify_bundle(bundle_dir: Path | str, pinned_contract_sha256: str,
                  deep_bars: Mapping[str, Sequence] | None = None) -> dict:
    """Verify a frozen candidate bundle from serialized artifacts only.

    deep_bars: optional {symbol: M15 bars} from the pinned raw dataset; when
    supplied, every traded row is re-derived with this module's own scan."""
    bundle = Path(bundle_dir)
    checks: dict[str, dict] = {}
    failures: list[str] = []

    def record(name: str, ok: bool, detail: str = "",
               info: str = "") -> bool:
        # failure descriptions are stored only for failing checks; passing
        # checks may carry an informational summary instead
        checks[name] = {"passed": bool(ok),
                        "detail": (detail if not ok else info)}
        if not ok:
            failures.append(f"{name}: {detail}" if detail else name)
        return ok

    # ---- 1. contract file hash equals the published pin
    contract_bytes = (bundle / CONTRACT_NAME).read_bytes()
    contract_sha = sha256_bytes(contract_bytes)
    if not record("contract_file_hash", contract_sha == pinned_contract_sha256,
                  f"file {contract_sha[:16]}… vs pinned {pinned_contract_sha256[:16]}…"):
        # The contract is the root; still attempt remaining checks against
        # the (tampered) content so the audit can report more evidence.
        pass
    contract = json.loads(contract_bytes.decode("utf-8"))

    # ---- 2. PATH B canonical serialization reproduces the exact bytes
    path_b = canonical_serialize(contract)
    record("contract_path_b_bytes", path_b.encode("utf-8") == contract_bytes,
           "canonical re-serialization differs from file bytes")
    path_b_hash = sha256_bytes(path_b.encode("utf-8"))
    record("contract_hash_two_paths",
           path_b_hash == contract_sha == pinned_contract_sha256,
           f"path_b {path_b_hash[:16]}… file {contract_sha[:16]}… "
           f"pinned {pinned_contract_sha256[:16]}…")

    # ---- 3. contract re-states the frozen facts
    semantic = []
    if contract.get("candidate_id") != EXPECTED_CANDIDATE_ID:
        semantic.append("candidate_id")
    if contract.get("research_horizon") != EXPECTED_RESEARCH_HORIZON:
        semantic.append("research_horizon")
    if contract.get("horizon_timeframe") != EXPECTED_HORIZON_UNIT:
        semantic.append("horizon_timeframe")
    if contract.get("horizon_anchor") != EXPECTED_HORIZON_ANCHOR:
        semantic.append("horizon_anchor")
    if contract.get("first_objective_pct") != EXPECTED_FIRST_OBJECTIVE_PCT:
        semantic.append("first_objective_pct")
    if contract.get("runner_pct") != EXPECTED_RUNNER_PCT:
        semantic.append("runner_pct")
    if contract.get("same_bar_collision_policy") != EXPECTED_SAME_BAR_COLLISION_POLICY:
        semantic.append("same_bar_collision_policy")
    if contract.get("runner_stop_policy") != EXPECTED_RUNNER_STOP_POLICY:
        semantic.append("runner_stop_policy")
    if contract.get("dataset_role") != EXPECTED_DATASET_ROLE:
        semantic.append("dataset_role")
    if contract.get("population_pinned_entry_n") != EXPECTED_POPULATION_N:
        semantic.append("population_pinned_entry_n")
    if contract.get("oos_opened") is not False or contract.get("holdout_touched") is not False:
        semantic.append("oos/holdout flags")
    record("contract_frozen_facts", not semantic,
           "divergent fields: " + ", ".join(semantic) if semantic else "")

    # ---- 4. content-addressed evidence resolution (raw bytes)
    store = RawContentStore()
    evidence_files = sorted((bundle / "evidence").glob("*.json"))
    for path in evidence_files:
        store.put(path.read_bytes())
    bindings = {
        "trigger_authority_hash": contract.get("trigger_authority_hash"),
        "first_target_policy_hash": contract.get("first_target_policy_hash"),
        "runner_target_policy_hash": contract.get("runner_target_policy_hash"),
        "collision_policy_hash": contract.get("collision_policy_hash"),
        "session_authority_hash": contract.get("session_authority_hash"),
        "friction_model_hash": contract.get("friction_model_hash"),
        "friction_table_hash": contract.get("friction_table_hash"),
        "dataset_role_policy_hash": contract.get("dataset_role_policy_hash"),
        "population_authority_hash": contract.get("population_authority_hash"),
    }
    unresolved = [name for name, key in bindings.items()
                  if not key or key not in store]
    record("evidence_resolution", not unresolved,
           "unresolved content addresses: " + ", ".join(unresolved) if unresolved else "")

    # ---- 5. evidence semantics (independent expectations)
    sem_fail: list[str] = []
    try:
        collision = json.loads(store.resolve(bindings["collision_policy_hash"]))
        if collision.get("collision_policy_id") != EXPECTED_COLLISION_POLICY_ID:
            sem_fail.append("collision_policy_id")
        if "stop" not in collision.get("rule", "").lower() \
                or "first" not in collision.get("rule", "").lower():
            sem_fail.append("collision rule is not stop-first")
        first_tp = json.loads(store.resolve(bindings["first_target_policy_hash"]))
        if first_tp.get("first_target_policy_id") != EXPECTED_FIRST_TARGET_POLICY_ID:
            sem_fail.append("first_target_policy_id")
        runner_tp = json.loads(store.resolve(bindings["runner_target_policy_hash"]))
        if runner_tp.get("runner_target_policy_id") != EXPECTED_RUNNER_TARGET_POLICY_ID:
            sem_fail.append("runner_target_policy_id")
        if "R0" not in runner_tp.get("runner_stop", ""):
            sem_fail.append("runner stop is not R0 original SL")
        friction_model = json.loads(store.resolve(bindings["friction_model_hash"]))
        if friction_model.get("friction_model_id") != EXPECTED_FRICTION_MODEL_ID:
            sem_fail.append("friction_model_id")
        friction_table = json.loads(store.resolve(bindings["friction_table_hash"]))
        for symbol in EXPECTED_SYMBOLS:
            if symbol not in friction_table:
                sem_fail.append(f"friction table missing {symbol}")
        derived_complete = _derive_friction_complete(friction_table)
        if contract.get("friction_authority_complete_derived") != derived_complete:
            sem_fail.append("friction_authority_complete_derived != derived value")
        if derived_complete:
            sem_fail.append("friction authority claimed complete without "
                            "repository-pinned values")
        fam = contract.get("target_family_contracts", {})
        if fam.get(FAIL_CLOSED_FAMILY, {}).get("status") != "TARGET_FAMILY_CONTRACT_INCOMPLETE":
            sem_fail.append("NT05 fail-closed family contract missing/altered")
    except (LookupError, KeyError, json.JSONDecodeError) as exc:
        sem_fail.append(f"evidence unreadable: {exc}")
    record("evidence_semantics", not sem_fail,
           "; ".join(sem_fail) if sem_fail else "")

    # ---- 6. manifest integrity (recompute every covered file hash)
    try:
        manifest = json.loads((bundle / MANIFEST_NAME).read_text(encoding="utf-8"))
        recomputed = build_manifest_entries(bundle)
        listed = {e["artifact"]: e["sha256"] for e in manifest}
        got = {e["artifact"]: e["sha256"] for e in recomputed}
        if listed != got:
            record("manifest_integrity", False,
                   "manifest entries != recomputed file hashes "
                   f"(diff: {sorted(set(listed.items()) ^ set(got.items()))[:4]})")
        else:
            record("manifest_integrity",
                   manifest_hash(recomputed) == contract.get("dev_evidence_manifest_sha256"),
                   "manifest hash != contract binding")
    except (OSError, json.JSONDecodeError) as exc:
        record("manifest_integrity", False, f"manifest unreadable: {exc}")

    # ---- 7. ledger + accounting
    rows = [json.loads(line) for line in
            (bundle / LEDGER_NAME).read_text(encoding="utf-8").splitlines() if line]
    t1_n = sum(1 for r in rows if r.get("is_t1"))
    record("population_identity",
           len(rows) == EXPECTED_POPULATION_N and t1_n == EXPECTED_T1_SUBSET_N,
           f"{len(rows)} rows vs pinned {EXPECTED_POPULATION_N}; T1 subset "
           f"{t1_n} vs pinned {EXPECTED_T1_SUBSET_N}")
    ids = [r.get("entry_id") for r in rows]
    record("unique_entry_ids", len(ids) == len(set(ids)),
           "duplicate entry ids in ledger")
    row_failures = validate_ledger_rows(rows, contract)
    record("row_accounting_and_causality", not row_failures,
           "; ".join(row_failures[:5]) if row_failures else "")

    aggregates = recompute_aggregates(rows)
    unresolved_traded = [
        r["entry_id"] for r in rows
        if r["status"] in TRADED_STATUSES and (
            r.get("first_leg", {}).get("leg_r") is None
            or r.get("runner_leg", {}).get("leg_r") is None
            or r.get("gross_trade_r") is None)]
    record("unresolved_runner_zero",
           not unresolved_traded,
           f"traded rows without complete resolution: {unresolved_traded[:5]}")

    try:
        accounting = json.loads((bundle / ACCOUNTING_NAME).read_text(encoding="utf-8"))
        agg_fail: list[str] = []
        for key in ("population_n", "t1_subset_n", "traded_n",
                    "not_applicable_n", "censored_n", "status_counts",
                    "censored_entry_ids"):
            if accounting.get(key) != aggregates[key]:
                agg_fail.append(f"{key}: {accounting.get(key)!r} != {aggregates[key]!r}")
        if not math.isclose(
                (accounting.get("gross_r_sum") or 0.0), aggregates["gross_r_sum"],
                rel_tol=0.0, abs_tol=1e-9):
            agg_fail.append("gross_r_sum")
        if accounting.get("dataset_role") != EXPECTED_DATASET_ROLE:
            agg_fail.append(f"dataset_role {accounting.get('dataset_role')!r}")
        if accounting.get("unresolved_runner_n") != 0:
            agg_fail.append("unresolved_runner_n != 0")
        record("accounting_aggregates", not agg_fail,
               "; ".join(agg_fail) if agg_fail else "")
    except (OSError, json.JSONDecodeError) as exc:
        record("accounting_aggregates", False, f"dev_accounting unreadable: {exc}")

    # ---- 8. optional deep re-derivation from pinned bars
    if deep_bars is not None:
        deep_fail: list[str] = []
        for row in rows:
            if row["status"] not in TRADED_STATUSES:
                continue
            bars = deep_bars.get(row["symbol"])
            if bars is None:
                deep_fail.append(f"{row['entry_id']}: no bars for symbol")
                continue
            entry_ts = _parse_ts(row["entry_time"]) - timedelta(minutes=15)
            idx = _bar_index(bars, entry_ts)
            if idx is None:
                deep_fail.append(f"{row['entry_id']}: entry bar not found")
                continue
            window = bars[idx + 1: idx + 1 + EXPECTED_RESEARCH_HORIZON]
            status, first_leg, runner_leg, horizon_close = derive_trade_outcome(
                window, direction=row["direction"],
                entry_price=row["entry_price"], stop_price=row["stop_price"],
                first_price=None if row["first_objective"] is None
                else row["first_objective"]["price"],
                runner_price=None if row["runner_objective"] is None
                else row["runner_objective"]["price"],
                horizon_bars=EXPECTED_RESEARCH_HORIZON)
            if status != row["status"]:
                deep_fail.append(f"{row['entry_id']}: status {row['status']} != {status}")
                continue
            if not math.isclose(horizon_close, row["horizon_close"],
                                rel_tol=0.0, abs_tol=1e-12):
                deep_fail.append(f"{row['entry_id']}: horizon close differs")
            for leg_name, got_leg, exp_leg in (
                    ("first", row["first_leg"], first_leg),
                    ("runner", row["runner_leg"], runner_leg)):
                if got_leg["exit_bar"] != exp_leg[0] \
                        or got_leg["exit_reason"] != exp_leg[2] \
                        or not math.isclose(got_leg["exit_price"], exp_leg[1],
                                            rel_tol=0.0, abs_tol=1e-12) \
                        or not math.isclose(got_leg["leg_r"], exp_leg[3],
                                            rel_tol=0.0, abs_tol=1e-12):
                    deep_fail.append(
                        f"{row['entry_id']}: {leg_name} leg {got_leg} != {exp_leg}")
        record("deep_replay_independent", not deep_fail,
               detail="; ".join(deep_fail[:5]) if deep_fail else "",
               info=(f"{sum(1 for r in rows if r['status'] in TRADED_STATUSES)} "
                     "trades re-derived bar-by-bar with the independent "
                     "verifier scan"))

    return {"ok": not failures, "failures": failures, "checks": checks}


def _bar_index(bars: Sequence, timestamp: datetime) -> int | None:
    lo, hi = 0, len(bars) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if bars[mid].timestamp == timestamp:
            return mid
        if bars[mid].timestamp < timestamp:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


def _derive_friction_complete(table: dict) -> bool:
    """Independent derivation of FRICTION_AUTHORITY_COMPLETE from content."""
    for symbol in EXPECTED_SYMBOLS:
        row = table.get(symbol)
        if not isinstance(row, dict):
            return False
        for slot in ("spread", "slippage", "commission"):
            value = row.get(slot)
            if isinstance(value, bool) or not isinstance(value, (int, float)) \
                    or value < 0:
                return False
        for slot in ("entry_treatment", "partial_close_cost",
                     "runner_close_cost", "forced_horizon_close_cost"):
            value = row.get(slot)
            if not isinstance(value, str) or not value \
                    or value in ("UNAVAILABLE_NO_REPOSITORY_AUTHORITY",
                                 "UNPRICED_NO_AUTHORITY"):
                return False
    return True
