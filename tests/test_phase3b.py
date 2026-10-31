"""Phase 3B archive, publisher handover and historical gap regressions.

All numeric values and publisher bytes here are synthetic unit-test fixtures.
"""
import hashlib
from dataclasses import replace
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest

from packages.connectors.base import SourceObservation
from packages.connectors.india_release import ReleaseManifest, parse_release_package
from packages.jobs.ingest import ingest_records
from packages.jobs.source_archive import archive_original, read_original
from packages.domain.calendar import recent_sessions
from packages.domain.config import registry
from packages.scoring.engine_v2 import history_contiguous
from scripts.phase3b_gap_report import coverage

UTC = timezone.utc


def manifest(provider, published, version):
    host = {"rbi": "www.rbi.org.in", "fbil": "www.fbil.org.in", "nsdl": "pilot.fpi.nsdl.co.in"}[provider]
    return ReleaseManifest(provider, f"https://{host}/test-original", f"https://{host}/test-release-notice", published, hashlib.sha256(b"synthetic publisher fixture").hexdigest(), "written-permission", version)


def csv_row(indicator, value, unit, start, end, quality="verified"):
    return f"indicator_id,value,unit,period_start,period_end,vintage_id,quality\n{indicator},{value},{unit},{start},{end},synthetic-fixture,{quality}\n".encode()


def test_controlled_archive_is_idempotent_and_tamper_evident(tmp_path, monkeypatch):
    monkeypatch.setenv("SOURCE_ARCHIVE_ROOT", str(tmp_path / "isolated-archive"))
    raw = b"synthetic publisher fixture"
    first = archive_original(raw)
    second = archive_original(raw)
    assert first["created"] is True and second["created"] is False
    assert read_original(first["reference"], first["sha256"]) == raw
    assert "archive://sha256/" in first["reference"]
    with pytest.raises(ValueError):
        read_original(first["reference"], "0" * 64)
    (tmp_path / "isolated-archive" / "sha256" / first["sha256"]).write_bytes(b"tampered fixture")
    with pytest.raises(ValueError, match="integrity"):
        read_original(first["reference"], first["sha256"])
    with pytest.raises(ValueError, match="differ"):
        archive_original(raw)


def test_rbi_fbil_handover_and_source_definition():
    rbi = manifest("rbi", datetime(2018, 7, 9, 12, tzinfo=UTC), "rbi-reference-v1")
    assert parse_release_package(csv_row("usd_inr_spot", "70", "INR_per_USD", "2018-07-09", "2018-07-09"), rbi)[0].provider == "rbi"
    with pytest.raises(ValueError, match="ended"):
        parse_release_package(csv_row("usd_inr_spot", "70", "INR_per_USD", "2018-07-10", "2018-07-10"), replace(rbi, published_at=datetime(2018, 7, 11, 12, tzinfo=UTC)))
    fbil = manifest("fbil", datetime(2018, 7, 11, 12, tzinfo=UTC), "fbil-reference-v1")
    assert parse_release_package(csv_row("usd_inr_spot", "70", "INR_per_USD", "2018-07-10", "2018-07-10"), fbil)[0].provider == "fbil"
    with pytest.raises(ValueError, match="began"):
        parse_release_package(csv_row("usd_inr_spot", "70", "INR_per_USD", "2018-07-09", "2018-07-09"), fbil)
    with pytest.raises(ValueError, match="definition"):
        parse_release_package(csv_row("usd_inr_spot", "70", "INR_per_USD", "2018-07-10", "2018-07-10"), replace(fbil, definition_version="rbi-reference-v1"))


def test_nsdl_confirmed_provisional_and_monthly_basis_rejected_for_daily_ids():
    confirmed = manifest("nsdl", datetime(2024, 10, 2, 12, tzinfo=UTC), "nsdl-confirmed-custodian-v1")
    daily = csv_row("fpi_equity_net_inr", "-1000", "INR_cr", "2024-10-01", "2024-10-01")
    assert parse_release_package(daily, confirmed)[0].quality == "verified"
    provisional = replace(confirmed, definition_version="nsdl-provisional-exchange-v1")
    with pytest.raises(ValueError, match="quality"):
        parse_release_package(daily, provisional)
    assert parse_release_package(daily.replace(b"verified", b"provisional"), provisional)[0].quality == "provisional"
    monthly = csv_row("fpi_debt_net_inr", "-1000", "INR_cr", "2024-09-01", "2024-09-30")
    with pytest.raises(ValueError, match="Monthly cumulative"):
        parse_release_package(monthly, confirmed)


def test_release_requires_plausible_publication_evidence_and_frequency_definition():
    rbi = manifest("rbi", datetime(2026, 10, 30, 12, tzinfo=UTC), "rbi-wss-gross-reserves-v1")
    weekly = csv_row("fx_gross_reserves_usd", "600", "USD_bn", "2026-10-23", "2026-10-23")
    assert parse_release_package(weekly, rbi)[0].published_at == rbi.published_at
    with pytest.raises(ValueError, match="WSS definition"):
        parse_release_package(weekly, replace(rbi, definition_version="rbi-unknown-reserves-v1"))
    with pytest.raises(ValueError, match="Period must precede"):
        parse_release_package(weekly, replace(rbi, published_at=datetime(2026, 10, 20, 12, tzinfo=UTC)))
    with pytest.raises(ValueError, match="HTTPS URLs"):
        parse_release_package(weekly, replace(rbi, publication_evidence_url="https://other.example/unsupported-release"))
    daily_yield = csv_row("india_10y_yield", "7.12", "pct", "2026-10-29", "2026-10-29")
    with pytest.raises(ValueError, match="Monthly end-period"):
        parse_release_package(daily_yield, rbi)
    assert parse_release_package(daily_yield, replace(rbi, definition_version="rbi-daily-10y-benchmark-v1"))[0].unit == "pct"


def test_nsdl_history_rejects_conflicting_reporting_basis():
    days = recent_sessions(datetime(2026, 10, 30, tzinfo=UTC), "india", 20)
    rows = [SimpleNamespace(period_end=day, provider="nsdl", vintage_id="nsdl-confirmed-custodian-v1:release") for day in days]
    definition = registry(phase2=True)["fpi_equity_net_inr"]
    assert history_contiguous(rows, definition, "rolling_sum_20", "fpi_equity_net_inr")
    rows[-1].vintage_id = "nsdl-provisional-exchange-v1:release"
    assert not history_contiguous(rows, definition, "rolling_sum_20", "fpi_equity_net_inr")


def test_gap_report_keeps_late_backfill_out_of_system_known_and_tracks_revisions(db):
    as_of = datetime(2018, 7, 10, 12, tzinfo=UTC)
    before = coverage(db, as_of)["indicators"]["usd_inr_spot"]
    assert before["source_known_count"] == before["system_known_count"] == 0
    record = SourceObservation("usd_inr_spot", Decimal("70"), "INR_per_USD", date(2018, 7, 6), date(2018, 7, 6), datetime(2018, 7, 9, 12, tzinfo=UTC), "rbi", "https://www.rbi.org.in/unit-test-only", "synthetic-original")
    assert ingest_records(db, [record], b"synthetic-first", "rbi")["inserted"] == 1
    assert ingest_records(db, [record], b"synthetic-first", "rbi")["duplicate"] == 1
    after = coverage(db, as_of)["indicators"]["usd_inr_spot"]
    assert after["source_known_count"] == 1 and after["system_known_count"] == 0
    assert "2018-07" not in after["missing_months_source_known"]
    assert "2018-07" in after["missing_months_system_known"]
    assert "2018-06" in after["missing_months_source_known"]
    revised = replace(record, value=Decimal("70.1"), published_at=datetime(2018, 7, 12, 12, tzinfo=UTC), vintage_id="synthetic-revision", quality="revised")
    assert ingest_records(db, [revised], b"synthetic-revised", "rbi")["revisions"] == 1
    later = coverage(db, datetime(2018, 7, 13, 12, tzinfo=UTC))["indicators"]["usd_inr_spot"]
    assert later["source_known_count"] == 1 and later["system_known_count"] == 0
    assert len(later["vintages"]) == 2
    assert later["calendar_unverified_years"] == [2018]
