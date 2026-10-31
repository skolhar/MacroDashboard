"""Phase 3A provenance, conservative interpretation, and replay regressions."""
import hashlib
import base64
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace

import pytest
from sqlalchemy import select

from packages.connectors.india_release import ReleaseManifest, parse_release_package
from packages.connectors.base import SourceObservation
from packages.domain.calendar import recent_sessions
from packages.domain.models import Observation, SourceReleaseReview
from packages.domain.store import observations_at
from packages.jobs.ingest import ingest_records
from packages.jobs.operators import issue
from packages.jobs.sync_registry import sync_registry
from packages.scoring.external_liquidity import external_liquidity_view

UTC = timezone.utc
CSV = b"indicator_id,value,unit,period_start,period_end,vintage_id,quality\nusd_inr_spot,81.25,INR_per_USD,2018-07-06,2018-07-06,release-1,verified\n"


def manifest(**overrides):
    values = dict(provider="rbi", source_reference="https://www.rbi.org.in/reference", publication_evidence_url="https://www.rbi.org.in/release", published_at=datetime(2018, 7, 9, 12, tzinfo=UTC), source_sha256=hashlib.sha256(b"publisher-original").hexdigest(), redistribution_basis="written-permission", definition_version="rbi-reference-v1")
    values.update(overrides)
    return ReleaseManifest(**values)


def test_release_package_requires_rights_time_evidence_and_approved_units():
    rows = parse_release_package(CSV, manifest())
    assert rows[0].published_at == datetime(2018, 7, 9, 12, tzinfo=UTC)
    assert rows[0].provider == "rbi" and rows[0].unit == "INR_per_USD"
    for bad in (manifest(redistribution_basis="publicly-viewable"), manifest(published_at=datetime(2024, 1, 3, 12)), manifest(publication_evidence_url="https://evil.example/release"), manifest(provider="nsdl")):
        with pytest.raises(ValueError):
            parse_release_package(CSV, bad)
    with pytest.raises(ValueError):
        parse_release_package(CSV.replace(b"INR_per_USD", b"USD_per_INR"), manifest())
    with pytest.raises(ValueError):
        parse_release_package(CSV.replace(b"2018-07-06,2018-07-06", b"2018-07-10,2018-07-10"), manifest())
    with pytest.raises(ValueError):
        parse_release_package(CSV.replace(b"usd_inr_spot", b"rbi_net_forward_usd"), manifest())


def test_release_import_is_idempotent_and_preserves_original_hash_and_vintage(db):
    rows = parse_release_package(CSV, manifest())
    original = b"publisher-original"
    first = ingest_records(db, rows, CSV, "rbi", original_raw=original)
    second = ingest_records(db, rows, CSV, "rbi", original_raw=original)
    assert (first["inserted"], second["duplicate"]) == (1, 1)
    record = db.scalar(select(Observation).where(Observation.provider == "rbi"))
    assert record.content_hash == hashlib.sha256(original).hexdigest()
    assert record.published_at == rows[0].published_at
    assert record.ingested_at > record.published_at
    assert observations_at(db, "usd_inr_spot", record.published_at - timedelta(seconds=1), demo=False) == []
    assert observations_at(db, "usd_inr_spot", record.published_at + timedelta(seconds=1), demo=False) == []  # system-known replay
    assert len(observations_at(db, "usd_inr_spot", record.ingested_at + timedelta(seconds=1), demo=False)) == 1
    assert len(observations_at(db, "usd_inr_spot", record.published_at + timedelta(seconds=1), mode="source_known", demo=False)) == 1


def _dashboard(fx=None, fpi=None, reserves=None, oil=None):
    values = {"usd_inr_spot": fx, "fpi_equity_net_inr": fpi, "fx_gross_reserves_usd": reserves, "brent_usd": oil}
    metrics = [{"id": id, "scored_feature": value, "status": "verified" if value is not None else "DATA_UNAVAILABLE"} for id, value in values.items()]
    return {"as_of": "2026-10-31T00:00:00+00:00", "mode": "live", "metrics": metrics, "cycles": [{"id": "fx", "score": None, "coverage": 0.4}], "alerts": [], "source_health": {}, "data_confidence": {"score": None}}


def test_fx_classification_requires_independent_confirmations():
    assert external_liquidity_view(_dashboard())["classification"] == "INSUFFICIENT_EVIDENCE"
    assert external_liquidity_view(_dashboard(fx=3))["classification"] == "AWAITING_FOREIGN_FLOW_EVIDENCE"
    assert external_liquidity_view(_dashboard(fx=3, fpi=1000))["classification"] == "DEPRECIATION_WITH_COUNTER_FLOW_EVIDENCE"
    assert external_liquidity_view(_dashboard(fx=3, fpi=-20000))["classification"] == "FINANCING_PRESSURE_AWAITING_LIQUIDITY_EVIDENCE"
    assert external_liquidity_view(_dashboard(fx=3, fpi=-20000, reserves=-1, oil=90))["classification"] == "FINANCING_PRESSURE_WITH_COUNTER_LIQUIDITY_EVIDENCE"
    assert external_liquidity_view(_dashboard(fx=3, fpi=-20000, reserves=-1))["evidence_status"]["elevated_oil"] == "UNKNOWN"
    stressed = external_liquidity_view(_dashboard(fx=3, fpi=-20000, reserves=-4, oil=110))
    assert stressed["classification"] == "REINFORCING_STRESS_WATCH"
    assert stressed["cycle"]["score"] is None  # no invented score from the narrative classification
    assert "not proof of causality" in stressed["explanation"]
    assert external_liquidity_view(_dashboard(fx=1, fpi=-20000, reserves=-4))["classification"] == "NO_CONFIRMED_FX_PRESSURE"


def test_release_api_requires_scoped_operator_and_original_hash(db, monkeypatch, tmp_path):
    from fastapi.testclient import TestClient
    import apps.api.main as api
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "db")
    monkeypatch.setenv("SOURCE_ARCHIVE_ROOT", str(tmp_path / "originals"))
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setattr(api, "LIMITER", SimpleNamespace(allow=lambda *args: True))
    token = issue(db, "release-submitter", {"imports:write", "releases:approve"}, 1, "release-submitter-test-token")
    reviewer_token = issue(db, "independent-reviewer", {"releases:approve"}, 1, "independent-reviewer-test-token")
    payload = {**manifest().__dict__, "published_at": manifest().published_at.isoformat(), "original_source_base64": base64.b64encode(b"publisher-original").decode(), "extract_csv_base64": base64.b64encode(CSV).decode()}
    client = TestClient(api.app)
    assert client.post("/api/v1/admin/imports/release", json=payload).status_code == 401
    assert client.post("/api/v1/admin/releases/archive", content=b"publisher-original", headers={"X-Source-Provider": "rbi", "Content-Type": "application/octet-stream"}).status_code == 401
    headers = {"X-Admin-Token": token}
    assert client.post("/api/v1/admin/releases/archive", content=b"x" * 750_001, headers={**headers, "X-Source-Provider": "rbi", "Content-Type": "application/octet-stream"}).status_code == 413
    archived = client.post("/api/v1/admin/releases/archive", content=b"publisher-original", headers={**headers, "X-Source-Provider": "rbi", "Content-Type": "application/octet-stream"})
    assert archived.status_code == 200
    assert archived.json()["sha256"] == manifest().source_sha256
    manual = b"indicator_id,value,unit,period_start,period_end,published_at,vintage_id,source_reference,quality\nusd_inr_spot,81.25,INR_per_USD,2018-07-06,2018-07-06,2018-07-09T12:00:00Z,manual-bypass,https://www.rbi.org.in/reference,verified\n"
    bypass = client.post("/api/v1/admin/imports/csv", content=manual, headers={**headers, "X-Source-Provider": "rbi", "X-License-Attestation": "public-redistributable", "Content-Type": "text/csv"})
    assert bypass.status_code == 422
    review_payload = {**manifest().__dict__, "published_at": manifest().published_at.isoformat(), "extract_sha256": hashlib.sha256(CSV).hexdigest(), "original_archive_reference": archived.json()["reference"], "publication_evidence_note": "Independent fixture release notice dated 9 July 2018.", "entitlement_reference": "archive://fixture/written-permission"}
    submitted = client.post("/api/v1/admin/releases/reviews", json=review_payload, headers=headers)
    assert submitted.status_code == 200
    review_id = submitted.json()["review_id"]
    payload["review_id"] = review_id
    assert client.post("/api/v1/admin/imports/release", json=payload, headers=headers).status_code == 422  # pending
    approval = {"publication_evidence_verified": True, "entitlement_verified": True, "review_note": "Checked the separate fixture notice and permission record."}
    assert client.post(f"/api/v1/admin/releases/reviews/{review_id}/approve", json=approval, headers=headers).status_code == 409  # no self approval
    reviewer_headers = {"X-Admin-Token": reviewer_token}
    assert client.post("/api/v1/admin/releases/archive", content=b"publisher-original", headers={**reviewer_headers, "X-Source-Provider": "rbi", "Content-Type": "application/octet-stream"}).status_code == 403
    reviewed = client.get(f"/api/v1/admin/releases/reviews/{review_id}", headers=reviewer_headers)
    assert reviewed.json()["source_sha256"] == manifest().source_sha256
    assert client.get(f"/api/v1/admin/releases/reviews/{review_id}/original", headers=reviewer_headers).content == b"publisher-original"
    assert client.post(f"/api/v1/admin/releases/reviews/{review_id}/approve", json=approval, headers=reviewer_headers).status_code == 200
    assert client.post(f"/api/v1/admin/releases/reviews/{review_id}/approve", json=approval, headers=reviewer_headers).status_code == 409
    bad = {**payload, "source_sha256": "0" * 64}
    assert client.post("/api/v1/admin/imports/release", json=bad, headers=headers).status_code == 422
    assert client.post("/api/v1/admin/imports/release", json=payload, headers=headers).json()["inserted"] == 1
    assert client.post("/api/v1/admin/imports/release", json=payload, headers=headers).json()["duplicate"] == 1
    stored = db.scalar(select(SourceReleaseReview).where(SourceReleaseReview.id == review_id))
    assert stored.approved_by == "independent-reviewer"
    assert stored.publication_evidence_note and stored.entitlement_reference
    observation = db.scalar(select(Observation).where(Observation.provider == "rbi"))
    assert observation.release_review_id == review_id and observation.rate_kind == "published_reference_rate"
    with pytest.raises(ValueError, match="Conflicting reviewed release"):
        ingest_records(db, parse_release_package(CSV, manifest()), CSV, "rbi", original_raw=b"changed publisher bytes", release_review_id=review_id)
    response = client.get("/api/v1/external-liquidity")
    assert response.status_code == 200
    assert response.json()["classification"] == "INSUFFICIENT_EVIDENCE"


def test_live_api_partial_counter_stale_and_point_in_time(db, monkeypatch):
    """Synthetic test records in a private DB exercise the complete live read path."""
    from fastapi.testclient import TestClient
    import apps.api.main as api
    sync_registry(db)
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    client = TestClient(api.app)
    sessions = recent_sessions(datetime(2026, 10, 30, tzinfo=UTC), "india", 60)
    published = datetime(2026, 10, 30, 10, tzinfo=UTC)

    def add_series(indicator, provider, unit, dates, values, raw):
        records = [SourceObservation(indicator, Decimal(str(value)), unit, day, day, published, provider, "https://example.org/unit-test-only", f"synthetic-test-{indicator}-{day}") for day, value in zip(dates, values)]
        return ingest_records(db, records, raw, provider)

    add_series("usd_inr_spot", "fbil", "INR_per_USD", sessions[-21:], [80 + n * .17 for n in range(21)], b"synthetic-fx-test")
    current = datetime.now(UTC).isoformat()
    first = client.get("/api/v1/external-liquidity", params={"as_of": current}).json()
    assert first["classification"] == "AWAITING_FOREIGN_FLOW_EVIDENCE"
    assert first["evidence_status"]["foreign_equity_selling"] == "UNKNOWN"
    fx = next(m for m in first["metrics"] if m["id"] == "usd_inr_spot")
    assert fx["display_name"] == "USD/INR published FBIL reference rate"
    assert fx["rate_kind"] == "published_reference_rate"
    assert fx["transform"] == "change_pct_20" and fx["scored_feature"] > 2
    assert client.get("/api/v1/indicators/usd_inr_spot/series", params={"as_of": current}).json()["items"][-1]["rate_kind"] == "published_reference_rate"

    add_series("fpi_equity_net_inr", "nsdl", "INR_cr", sessions[-20:], [-1000] * 20, b"synthetic-fpi-test")
    second = client.get("/api/v1/external-liquidity", params={"as_of": datetime.now(UTC).isoformat()}).json()
    assert second["classification"] == "FINANCING_PRESSURE_AWAITING_LIQUIDITY_EVIDENCE"
    assert second["evidence_status"]["gross_reserve_decline"] == "UNKNOWN"
    weekly = [date(2026, 8, 7) + timedelta(weeks=n) for n in range(13)]
    add_series("fx_gross_reserves_usd", "rbi", "USD_bn", weekly, [500] * 13, b"synthetic-reserve-test")
    add_series("brent_usd", "licensed_brent", "USD_per_bbl", sessions, [90] * len(sessions), b"synthetic-oil-test")
    third = client.get("/api/v1/external-liquidity", params={"as_of": datetime.now(UTC).isoformat()}).json()
    assert third["classification"] == "FINANCING_PRESSURE_WITH_COUNTER_LIQUIDITY_EVIDENCE"
    assert third["evidence_status"]["gross_reserve_decline"] == "COUNTER"
    assert third["evidence_status"]["elevated_oil"] == "COUNTER"
    stale = client.get("/api/v1/external-liquidity", params={"as_of": "2026-11-06T18:30:00+05:30"}).json()
    assert stale["classification"] == "INSUFFICIENT_EVIDENCE"
    assert stale["evidence_status"]["depreciation"] == "UNKNOWN"
    assert next(m for m in stale["metrics"] if m["id"] == "usd_inr_spot")["status"] == "stale"
    vendor = SourceObservation("usd_inr_spot", Decimal("83.40"), "INR_per_USD", sessions[-1], sessions[-1], published + timedelta(hours=1), "licensed_vendor", "https://example.org/unit-test-only", "synthetic-test-vendor-switch")
    ingest_records(db, [vendor], b"synthetic-conflicting-rate-definition", "licensed_vendor")
    switched = client.get("/api/v1/external-liquidity", params={"as_of": datetime.now(UTC).isoformat()}).json()
    assert switched["classification"] == "INSUFFICIENT_EVIDENCE"
    assert next(m for m in switched["metrics"] if m["id"] == "usd_inr_spot")["history_status"] == "insufficient_or_gap"
    past = client.get("/api/v1/replay", params={"as_of": "2026-10-30T18:30:00+05:30", "vintage_mode": "system_known", "ruleset": "v2"}).json()
    assert next(m for m in past["metrics"] if m["id"] == "usd_inr_spot")["status"] == "DATA_UNAVAILABLE"
