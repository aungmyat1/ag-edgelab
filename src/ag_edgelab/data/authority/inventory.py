"""Source inventory and the authority decision matrix.

DATA_AUTHORITY_R1 section 2 requires that every candidate source be
described against the SAME fields and that long history alone never earn
selection. This module holds the records produced by the R1 investigation.

Each record carries an ``authority_status``:

``CERTIFIED``   provenance pinned, timezone PROVEN from the data, hashes
                reproducible, quality classified. Usable as evidence.
``REJECTED``    investigated and failed a contract. The reason is recorded
                with the measurement that produced it, so the rejection can
                be re-tested rather than re-argued.
``UNAVAILABLE`` not reachable from this environment. Not a judgement about
                the source, a statement about the sandbox.
``REFERENCE``   present and trusted, but out of scope for new derivation
                (e.g. the frozen 2017 authority, which must not change).
"""

from __future__ import annotations

from dataclasses import dataclass, field

CERTIFIED = "CERTIFIED"
REJECTED = "REJECTED"
UNAVAILABLE = "UNAVAILABLE"
REFERENCE = "REFERENCE"

INVENTORY_FIELDS: tuple[str, ...] = (
    "SOURCE_ID", "VENUE_PROVIDER", "SYMBOLS", "TIMEFRAMES", "START", "END",
    "TIMEZONE", "RAW_FORMAT", "DOWNLOAD_METHOD", "LICENSE_ACCESS",
    "MISSING_BAR_BEHAVIOR", "DUPLICATE_BEHAVIOR", "DST_SESSION_TIME_BEHAVIOR",
    "BID_ASK_AVAILABILITY", "VOLUME_TYPE", "REPRODUCIBILITY",
    "SHA256_CAPABILITY", "KNOWN_LIMITATIONS",
)


@dataclass(frozen=True)
class SourceRecord:
    SOURCE_ID: str
    VENUE_PROVIDER: str
    SYMBOLS: str
    TIMEFRAMES: str
    START: str
    END: str
    TIMEZONE: str
    RAW_FORMAT: str
    DOWNLOAD_METHOD: str
    LICENSE_ACCESS: str
    MISSING_BAR_BEHAVIOR: str
    DUPLICATE_BEHAVIOR: str
    DST_SESSION_TIME_BEHAVIOR: str
    BID_ASK_AVAILABILITY: str
    VOLUME_TYPE: str
    REPRODUCIBILITY: str
    SHA256_CAPABILITY: str
    KNOWN_LIMITATIONS: str
    authority_status: str
    decision: str
    evidence: list[str] = field(default_factory=list)

    def as_dict(self) -> dict:
        payload = {name: getattr(self, name) for name in INVENTORY_FIELDS}
        payload["AUTHORITY_STATUS"] = self.authority_status
        payload["DECISION"] = self.decision
        payload["EVIDENCE"] = list(self.evidence)
        return payload


DUKASCOPY_TICK = SourceRecord(
    SOURCE_ID="DUKASCOPY_TICK_FX31337_MIRROR_V1",
    VENUE_PROVIDER="Dukascopy Bank SA (originating feed), mirrored by the FX-Data "
                   "GitHub organisation via fx31337/fx-data-download-action",
    SYMBOLS="EURUSD, GBPUSD, USDJPY, XAUUSD",
    TIMEFRAMES="TICK (native); M1 derived here; M5/M15/H1/H4/D1 derived from that M1",
    START="2011-01-01", END="2018-12-31",
    TIMEZONE="UTC — PROVEN, not asserted. Per-symbol identification is degenerate "
             "(gold admits UTC+0/Chicago and UTC+1/New York equally); the corpus "
             "intersection over all four symbols leaves exactly UTC+0.",
    RAW_FORMAT="One CSV per UTC hour: 'YYYY.MM.DD HH:MM:SS.mmm,bid,ask,bid_volume,"
               "ask_volume', CRLF. All instruments on a fixed 1e-5 decimal grid.",
    DOWNLOAD_METHOD="GitHub tarball API at a pinned COMMIT sha per (symbol, year); "
                    "scripts/acquire_dukascopy_fx_multiyear.sh",
    LICENSE_ACCESS="Public GitHub repositories, no declared licence file. Treated as "
                   "RESEARCH-ONLY: bytes are never redistributed by this repo, only "
                   "hashed and referenced. Dukascopy's own historical feed is "
                   "publicly accessible for non-commercial research.",
    MISSING_BAR_BEHAVIOR="Absent hours simply have no file; absent minutes produce no "
                         "bar. Nothing is forward filled. Gaps are classified against "
                         "the declared venue session contract.",
    DUPLICATE_BEHAVIOR="Zero duplicate M1 timestamps measured across all 32 "
                       "symbol-years. The schema rejects duplicates rather than "
                       "deduplicating them.",
    DST_SESSION_TIME_BEHAVIOR="Clock is fixed-offset UTC; the VENUE session boundary "
                              "moves with venue DST. Spot FX = 17:00 America/New_York; "
                              "XAUUSD = CME Globex 17:00 America/Chicago with a daily "
                              "16:00-17:00 halt (confirmed from the data).",
    BID_ASK_AVAILABILITY="YES — native bid and ask on every tick, so spread is MEASURED, "
                         "not assumed.",
    VOLUME_TYPE="tick_volume = genuine count of ticks in the bucket. real_volume = sum "
                "of the provider's reported bid+ask volumes. Neither is invented; "
                "neither is an exchange-cleared volume.",
    REPRODUCIBILITY="HIGH — every (symbol, year) is pinned to an immutable git commit; "
                    "identity is a content Merkle root over the extracted CSV members, "
                    "so it survives re-packaging by the tarball endpoint.",
    SHA256_CAPABILITY="YES — per-member sha256, a raw tree Merkle root, and a canonical "
                      "sha256 for every normalized and derived dataset.",
    KNOWN_LIMITATIONS="(1) A mirror, not the vendor endpoint: the mirror could be "
                      "deleted, though pinned commits make tampering detectable. "
                      "(2) Dukascopy is an ECN aggregator, so quotes are not any single "
                      "retail broker's. (3) XAUUSD begins 2011 and GBPUSD/USDJPY/XAUUSD "
                      "end 2018, which bounds the common window. (4) No commission/swap "
                      "data — spread alone is not a friction authority.",
    authority_status=CERTIFIED,
    decision="SELECTED as the multi-year FX authority: it is the only reachable source "
             "that is tick-native (so M1 is derived, not trusted), hash-pinnable to an "
             "immutable commit, and whose timezone frame could be PROVEN from the data.",
    evidence=[
        "timezone_proof: corpus offset intersection -> UTC+0, 32/32 slices",
        "cross_source_comparison.json: 2017 overlap vs the frozen HistData authority",
        "data_quality_report.json: per symbol-year coverage, gaps and anomalies",
    ],
)

HISTDATA_2017 = SourceRecord(
    SOURCE_ID="HISTDATA_ASCII_M1_2017_PR10_PINNED",
    VENUE_PROVIDER="HistData.com ASCII M1, mirrored in parrondo/deeptrading",
    SYMBOLS="EURUSD, GBPUSD, USDJPY, XAUUSD",
    TIMEFRAMES="M1 native; M15 at >=13/15 minutes; H1/H4/D1 from M15",
    START="2017-01-01", END="2017-12-31",
    TIMEZONE="America/New_York (DST-following) normalized to UTC — frozen contract "
             "in src/ag_edgelab/data/fx_histdata_2017.py",
    RAW_FORMAT="Semicolon-delimited ASCII M1 inside per-symbol zips",
    DOWNLOAD_METHOD="scripts/acquire_histdata_fx_2017.sh (GitHub contents API, "
                    "sha256-pinned)",
    LICENSE_ACCESS="HistData.com free personal/research use; zips never committed",
    MISSING_BAR_BEHAVIOR="M15 buckets below 13/15 minutes are MISSING, never filled",
    DUPLICATE_BEHAVIOR="Hard failure — the loader refuses to dedupe silently",
    DST_SESSION_TIME_BEHAVIOR="Source wall clock follows US DST; normalized to UTC "
                              "before any session logic",
    BID_ASK_AVAILABILITY="NO — single price series, no spread",
    VOLUME_TYPE="None",
    REPRODUCIBILITY="HIGH — four pinned zip sha256 identities",
    SHA256_CAPABILITY="YES",
    KNOWN_LIMITATIONS="Single calendar year (2017). Its OOS window is CONSUMED twice "
                      "and its holdout is sealed.",
    authority_status=REFERENCE,
    decision="UNCHANGED. Used in this mission only as the independent comparator for "
             "the 2017 overlap. No byte, hash, partition or governance record of this "
             "authority was modified.",
    evidence=["config/governance/oos_access_log.json dataset_registry",
              "cross_source_comparison.json"],
)

EJTRADER_MT5 = SourceRecord(
    SOURCE_ID="EJTRADER_MT5_OHLC_MIRROR",
    VENUE_PROVIDER="ejtraderLabs/historical-data (unidentified MT5 broker server)",
    SYMBOLS="EURUSD, GBPUSD, USDJPY, XAUUSD (+8 more)",
    TIMEFRAMES="M15, M30, H1, H4, D1 — no M1",
    START="2012-11-16", END="2022-03-04",
    TIMEZONE="UNPROVABLE. Measured: 0/52 weekly opens align under any fixed offset; "
             "the clock FOLLOWS DST (best fit Europe/Helsinki 48/52), so it is a "
             "broker server clock whose exact DST policy is undeclared and which "
             "diverges from both candidates on the EU/US transition-mismatch weeks.",
    RAW_FORMAT="CSV: Date,open,high,low,close,tick_volume",
    DOWNLOAD_METHOD="GitHub contents API",
    LICENSE_ACCESS="Apache-2.0",
    MISSING_BAR_BEHAVIOR="Undeclared; no gap inventory published",
    DUPLICATE_BEHAVIOR="Measured: 0 duplicates, 0 non-monotonic rows (this part is clean)",
    DST_SESSION_TIME_BEHAVIOR="Source clock itself shifts with DST — the opposite of a "
                              "fixed frame; weekly open hour is 00:00 server time",
    BID_ASK_AVAILABILITY="NO",
    VOLUME_TYPE="tick_volume only",
    REPRODUCIBILITY="MEDIUM — pinnable to a commit, but the upstream broker and its "
                    "server-time policy are unknown and unverifiable",
    SHA256_CAPABILITY="YES (of the mirrored bytes only)",
    KNOWN_LIMITATIONS="(1) Timezone authority unprovable — the single hardest STOP "
                      "condition. (2) 29.6% of EURUSD H1 rows carry float round-trip "
                      "noise (e.g. open=127801.00000000001), so prices are not exact on "
                      "any tick grid. (3) No M1, so higher timeframes cannot descend "
                      "from a verified M1 lineage. (4) Broker identity unknown.",
    authority_status=REJECTED,
    decision="REJECTED despite having the LONGEST history (9.3 years). Section 2 "
             "forbids selecting a source for history alone, and section 16 makes "
             "ambiguous timezone authority a STOP condition. Adopting it would have "
             "required asserting a timezone the data refutes.",
    evidence=[
        "EURUSD H1 sha256 1b29ca23bdc7b2645ae48a0ccb06108263b69e586bdc7d0ba40e66d1e5966eb9 "
        "at commit 34e948c5f454791f67efc9b84f99340cca0d9b08",
        "prove_fixed_offset_frame(2017) -> REFUTED, admissible offsets = {} ",
        "assume-UTC check: 0/52 weekly opens land on any declared venue boundary",
        "17025/57600 rows (29.6%) exceed 3 fractional digits",
    ],
)

VT_MARKETS_MT5 = SourceRecord(
    SOURCE_ID="VT_MARKETS_MT5_HISTORY",
    VENUE_PROVIDER="VT Markets (MetaTrader 5 broker)",
    SYMBOLS="EURUSD, GBPUSD, USDJPY, XAUUSD (broker symbol names may differ)",
    TIMEFRAMES="M1..MN1 via the terminal",
    START="broker dependent", END="live",
    TIMEZONE="Broker server time (typically EET/EEST), undeclared via any public API",
    RAW_FORMAT="MT5 terminal history / MetaTrader5 Python package",
    DOWNLOAD_METHOD="Requires an installed MT5 terminal plus account credentials",
    LICENSE_ACCESS="Account-holder access only",
    MISSING_BAR_BEHAVIOR="Broker dependent, undeclared",
    DUPLICATE_BEHAVIOR="Broker dependent, undeclared",
    DST_SESSION_TIME_BEHAVIOR="Server clock follows broker DST policy",
    BID_ASK_AVAILABILITY="YES in the terminal (and the only path to real commission/swap)",
    VOLUME_TYPE="tick_volume and real_volume",
    REPRODUCIBILITY="LOW from this environment",
    SHA256_CAPABILITY="Only over a local export",
    KNOWN_LIMITATIONS="Outbound network in this sandbox reaches GitHub and PyPI only; "
                      "no MT5 terminal, no credentials, and none may be requested.",
    authority_status=UNAVAILABLE,
    decision="NOT ACQUIRED. This is the blocker for FRICTION_AUTHORITY_COMPLETE: "
             "commission, swap and contract specifications are broker facts and cannot "
             "be derived from a price feed. The schema is prepared and left NULL.",
    evidence=["network probe: only api.github.com / codeload / pypi reachable",
              "friction_authority_gap.json"],
)

PUBLIC_CRYPTO = SourceRecord(
    SOURCE_ID="BINANCE_BYBIT_PUBLIC_ARCHIVES",
    VENUE_PROVIDER="Binance Vision / Bybit public archives",
    SYMBOLS="BTCUSDT and other crypto pairs",
    TIMEFRAMES="M1+ klines; funding history for perpetuals",
    START="2017+", END="live",
    TIMEZONE="UTC epoch milliseconds (unambiguous)",
    RAW_FORMAT="Monthly kline zips / REST JSON",
    DOWNLOAD_METHOD="HTTPS to data.binance.vision / api.bybit.com",
    LICENSE_ACCESS="Public",
    MISSING_BAR_BEHAVIOR="No gap validation in the archived branch scripts",
    DUPLICATE_BEHAVIOR="Partial dedup only",
    DST_SESSION_TIME_BEHAVIOR="N/A — 24/7",
    BID_ASK_AVAILABILITY="NO at kline level",
    VOLUME_TYPE="base/quote volume, trade count",
    REPRODUCIBILITY="Would be HIGH if reachable",
    SHA256_CAPABILITY="Not implemented in the archived branch scripts",
    KNOWN_LIMITATIONS="Both hosts are unreachable from this sandbox (connection "
                      "refused), so no crypto bytes could be retrieved or hashed.",
    authority_status=UNAVAILABLE,
    decision="NOT ACQUIRED. Section 12 is answered as a CONTRACT REVIEW only; see "
             "crypto_data_adapter_review.json.",
    evidence=["network probe: data.binance.vision and api.bybit.com unreachable"],
)

SYNTHETIC_BTCUSDT = SourceRecord(
    SOURCE_ID="SYNTHETIC_BTCUSDT_FIXTURE",
    VENUE_PROVIDER="In-repo generated fixture (scripts/make_synthetic_btcusdt_fixture.py)",
    SYMBOLS="BTCUSDT", TIMEFRAMES="M5", START="synthetic", END="synthetic",
    TIMEZONE="UTC", RAW_FORMAT="CSV",
    DOWNLOAD_METHOD="Generated locally",
    LICENSE_ACCESS="N/A",
    MISSING_BAR_BEHAVIOR="N/A", DUPLICATE_BEHAVIOR="N/A",
    DST_SESSION_TIME_BEHAVIOR="N/A", BID_ASK_AVAILABILITY="NO",
    VOLUME_TYPE="synthetic",
    REPRODUCIBILITY="Deterministic from a seed",
    SHA256_CAPABILITY="YES",
    KNOWN_LIMITATIONS="Synthetic. Carries no information about any real market.",
    authority_status=REJECTED,
    decision="EXCLUDED from the authority by construction. It remains a CI plumbing "
             "fixture and is never citable as edge evidence.",
    evidence=["config/governance/data_authority_gap.json crypto_coverage.synthetic_lane"],
)

ALL_SOURCES: tuple[SourceRecord, ...] = (
    DUKASCOPY_TICK, HISTDATA_2017, EJTRADER_MT5,
    VT_MARKETS_MT5, PUBLIC_CRYPTO, SYNTHETIC_BTCUSDT,
)


def inventory_document() -> dict:
    return {
        "inventory_version": "DATA_AUTHORITY_R1_SOURCE_INVENTORY_V1",
        "selection_rule": (
            "Long history never earns selection on its own. A source is CERTIFIED "
            "only when its provenance is pinned to immutable bytes, its timezone "
            "frame is PROVEN from the data rather than asserted by documentation, "
            "its identity is reproducible by hash, and its gaps are classified."
        ),
        "fields": list(INVENTORY_FIELDS),
        "source_count": len(ALL_SOURCES),
        "sources": [s.as_dict() for s in ALL_SOURCES],
    }


def authority_matrix() -> dict:
    return {
        "matrix_version": "DATA_AUTHORITY_R1_SOURCE_AUTHORITY_MATRIX_V1",
        "criteria": [
            "PROVENANCE_PINNED", "TIMEZONE_PROVEN", "HASHABLE",
            "TICK_OR_M1_NATIVE", "BID_ASK", "MULTI_YEAR", "REACHABLE",
        ],
        "rows": [
            {
                "SOURCE_ID": s.SOURCE_ID,
                "AUTHORITY_STATUS": s.authority_status,
                "PROVENANCE_PINNED": s.SOURCE_ID in {
                    "DUKASCOPY_TICK_FX31337_MIRROR_V1",
                    "HISTDATA_ASCII_M1_2017_PR10_PINNED"},
                "TIMEZONE_PROVEN": s.SOURCE_ID in {
                    "DUKASCOPY_TICK_FX31337_MIRROR_V1",
                    "HISTDATA_ASCII_M1_2017_PR10_PINNED"},
                "HASHABLE": s.SHA256_CAPABILITY.startswith("YES"),
                "TICK_OR_M1_NATIVE": s.SOURCE_ID in {
                    "DUKASCOPY_TICK_FX31337_MIRROR_V1",
                    "HISTDATA_ASCII_M1_2017_PR10_PINNED",
                    "BINANCE_BYBIT_PUBLIC_ARCHIVES"},
                "BID_ASK": s.BID_ASK_AVAILABILITY.startswith("YES"),
                "MULTI_YEAR": s.SOURCE_ID in {
                    "DUKASCOPY_TICK_FX31337_MIRROR_V1", "EJTRADER_MT5_OHLC_MIRROR",
                    "VT_MARKETS_MT5_HISTORY", "BINANCE_BYBIT_PUBLIC_ARCHIVES"},
                "REACHABLE": s.authority_status != UNAVAILABLE,
                "DECISION": s.decision,
            }
            for s in ALL_SOURCES
        ],
    }
