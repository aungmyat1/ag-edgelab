"""DATA_AUTHORITY_R1 — contract tests for the FX data authority.

These tests exercise the guarantees the mission is accountable for:
raw identity, schema validity, UTC normalization, duplicate and
missing-bar detection, OHLC invariants, deterministic resampling,
timeframe lineage, future-mutation isolation, truncation invariance,
partition non-overlap, sealed-holdout denial, consumed-OOS denial,
content-addressed evidence, cross-source diagnostics, and friction-null
semantics.

They run entirely on small in-test fixtures: no network, no external
store, and no dependency on the 5.8 GB raw corpus.
"""

from __future__ import annotations

import json
import subprocess
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from pydantic import ValidationError

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from ag_edgelab.data.authority import cross_source                       # noqa: E402
from ag_edgelab.data.authority.cas import (                              # noqa: E402
    CasStore, ContentMismatch, ContentUnavailable, parse_cas_location,
)
from ag_edgelab.data.authority.friction_contract import (                # noqa: E402
    FrictionAuthorityMissing, FrictionQuote, assert_estimable, empty_quote,
    net_economics_estimable,
)
from ag_edgelab.data.authority.partition import (                        # noqa: E402
    AccessStatus, ConsumedOosDenied, DatasetPartitionRegistry,
    PartitionOverlapError, PartitionRecord, PartitionRole, SealedHoldoutDenied,
)
from ag_edgelab.data.authority.quality import assess_year                # noqa: E402
from ag_edgelab.data.authority.rawobj import (                           # noqa: E402
    RawIdentityError, RawMember, RawObject, hash_archive_members,
    member_index_document, merkle_root, verify_raw_object,
)
from ag_edgelab.data.authority.resample import (                         # noqa: E402
    DERIVED_TIMEFRAMES, closed_bars_asof, derive_all, floor_utc, resample,
)
from ag_edgelab.data.authority.schema import (                           # noqa: E402
    CanonicalBar, SchemaViolation, canonical_dataset_hash, dumps_canonical,
    loads_canonical, validate_canonical_series,
)
from ag_edgelab.data.authority.session import (                          # noqa: E402
    CME_METALS_CHICAGO, SPOT_FX_NEW_YORK, contract_for,
)
from ag_edgelab.data.authority.timezone_proof import (                   # noqa: E402
    AMBIGUOUS, PROVEN, REFUTED, prove_corpus_frame, prove_fixed_offset_frame,
)

UTC = timezone.utc


# ---------------------------------------------------------------------------
# fixtures
# ---------------------------------------------------------------------------

def bar(minute: int, *, symbol: str = "EURUSD", base: float = 1.10000,
        **kw) -> CanonicalBar:
    ts = datetime(2017, 3, 1, 0, 0, tzinfo=UTC) + timedelta(minutes=minute)
    o = round(base + minute * 1e-5, 5)
    return CanonicalBar(
        timestamp_utc=ts, symbol=symbol, open=o, high=round(o + 2e-5, 5),
        low=round(o - 2e-5, 5), close=round(o + 1e-5, 5),
        tick_volume=kw.get("tick_volume", 10),
        real_volume=kw.get("real_volume", 1.5),
        spread=kw.get("spread", 0.00002),
    )


def series(n: int, **kw) -> list[CanonicalBar]:
    return [bar(i, **kw) for i in range(n)]


def agg(rows, timeframe: str, source_timeframe: str = "M1"):
    """resample() returning just the bars (it also returns a coverage audit)."""
    bars, _audit = resample(rows, source_timeframe=source_timeframe,
                            target_timeframe=timeframe)
    return bars


def m15(rows):
    return agg(rows, "M15")


# ---------------------------------------------------------------------------
# raw identity
# ---------------------------------------------------------------------------

def make_archive(tmp_path, payloads: dict[str, bytes]) -> Path:
    """Build a real .tar.gz so raw identity is tested the way it is used."""
    import tarfile, io
    archive = tmp_path / "raw.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        for name, payload in sorted(payloads.items()):
            info = tarfile.TarInfo(name)
            info.size = len(payload)
            tar.addfile(info, io.BytesIO(payload))
    return archive


class TestRawIdentity:
    PAYLOADS = {"EURUSD/2017/01/a_ticks.csv": b"1,2,3\r\n",
                "EURUSD/2017/01/b_ticks.csv": b"4,5,6\r\n"}

    def _record(self, archive: Path, root: str, count: int) -> RawObject:
        return RawObject(
            raw_id="SRC:EURUSD:2017", source_id="SRC", source="unit-test",
            symbol="EURUSD", sha256=root, byte_size=archive.stat().st_size,
            member_count=count, member_index_sha256="0" * 64,
            coverage_start=datetime(2017, 1, 1, tzinfo=UTC),
            coverage_end=datetime(2017, 12, 31, tzinfo=UTC),
            retrieval_timestamp=datetime(2026, 1, 1, tzinfo=UTC),
            timezone="UTC", format="csv", local_path=str(archive),
            upstream_ref="git:abc")

    def test_merkle_root_is_order_independent(self):
        a = [RawMember("b.csv", "1" * 64, 10), RawMember("a.csv", "2" * 64, 20)]
        assert merkle_root(a) == merkle_root(list(reversed(a)))

    def test_merkle_root_changes_when_any_member_changes(self):
        a = [RawMember("a.csv", "1" * 64, 10), RawMember("b.csv", "2" * 64, 20)]
        b = [RawMember("a.csv", "1" * 64, 10), RawMember("b.csv", "3" * 64, 20)]
        assert merkle_root(a) != merkle_root(b)

    def test_merkle_root_changes_when_a_member_is_dropped(self):
        a = [RawMember("a.csv", "1" * 64, 10), RawMember("b.csv", "2" * 64, 20)]
        assert merkle_root(a) != merkle_root(a[:1])

    def test_archive_hash_is_stable_across_recompression(self, tmp_path):
        """Identity must survive re-packaging: the GitHub tarball endpoint
        does not return byte-stable archives, so the Merkle root is the
        identity, not the tarball bytes."""
        import hashlib
        first = make_archive(tmp_path / "a", self.PAYLOADS) \
            if (tmp_path / "a").mkdir() is None else None
        (tmp_path / "b").mkdir()
        second = make_archive(tmp_path / "b", self.PAYLOADS)
        root_a, members_a = hash_archive_members(first)
        root_b, members_b = hash_archive_members(second)
        assert root_a == root_b
        assert len(members_a) == len(members_b) == 2
        assert hashlib.sha256(first.read_bytes()).hexdigest() != root_a

    def test_verify_raw_object_accepts_an_intact_archive(self, tmp_path):
        archive = make_archive(tmp_path, self.PAYLOADS)
        root, members = hash_archive_members(archive)
        verify_raw_object(self._record(archive, root, len(members)), archive)

    def test_verify_raw_object_fails_closed_on_modified_content(self, tmp_path):
        archive = make_archive(tmp_path, self.PAYLOADS)
        root, members = hash_archive_members(archive)
        record = self._record(archive, root, len(members))
        tampered = dict(self.PAYLOADS)
        tampered["EURUSD/2017/01/a_ticks.csv"] = b"9,9,9\r\n"
        (tmp_path / "t").mkdir()
        bad = make_archive(tmp_path / "t", tampered)
        with pytest.raises(RawIdentityError, match="BLOCKED_DATA_AUTHORITY"):
            verify_raw_object(record, bad)

    def test_verify_raw_object_fails_closed_when_absent(self, tmp_path):
        archive = make_archive(tmp_path, self.PAYLOADS)
        root, members = hash_archive_members(archive)
        record = self._record(archive, root, len(members))
        archive.unlink()
        with pytest.raises(RawIdentityError, match="fail closed"):
            verify_raw_object(record, archive)

    def test_member_index_is_byte_stable(self, tmp_path):
        archive = make_archive(tmp_path, self.PAYLOADS)
        _, members = hash_archive_members(archive)
        assert member_index_document(members) == member_index_document(
            tuple(reversed(members)))


# ---------------------------------------------------------------------------
# schema
# ---------------------------------------------------------------------------

class TestCanonicalSchema:
    def test_valid_bar_round_trips_through_text(self):
        original = series(5)
        restored = loads_canonical(dumps_canonical(original))
        assert list(restored) == original

    def test_dataset_hash_is_stable_and_content_sensitive(self):
        a, b = series(5), series(5)
        assert canonical_dataset_hash(a) == canonical_dataset_hash(b)
        assert canonical_dataset_hash(a) != canonical_dataset_hash(series(6))

    @pytest.mark.parametrize("field,value", [
        ("high", 1.0), ("low", 9.0), ("open", 9.0), ("close", 9.0),
    ])
    def test_ohlc_invariant_rejects_impossible_bars(self, field, value):
        base = bar(0).model_dump()
        base[field] = value
        with pytest.raises(ValidationError, match="OHLC invariant"):
            CanonicalBar(**base)

    def test_naive_timestamp_is_rejected(self):
        base = bar(0).model_dump()
        base["timestamp_utc"] = datetime(2017, 1, 1, 0, 0)
        with pytest.raises(ValidationError, match="aware UTC"):
            CanonicalBar(**base)

    def test_non_utc_timestamp_is_rejected(self):
        base = bar(0).model_dump()
        base["timestamp_utc"] = datetime(2017, 1, 1, tzinfo=timezone(timedelta(hours=2)))
        with pytest.raises(ValidationError, match="aware UTC"):
            CanonicalBar(**base)

    def test_duplicate_timestamps_are_rejected_not_deduplicated(self):
        rows = series(3)
        with pytest.raises(SchemaViolation):
            validate_canonical_series(rows + [rows[-1]], symbol="EURUSD")

    def test_out_of_order_series_is_rejected_not_sorted(self):
        rows = series(3)
        with pytest.raises(SchemaViolation):
            validate_canonical_series([rows[2], rows[0], rows[1]], symbol="EURUSD")

    def test_absent_optional_field_is_empty_not_zero(self):
        plain = CanonicalBar(timestamp_utc=datetime(2017, 1, 1, tzinfo=UTC),
                             symbol="EURUSD", open=1.1, high=1.1, low=1.1, close=1.1)
        text = dumps_canonical([plain])
        body = [ln for ln in text.splitlines() if ln and not ln.startswith("#")][1]
        assert body.endswith(",,,,,"), body
        assert loads_canonical(text)[0].tick_volume is None


# ---------------------------------------------------------------------------
# timezone
# ---------------------------------------------------------------------------

class TestTimezoneProof:
    def _utc_opens(self, contract, year=2017):
        """Synthesize a year of observations from a UTC-clock source."""
        out = []
        start = datetime(year, 1, 1, tzinfo=UTC)
        end = datetime(year + 1, 1, 1, tzinfo=UTC)
        for w_start, w_end in contract.windows(start, end):
            cursor = w_start
            while cursor < w_end:
                out.append(cursor.replace(tzinfo=None))
                cursor += timedelta(hours=1)
        return out

    def test_single_spot_fx_instrument_is_also_degenerate(self):
        """One instrument can never separate a clock from a venue session.

        (UTC+0, New York 17:00) and (UTC-1, Chicago 17:00) predict exactly
        the same observations. The prover must say so rather than silently
        preferring UTC.
        """
        proof = prove_fixed_offset_frame(self._utc_opens(SPOT_FX_NEW_YORK))
        assert proof.status == AMBIGUOUS
        assert proof.offset_hours is None
        assert set(proof.admissible_offsets) == {-1, 0}
        assert proof.match_fraction == 1.0

    def test_shifted_clock_is_never_mistaken_for_utc(self):
        shifted = [t + timedelta(hours=3)
                   for t in self._utc_opens(SPOT_FX_NEW_YORK)]
        proof = prove_fixed_offset_frame(shifted)
        assert 0 not in proof.admissible_offsets
        assert set(proof.admissible_offsets) == {2, 3}

    def test_week_segmentation_is_clock_agnostic(self):
        """Week boundaries come from the weekend GAP, not a calendar rule.

        A calendar rule has to assume where the week starts in the source
        clock — the very unknown being identified — and on a clock shifted
        far enough it absorbs the previous week's closing bar.
        """
        base = self._utc_opens(SPOT_FX_NEW_YORK)
        counts = {
            shift: len(prove_fixed_offset_frame(
                [t + timedelta(hours=shift) for t in base]).source_clock_open_hours)
            for shift in (-6, -3, 0, 3, 6)
        }
        assert all(n == 2 for n in counts.values()), counts

    def test_dst_following_source_clock_is_refuted(self):
        """A broker server clock is not a fixed offset and must not pass."""
        from zoneinfo import ZoneInfo
        helsinki = ZoneInfo("Europe/Helsinki")
        stamps = [t.replace(tzinfo=UTC).astimezone(helsinki).replace(tzinfo=None)
                  for t in self._utc_opens(SPOT_FX_NEW_YORK)]
        assert prove_fixed_offset_frame(stamps).status == REFUTED

    def test_too_few_weeks_is_ambiguous_never_assumed_utc(self):
        stamps = self._utc_opens(SPOT_FX_NEW_YORK)[: 24 * 7 * 3]
        proof = prove_fixed_offset_frame(stamps)
        assert proof.status == AMBIGUOUS
        assert proof.offset_hours is None

    def test_single_instrument_gold_is_degenerate(self):
        """Gold alone cannot separate UTC+0/Chicago from UTC+1/New York."""
        proof = prove_fixed_offset_frame(self._utc_opens(CME_METALS_CHICAGO))
        assert proof.status == AMBIGUOUS
        assert set(proof.admissible_offsets) == {0, 1}

    def test_corpus_intersection_resolves_the_gold_degeneracy(self):
        fx = prove_fixed_offset_frame(self._utc_opens(SPOT_FX_NEW_YORK))
        gold = prove_fixed_offset_frame(self._utc_opens(CME_METALS_CHICAGO))
        corpus = prove_corpus_frame({"EURUSD": fx, "XAUUSD": gold})
        assert corpus.status == PROVEN
        assert corpus.offset_hours == 0
        assert corpus.resolved_session_contracts["XAUUSD"] == \
            CME_METALS_CHICAGO.contract_id
        assert corpus.resolved_session_contracts["EURUSD"] == \
            SPOT_FX_NEW_YORK.contract_id

    def test_mid_corpus_venue_change_does_not_refute_the_clock(self):
        """XAUUSD really does change session convention between 2011 and 2012.

        The clock stayed UTC throughout. A prover that demanded one venue
        contract for the whole corpus would reject the true clock because
        the SESSION moved.
        """
        early = self._utc_opens(SPOT_FX_NEW_YORK, year=2011)
        late = [t for y in (2012, 2013, 2014)
                for t in self._utc_opens(CME_METALS_CHICAGO, year=y)]
        proof = prove_fixed_offset_frame(early + late)
        assert 0 in proof.admissible_offsets

    def test_dst_following_clock_cannot_hide_behind_two_contracts(self):
        """The persistence rule is what stops the union from being a loophole.

        A EET/EEST broker clock looks like New York every winter and like
        Chicago every summer. Allowing the contract to vary per week would
        let it pass as a fixed offset; requiring venue sessions to persist
        exposes it.
        """
        from zoneinfo import ZoneInfo
        helsinki = ZoneInfo("Europe/Helsinki")
        stamps = [t.replace(tzinfo=UTC).astimezone(helsinki).replace(tzinfo=None)
                  for y in (2015, 2016, 2017)
                  for t in self._utc_opens(SPOT_FX_NEW_YORK, year=y)]
        proof = prove_fixed_offset_frame(stamps)
        assert proof.status == REFUTED
        assert proof.admissible_offsets == ()

    def test_corpus_refuses_when_instruments_disagree(self):
        fx = prove_fixed_offset_frame(self._utc_opens(SPOT_FX_NEW_YORK))
        shifted = prove_fixed_offset_frame(
            [t + timedelta(hours=6) for t in self._utc_opens(SPOT_FX_NEW_YORK)])
        corpus = prove_corpus_frame({"A": fx, "B": shifted})
        assert corpus.status != PROVEN
        assert corpus.offset_hours is None


class TestSessionContracts:
    def test_spot_fx_boundary_tracks_us_dst(self):
        winter = SPOT_FX_NEW_YORK.windows(
            datetime(2017, 1, 1, tzinfo=UTC), datetime(2017, 1, 10, tzinfo=UTC))
        summer = SPOT_FX_NEW_YORK.windows(
            datetime(2017, 7, 1, tzinfo=UTC), datetime(2017, 7, 10, tzinfo=UTC))
        assert winter[0][0].hour == 22
        assert summer[0][0].hour == 21

    def test_metals_contract_excludes_the_daily_halt(self):
        windows = CME_METALS_CHICAGO.windows(
            datetime(2017, 1, 2, tzinfo=UTC), datetime(2017, 1, 7, tzinfo=UTC))
        minutes = sum((e - s).total_seconds() / 60 for s, e in windows)
        # 4 full sessions of 23h inside the probe window, never 24h days.
        assert all((e - s) <= timedelta(hours=23) for s, e in windows)
        assert minutes < 5 * 24 * 60

    def test_unknown_symbol_refuses_to_guess(self):
        with pytest.raises(KeyError):
            contract_for("NOT_A_SYMBOL")


# ---------------------------------------------------------------------------
# resampling / lineage
# ---------------------------------------------------------------------------

class TestResampling:
    def test_floor_is_aligned_to_utc_midnight(self):
        ts = datetime(2017, 3, 1, 13, 47, 31, tzinfo=UTC)
        assert floor_utc(ts, 60) == datetime(2017, 3, 1, 13, 0, tzinfo=UTC)
        assert floor_utc(ts, 240) == datetime(2017, 3, 1, 12, 0, tzinfo=UTC)
        assert floor_utc(ts, 1440) == datetime(2017, 3, 1, 0, 0, tzinfo=UTC)

    def test_resampling_is_deterministic(self):
        rows = series(600)
        assert canonical_dataset_hash(m15(rows)) == canonical_dataset_hash(m15(rows))

    def test_resampled_ohlc_matches_member_extremes(self):
        rows = series(60)
        h1 = agg(rows, "H1")
        assert len(h1) == 1
        assert h1[0].open == rows[0].open
        assert h1[0].close == rows[-1].close
        assert h1[0].high == max(b.high for b in rows)
        assert h1[0].low == min(b.low for b in rows)

    def test_volumes_sum_and_are_never_invented(self):
        rows = series(15)
        bucket = agg(rows, "M15")[0]
        assert bucket.tick_volume == sum(b.tick_volume for b in rows)
        partial = [b.model_copy(update={"tick_volume": None}) if i == 0 else b
                   for i, b in enumerate(rows)]
        assert agg(partial, "M15")[0].tick_volume is None

    def test_no_bar_is_emitted_for_an_empty_bucket(self):
        rows = [bar(0), bar(120)]           # one hour of silence between
        hours = {b.timestamp_utc.hour for b in agg(rows, "H1")}
        assert hours == {0, 2}

    def test_derive_all_shares_one_raw_lineage(self):
        rows = series(1440)
        datasets, lineages, audits = derive_all(
            rows, symbol="EURUSD", raw_parent_sha256="a" * 64,
            m1_dataset_sha256="b" * 64)
        assert set(datasets) == set(DERIVED_TIMEFRAMES)
        assert set(audits) == set(DERIVED_TIMEFRAMES)
        for lin in lineages.values():
            assert lin.raw_parent_sha256 == "a" * 64
            assert lin.source_dataset_sha256 == "b" * 64
            assert lin.source_timeframe == "M1"
            assert lin.as_dict()["lineage"].startswith("RAW(")
            assert lin.timezone == "UTC"

    def test_future_mutation_cannot_change_a_past_bar(self):
        rows = series(120)
        before = canonical_dataset_hash(agg(rows[:60], "H1"))
        extended = rows + [bar(i, base=2.0) for i in range(200, 260)]
        after = agg(extended, "H1")
        assert canonical_dataset_hash([b for b in after
                                       if b.timestamp_utc.hour == 0]) == before

    def test_truncation_invariance_of_closed_bars(self):
        rows = series(300)
        asof = datetime(2017, 3, 1, 3, 0, tzinfo=UTC)
        full = closed_bars_asof(agg(rows, "H1"), timeframe="H1", asof=asof)
        truncated_source = [b for b in rows if b.timestamp_utc < asof]
        trunc = closed_bars_asof(agg(truncated_source, "H1"), timeframe="H1",
                                 asof=asof)
        assert canonical_dataset_hash(full) == canonical_dataset_hash(trunc)

    def test_forming_bar_is_never_visible(self):
        rows = series(90)
        asof = datetime(2017, 3, 1, 1, 30, tzinfo=UTC)
        closed = closed_bars_asof(agg(rows, "H1"), timeframe="H1", asof=asof)
        assert [b.timestamp_utc.hour for b in closed] == [0]


# ---------------------------------------------------------------------------
# quality
# ---------------------------------------------------------------------------

class TestQuality:
    def _session_bars(self, n: int) -> list[CanonicalBar]:
        """n M1 bars starting inside the declared FX week."""
        start = datetime(2017, 3, 1, 0, 0, tzinfo=UTC)   # Wednesday, in session
        out = []
        for i in range(n):
            ts = start + timedelta(minutes=i)
            out.append(CanonicalBar(timestamp_utc=ts, symbol="EURUSD", open=1.1,
                                    high=1.1, low=1.1, close=1.1))
        return out

    def test_missing_bars_are_detected_against_the_session_grid(self):
        rows = self._session_bars(120)
        with_hole = rows[:30] + rows[60:]
        report = assess_year(with_hole, symbol="EURUSD", year=2017, timeframe="M1")
        assert report.missing_bars >= 30
        assert report.largest_gap_minutes >= 30

    def test_weekend_observation_is_flagged_not_dropped(self):
        saturday = CanonicalBar(
            timestamp_utc=datetime(2017, 3, 4, 12, 0, tzinfo=UTC),
            symbol="EURUSD", open=1.1, high=1.1, low=1.1, close=1.1)
        rows = self._session_bars(60) + [saturday]
        report = assess_year(rows, symbol="EURUSD", year=2017, timeframe="M1")
        assert report.weekend_observations == 1
        assert report.bar_count == 61        # retained, not removed

    def test_repair_policy_is_none(self):
        report = assess_year(self._session_bars(60), symbol="EURUSD", year=2017,
                             timeframe="M1")
        assert report.as_dict()["repair_policy"].startswith("NONE")

    def test_gold_uses_the_metals_session_contract(self):
        report = assess_year(
            [CanonicalBar(timestamp_utc=datetime(2017, 3, 1, 0, 0, tzinfo=UTC),
                          symbol="XAUUSD", open=1200.0, high=1200.0, low=1200.0,
                          close=1200.0)],
            symbol="XAUUSD", year=2017, timeframe="M1")
        assert report.as_dict()["session_contract"] == CME_METALS_CHICAGO.contract_id


# ---------------------------------------------------------------------------
# partitions
# ---------------------------------------------------------------------------

def _rec(role, status, start, end, *, family="F", sealed=False, **kw):
    return PartitionRecord(
        dataset_id="DS", dataset_hash="h", role=role, candidate_family=family,
        start=datetime.fromisoformat(start).replace(tzinfo=UTC),
        end=datetime.fromisoformat(end).replace(tzinfo=UTC),
        access_status=status, sealed=sealed, **kw)


class TestPartitionGovernance:
    def test_overlapping_partitions_are_rejected(self):
        reg = DatasetPartitionRegistry()
        reg.add(_rec(PartitionRole.DEVELOPMENT, AccessStatus.AVAILABLE,
                     "2011-01-01", "2016-01-01"))
        with pytest.raises(PartitionOverlapError):
            reg.add(_rec(PartitionRole.WALK_FORWARD, AccessStatus.AVAILABLE,
                         "2015-06-01", "2017-01-01"))

    def test_adjacent_partitions_are_allowed(self):
        reg = DatasetPartitionRegistry()
        reg.add(_rec(PartitionRole.DEVELOPMENT, AccessStatus.AVAILABLE,
                     "2011-01-01", "2016-01-01"))
        reg.add(_rec(PartitionRole.WALK_FORWARD, AccessStatus.AVAILABLE,
                     "2016-01-01", "2017-01-01"))
        assert len(reg.records) == 2

    def test_sealed_holdout_read_is_denied(self):
        reg = DatasetPartitionRegistry()
        reg.add(_rec(PartitionRole.SEALED_HOLDOUT, AccessStatus.SEALED,
                     "2018-07-01", "2019-01-01", sealed=True))
        with pytest.raises(SealedHoldoutDenied):
            reg.assert_readable(dataset_id="DS", candidate_family="F",
                                role=PartitionRole.SEALED_HOLDOUT,
                                requester="unit-test")

    def test_consumed_oos_read_is_denied(self):
        reg = DatasetPartitionRegistry()
        reg.add(_rec(PartitionRole.OOS, AccessStatus.CONSUMED,
                     "2017-09-01", "2017-12-01",
                     consumed_at=datetime(2026, 1, 1, tzinfo=UTC),
                     consumed_by="TARGET_POLICY_C3_V1"))
        with pytest.raises(ConsumedOosDenied):
            reg.assert_readable(dataset_id="DS", candidate_family="F",
                                role=PartitionRole.OOS, requester="unit-test")

    def test_available_oos_is_readable_once(self):
        reg = DatasetPartitionRegistry()
        reg.add(_rec(PartitionRole.OOS, AccessStatus.AVAILABLE,
                     "2018-01-01", "2018-07-01"))
        reg.assert_readable(dataset_id="DS", candidate_family="F",
                            role=PartitionRole.OOS, requester="unit-test")
        reg.mark_consumed(dataset_id="DS", candidate_family="F",
                          role=PartitionRole.OOS, consumed_by="X",
                          consumed_at=datetime(2026, 1, 1, tzinfo=UTC))
        with pytest.raises(ConsumedOosDenied):
            reg.assert_readable(dataset_id="DS", candidate_family="F",
                                role=PartitionRole.OOS, requester="unit-test")

    def test_consumed_window_is_development_known_for_a_new_family(self):
        reg = DatasetPartitionRegistry()
        reg.add(_rec(PartitionRole.OOS, AccessStatus.CONSUMED,
                     "2017-09-01", "2017-12-01", family="OLD",
                     consumed_at=datetime(2026, 1, 1, tzinfo=UTC),
                     consumed_by="TARGET_POLICY_C3_V1"))
        verdict = reg.classify_for_new_family(
            dataset_id="DS", start=datetime(2017, 9, 15, tzinfo=UTC),
            end=datetime(2017, 10, 15, tzinfo=UTC))
        assert verdict is AccessStatus.DEVELOPMENT_KNOWN

    def test_sealed_holdout_must_declare_sealed(self):
        with pytest.raises(Exception):
            _rec(PartitionRole.SEALED_HOLDOUT, AccessStatus.AVAILABLE,
                 "2018-07-01", "2019-01-01")

    def test_consumed_record_requires_attribution(self):
        with pytest.raises(Exception):
            _rec(PartitionRole.OOS, AccessStatus.CONSUMED,
                 "2017-09-01", "2017-12-01")


# ---------------------------------------------------------------------------
# content-addressed storage
# ---------------------------------------------------------------------------

class TestContentAddressedStore:
    def test_round_trip(self, tmp_path):
        store = CasStore(tmp_path)
        digest = store.put_text("hello authority")
        assert store.get_text(digest) == "hello authority"
        entry = store.store_entry("A", "hello authority", schema_version="V1")
        assert parse_cas_location(entry.storage_location) == entry.sha256

    def test_missing_content_fails_closed(self, tmp_path):
        with pytest.raises(ContentUnavailable):
            CasStore(tmp_path).get_bytes("a" * 64)

    def test_corrupted_content_fails_closed(self, tmp_path):
        store = CasStore(tmp_path)
        digest = store.put_text("original")
        store.path_for(digest).write_text("tampered", encoding="utf-8")
        with pytest.raises(ContentMismatch):
            store.get_text(digest)

    def test_identical_content_is_stored_once(self, tmp_path):
        store = CasStore(tmp_path)
        assert store.put_text("same") == store.put_text("same")


class TestEvidenceVerifier:
    def _run(self, *args):
        return subprocess.run(
            [sys.executable, str(ROOT / "scripts" / "verify_external_artifacts.py"),
             *args], capture_output=True, text=True)

    def test_verifier_passes_on_a_clean_checkout(self):
        assert self._run().returncode == 0

    def test_registry_content_addressed_entries_are_self_consistent(self):
        registry = json.loads(
            (ROOT / "config" / "governance" / "external_artifact_registry.json")
            .read_text(encoding="utf-8"))
        for art in registry.get("content_addressed", []):
            assert art["storage_location"] == f"cas:{art['sha256']}"
            for field in ("artifact_id", "schema_version", "producer_commit",
                          "dataset_role", "byte_size"):
                assert art.get(field) not in (None, ""), (art["artifact_id"], field)


# ---------------------------------------------------------------------------
# cross-source diagnostics
# ---------------------------------------------------------------------------

class TestCrossSource:
    def test_identical_series_agree(self):
        rows = series(100)
        result = cross_source.compare(rows, rows, symbol="EURUSD", timeframe="M1",
                                      source_a="A", source_b="B")
        assert result.verdict == cross_source.AGREEMENT
        assert result.median_abs_close_diff_ticks == 0.0
        assert result.timestamp_agreement_pct == 100.0

    def test_scale_error_is_caught(self):
        rows = series(100)
        scaled = [b.model_copy(update={
            "open": b.open * 10, "high": b.high * 10,
            "low": b.low * 10, "close": b.close * 10}) for b in rows]
        result = cross_source.compare(rows, scaled, symbol="EURUSD", timeframe="M1",
                                      source_a="A", source_b="B")
        assert result.verdict == cross_source.SCALE_DISAGREEMENT

    def test_disjoint_series_report_no_overlap(self):
        a = series(10)
        b = [x.model_copy(update={
            "timestamp_utc": x.timestamp_utc + timedelta(days=400)}) for x in a]
        result = cross_source.compare(a, b, symbol="EURUSD", timeframe="M1",
                                      source_a="A", source_b="B")
        assert result.verdict == cross_source.NO_OVERLAP

    def test_comparison_never_mutates_either_input(self):
        a, b = series(50), series(50)
        before = (canonical_dataset_hash(a), canonical_dataset_hash(b))
        cross_source.compare(a, b, symbol="EURUSD", timeframe="M1",
                             source_a="A", source_b="B")
        assert (canonical_dataset_hash(a), canonical_dataset_hash(b)) == before

    def test_timestamp_disagreement_is_reported_separately_from_price(self):
        a = series(100)
        b = [x for i, x in enumerate(a) if i % 2 == 0]
        result = cross_source.compare(a, b, symbol="EURUSD", timeframe="M1",
                                      source_a="A", source_b="B")
        assert result.median_abs_close_diff_ticks == 0.0
        assert result.timestamp_agreement_pct < 100.0


# ---------------------------------------------------------------------------
# friction
# ---------------------------------------------------------------------------

class TestFrictionNullSemantics:
    def test_empty_quote_is_incomplete(self):
        quote = empty_quote("EURUSD", "VT Markets", "RAW_ECN")
        assert not quote.is_complete
        assert set(quote.missing_value_fields()) >= {"commission", "swap_long"}

    def test_null_is_not_zero(self):
        quote = empty_quote("EURUSD", "VT Markets", "RAW_ECN")
        assert quote.commission is None
        assert quote.commission != 0

    def test_net_economics_not_estimable_without_authority(self):
        quotes = [empty_quote(s, "VT Markets", "RAW_ECN")
                  for s in ("EURUSD", "XAUUSD")]
        assert net_economics_estimable(quotes) is False

    def test_assert_estimable_raises_on_null_fields(self):
        with pytest.raises(FrictionAuthorityMissing,
                           match="NOT_ESTIMABLE_NO_FRICTION_AUTHORITY"):
            assert_estimable([empty_quote("EURUSD", "V", "A")], context="unit-test")

    def test_assert_estimable_raises_on_empty_input(self):
        with pytest.raises(FrictionAuthorityMissing):
            assert_estimable([], context="unit-test")

    def test_spread_alone_does_not_complete_the_authority(self):
        """A measured spread is real evidence but not a friction authority."""
        partial = FrictionQuote(
            symbol="EURUSD", venue="Dukascopy", account_type="ECN_AGGREGATE",
            timestamp=datetime(2017, 1, 1, tzinfo=UTC), source="tick feed",
            source_hash="a" * 64, bid=1.05, ask=1.0501,
            spread_points=10.0, spread_pips=1.0)
        assert not partial.is_complete
        assert "commission" in partial.missing_value_fields()
        with pytest.raises(FrictionAuthorityMissing):
            assert_estimable([partial], context="spread-only")

    def test_fully_populated_quote_is_estimable(self):
        """The gate opens only when every field is genuinely supplied."""
        complete = FrictionQuote(
            symbol="EURUSD", venue="V", account_type="A",
            timestamp=datetime(2017, 1, 1, tzinfo=UTC), source="broker",
            source_hash="b" * 64, bid=1.05, ask=1.0501, spread_points=10.0,
            spread_pips=1.0, commission=3.5, swap_long=-1.2, swap_short=0.4,
            contract_size=100000.0, tick_size=1e-5, tick_value=1.0)
        assert complete.is_complete
        assert net_economics_estimable([complete]) is True
        assert_estimable([complete], context="unit-test")
