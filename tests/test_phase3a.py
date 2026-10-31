"""Phase 3A provenance, conservative interpretation, and replay regressions."""
import hashlib
import base64
from datetime import datetime, timedelta, timezone

import pytest
from sqlalchemy import select

from packages.connectors.india_release import ReleaseManifest, parse_release_package
from packages.domain.models import Observation
from packages.domain.store import observations_at
from packages.jobs.ingest import ingest_records
from packages.jobs.operators import issue
from packages.scoring.external_liquidity import external_liquidity_view

UTC = timezone.utc
CSV = b"indicator_id,value,unit,period_start,period_end,vintage_id,quality\nusd_inr_spot,81.25,INR_per_USD,2024-01-02,2024-01-02,release-1,verified\n"


def manifest(**overrides):
    values = dict(provider="rbi", source_reference="https://www.rbi.org.in/reference", publication_evidence_url="https://www.rbi.org.in/release", published_at=datetime(2024, 1, 3, 12, tzinfo=UTC), source_sha256=hashlib.sha256(b"publisher-original").hexdigest(), redistribution_basis="written-permission", definition_version="rbi-reference-v1")
    values.update(overrides)
    return ReleaseManifest(**values)


def test_release_package_requires_rights_time_evidence_and_approved_units():
    rows = parse_release_package(CSV, manifest())
    assert rows[0].published_at == datetime(2024, 1, 3, 12, tzinfo=UTC)
    assert rows[0].provider == "rbi" and rows[0].unit == "INR_per_USD"
    for bad in (manifest(redistribution_basis="publicly-viewable"), manifest(published_at=datetime(2024, 1, 3, 12)), manifest(publication_evidence_url="https://evil.example/release"), manifest(provider="nsdl")):
        with pytest.raises(ValueError):
            parse_release_package(CSV, bad)
    with pytest.raises(ValueError):
        parse_release_package(CSV.replace(b"INR_per_USD", b"USD_per_INR"), manifest())
    with pytest.raises(ValueError):
        parse_release_package(CSV.replace(b"2024-01-02,2024-01-02", b"2024-01-04,2024-01-04"), manifest())
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
    assert external_liquidity_view(_dashboard(fx=3))["classification"] == "DEPRECIATION_WITHOUT_CONFIRMED_PRESSURE"
    assert external_liquidity_view(_dashboard(fx=3, fpi=-20000))["classification"] == "EXTERNAL_FINANCING_PRESSURE"
    stressed = external_liquidity_view(_dashboard(fx=3, fpi=-20000, reserves=-4, oil=110))
    assert stressed["classification"] == "REINFORCING_STRESS_WATCH"
    assert stressed["cycle"]["score"] is None  # no invented score from the narrative classification
    assert "not proof of causality" in stressed["explanation"]
    assert external_liquidity_view(_dashboard(fx=1, fpi=-20000, reserves=-4))["classification"] == "NO_CONFIRMED_FX_PRESSURE"


def test_release_api_requires_scoped_operator_and_original_hash(db, monkeypatch):
    from fastapi.testclient import TestClient
    import apps.api.main as api
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "db")
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    token = issue(db, "release-reviewer", {"imports:write"}, 1, "release-reviewer-test-token")
    payload = {**manifest().__dict__, "published_at": manifest().published_at.isoformat(), "original_source_base64": base64.b64encode(b"publisher-original").decode(), "extract_csv_base64": base64.b64encode(CSV).decode()}
    client = TestClient(api.app)
    assert client.post("/api/v1/admin/imports/release", json=payload).status_code == 401
    headers = {"X-Admin-Token": token}
    bad = {**payload, "source_sha256": "0" * 64}
    assert client.post("/api/v1/admin/imports/release", json=bad, headers=headers).status_code == 422
    assert client.post("/api/v1/admin/imports/release", json=payload, headers=headers).json()["inserted"] == 1
    assert client.post("/api/v1/admin/imports/release", json=payload, headers=headers).json()["duplicate"] == 1
    response = client.get("/api/v1/external-liquidity")
    assert response.status_code == 200
    assert response.json()["classification"] == "INSUFFICIENT_EVIDENCE"
