"""Synthetic economic scenarios only; no values are live findings."""
import json
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from packages.domain.models import AdminAudit, DiscoveryHypothesis, MarketBar, ResearchEvidence
from packages.scoring.discovery import evaluate, persist, replay, rules

UTC = timezone.utc
AS_OF = datetime(2026, 10, 31, 12, tzinfo=UTC)
PERIODS = [date(2026, month, 1) for month in range(2, 11)]


def add(db, key, day, value, *, source="synthetic-source-a", published=None, retrieved=None, revision="v1", frequency="monthly", synthetic=True):
    row = ResearchEvidence(indicator_key=key, indicator_or_claim=key, frequency=frequency, value_numeric=Decimal(str(value)), value_text=None, unit="synthetic units", period_start=day, period_end=day, source_name=source, source_reference="https://example.org/synthetic", retrieved_at=retrieved or datetime.combine(day, datetime.min.time(), UTC) + timedelta(hours=12), published_at=published, reliability_note="Synthetic regression scenario; no economic claim", usage_basis="Synthetic test fixture for regression only" if synthetic else "Private research with permitted source use", quality="estimated", revision_id=revision, observation_key=f"{key}:{day}:{source}:{revision}", entered_by="test")
    db.add(row)
    db.flush()
    return row


def series(db, key, values, **kwargs):
    return [add(db, key, day, value, **kwargs) for day, value in zip(PERIODS, values)]


def result(db, when=AS_OF, mode="system_known"):
    return evaluate(db, when, mode, include_test_fixtures=True)


def test_persistent_vs_isolated_and_structural_break(db):
    series(db, "persistent", [100, 101, 99, 100, 101, 99, 130, 135, 140])
    series(db, "isolated", [100, 101, 99, 100, 101, 99, 100, 101, 140])
    found = result(db)["series"]
    assert found["persistent"]["status"] == "PERSISTENT"
    assert {a["type"] for a in found["persistent"]["anomalies"]} >= {"sustained_deviation", "provisional_structural_break"}
    assert found["persistent"]["momentum"] == "rising"
    assert found["isolated"]["status"] == "ISOLATED"
    assert not found["isolated"]["persistent"]


def test_momentum_and_acceleration_are_descriptive_signals(db):
    series(db, "accelerating", [100, 101, 99, 100, 101, 99, 130, 135, 150])
    kinds = {item["type"] for item in result(db)["series"]["accelerating"]["anomalies"]}
    assert {"sustained_deviation", "momentum_change", "acceleration_change"} <= kinds


def test_gaps_staleness_and_conflicting_sources_block_inference(db):
    series(db, "gap", [100] * 6 + [140, 145, 150])
    # A missing report within the follow-up window must not count as three consecutive releases.
    db.delete(db.scalar(select(ResearchEvidence).where(ResearchEvidence.indicator_key == "gap", ResearchEvidence.period_end == date(2026, 9, 1))))
    add(db, "gap", date(2026, 1, 1), 100)
    assert result(db)["series"]["gap"]["status"] == "INCOMPLETE_HISTORY"
    series(db, "conflict", [100] * 6 + [140, 145, 150])
    add(db, "conflict", PERIODS[-1], 90, source="synthetic-source-b")
    assert result(db)["series"]["conflict"]["status"] == "CONFLICTING"
    assert len(result(db)["series"]["conflict"]["conflicting_observations"]) == 2
    series(db, "stale", [100] * 6 + [140, 145, 150])
    assert result(db, AS_OF + timedelta(days=120))["series"]["stale"]["status"] == "STALE"


def test_cross_indicator_pattern_is_provisional_and_spurious_price_pair_not_candidate(db):
    left = series(db, "fpi_equity_net", [100] * 6 + [50, 45, 40])
    right = series(db, "dii_equity_net", [100] * 6 + [150, 155, 160], source="synthetic-source-b")
    discovered = result(db)
    assert len(discovered["relationships"]) == 1
    candidate = discovered["relationships"][0]
    assert candidate["status"] == "provisional_unexplained"
    assert candidate["hypothesis"]["causal_status"] == "unverified_proposal"
    assert candidate["hypothesis"]["competing_explanations"]
    assert {item["id"] for item in candidate["observations"]} == {item.id for item in left[-3:] + right[-3:]}
    assert candidate["hypothesis"]["implications_1_3_months"] != candidate["hypothesis"]["implications_3_6_months"]
    # Co-moving independent prices do not create an economic mechanism candidate.
    market = MarketBar(instrument_id="nifty50", provider="yahoo", provider_symbol="^NSEI", market="NSE", currency="INR", exchange_timezone="Asia/Kolkata", session_date=date(2026, 10, 1), open=Decimal(100), high=Decimal(100), low=Decimal(100), close=Decimal(100), adjusted_close=None, volume=10, price_basis="raw", source_url="https://finance.yahoo.com/quote/%5ENSEI/", retrieved_at=AS_OF, quality="secondary_unverified", content_hash="synthetic-market-price")
    db.add(market)
    db.flush()
    assert len(result(db)["relationships"]) == 1


def test_new_cross_sector_question_is_independent_of_six_cycle_catalog(db):
    series(db, "banking_system_liquidity", [100] * 6 + [140, 145, 150])
    series(db, "bank_credit_growth", [100] * 6 + [60, 55, 50], source="synthetic-source-b")
    candidate = result(db)["relationships"][0]
    assert candidate["relationship_id"] == "liquidity_credit_disconnect"
    assert candidate["hypothesis"]["causal_status"] == "unverified_proposal"
    from packages.scoring.cycle_intelligence import catalog
    assert "liquidity_credit_disconnect" not in catalog()["cycles"]


def test_source_known_retrospective_and_system_known_no_lookahead(db):
    for day, value in zip(PERIODS, [100] * 6 + [140, 145, 150]):
        publication = datetime.combine(day, datetime.min.time(), UTC) + timedelta(days=10)
        add(db, "episode", day, value, published=publication, retrieved=AS_OF + timedelta(days=20))
    historical = datetime(2026, 10, 20, tzinfo=UTC)
    assert "episode" not in result(db, historical)["series"]
    retrospective = result(db, historical, "source_known")
    assert retrospective["series"]["episode"]["status"] == "PERSISTENT"
    assert retrospective["analysis_basis"] == "retrospective_source_reconstruction"
    add(db, "episode", PERIODS[-1], 100, source="synthetic-source-a", published=AS_OF + timedelta(days=2), retrieved=AS_OF + timedelta(days=30), revision="v2")
    assert retrospective["input_vintages"] == result(db, historical, "source_known")["input_vintages"]
    assert result(db, historical, "source_known")["series"]["episode"]["status"] == "PERSISTENT"


def test_snapshot_replay_and_candidate_isolation_from_catalog(db, monkeypatch, tmp_path):
    series(db, "fpi_equity_net", [100] * 6 + [50, 45, 40], synthetic=False)
    series(db, "dii_equity_net", [100] * 6 + [150, 155, 160], source="source-b", synthetic=False)
    snapshot = persist(db, AS_OF, "synthetic-discovery-1", "analyst", recorded_at=AS_OF)
    original = replay(snapshot)
    assert original["result"]["candidate_hypotheses"]
    assert original["input_vintages"]
    add(db, "fpi_equity_net", PERIODS[-1], 100, retrieved=AS_OF + timedelta(days=1), revision="v2", synthetic=False)
    bad_rules = tmp_path / "different.yaml"
    bad_rules.write_text("version: unrelated\n")
    import packages.scoring.discovery as discovery
    monkeypatch.setattr(discovery, "RULES_PATH", bad_rules)
    assert replay(snapshot) == original
    from packages.scoring.cycle_intelligence import catalog
    assert set(catalog()["cycles"]) == {"fx", "energy", "flows", "earnings", "it", "global"}


def test_private_api_scopes_and_hypothesis_audit(db, monkeypatch):
    from types import SimpleNamespace
    from packages.jobs.operators import issue
    import apps.api.main as api
    series(db, "fpi_equity_net", [100] * 6 + [50, 45, 40], synthetic=False)
    series(db, "dii_equity_net", [100] * 6 + [150, 155, 160], source="source-b", synthetic=False)
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setattr(api, "LIMITER", SimpleNamespace(allow=lambda *args, **kwargs: True))
    monkeypatch.setenv("APP_ENV", "development")
    read = issue(db, "reader", {"research:read"}, 1)
    write = issue(db, "writer", {"research:write"}, 1)
    client = TestClient(api.app)
    assert client.get("/api/v1/research/discovery").status_code == 401
    assert client.get("/api/v1/research/discovery", headers={"X-Admin-Token": write}).status_code == 403
    assert client.get("/api/v1/research/discovery", headers={"X-Admin-Token": read}).status_code == 200
    assert client.post("/api/v1/research/discovery/snapshots", json={"snapshot_key": "synthetic-api-snapshot"}, headers={"X-Admin-Token": read}).status_code == 403
    snap_response = client.post("/api/v1/research/discovery/snapshots", json={"snapshot_key": "synthetic-api-snapshot", "as_of": AS_OF.isoformat()}, headers={"X-Admin-Token": write})
    assert snap_response.status_code == 200, snap_response.text
    snap_id = snap_response.json()["id"]
    frozen = client.get(f"/api/v1/research/discovery/snapshots/{snap_id}", headers={"X-Admin-Token": read})
    assert frozen.status_code == 200
    candidate = frozen.json()["result"]["candidate_hypotheses"][0]
    payload = {"snapshot_id": snap_id, "candidate_key": candidate["key"], "investigation_question": "Does domestic buying respond to foreign selling?"}
    assert client.post("/api/v1/research/discovery/hypotheses", json=payload, headers={"X-Admin-Token": read}).status_code == 403
    opened = client.post("/api/v1/research/discovery/hypotheses", json=payload, headers={"X-Admin-Token": write})
    assert opened.status_code == 200, opened.text
    assert opened.json()["catalog_promoted"] is False
    assert client.post("/api/v1/research/discovery/hypotheses", json=payload, headers={"X-Admin-Token": write}).json()["duplicate"]
    hypothesis_id = opened.json()["id"]
    assert client.patch(f"/api/v1/research/discovery/hypotheses/{hypothesis_id}", json={"status": "investigating"}, headers={"X-Admin-Token": read}).status_code == 403
    assert client.patch(f"/api/v1/research/discovery/hypotheses/{hypothesis_id}", json={"status": "investigating"}, headers={"X-Admin-Token": write}).status_code == 200
    assert db.get(DiscoveryHypothesis, hypothesis_id).status == "investigating"
    historical = client.get("/api/v1/research/discovery", params={"as_of": AS_OF.isoformat()}, headers={"X-Admin-Token": read})
    assert historical.status_code == 200
    assert historical.json()["investigations"] == []  # a later status cannot leak backward
    assert {item.action for item in db.scalars(select(AdminAudit)).all()} >= {"discovery_snapshot_record", "discovery_hypothesis_open", "discovery_hypothesis_status"}
