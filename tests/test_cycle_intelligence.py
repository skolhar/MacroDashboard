"""All economic values here are synthetic fixtures, never live findings."""
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import select
from sqlalchemy import create_engine, text
from packages.domain.models import ResearchEvidence, ResearchInterpretation, CycleAssessmentSnapshot, MarketBar, AdminAudit
from packages.scoring.cycle_intelligence import catalog, evaluate, persist_assessment, replay_snapshot

UTC = timezone.utc
NOW = datetime(2026, 10, 31, 18, tzinfo=UTC)


def instant(day, hour=12):
    return datetime.combine(day, time(hour), UTC)


def observation(db, key, day, frequency="monthly", value="synthetic", source="Synthetic A", retrieved=None, revision="v1", claim=None):
    row = ResearchEvidence(indicator_key=key, indicator_or_claim=claim or key, frequency=frequency, value_text=value, value_numeric=None, unit=None, period_start=day, period_end=day, source_name=source, source_reference="https://example.org/synthetic-test", retrieved_at=retrieved or instant(day), published_at=None, reliability_note="Synthetic scenario; no actual economic observation", usage_basis="Synthetic test fixture for regression only", quality="estimated", revision_id=revision, observation_key=f"{key}:{source}:{day}:{revision}", entered_by="fixture")
    db.add(row)
    db.flush()
    return row


def interpretation(db, observed, mechanism, stance, kind, related=None, at=None, actor="analyst", revision="v1"):
    cycle = "flows"
    row = ResearchInterpretation(observation_id=observed.id, related_observation_id=related.id if related else None, cycle_id=cycle, mechanism_id=mechanism, evidence_type=kind, stance=stance, rationale="The synthetic actor response is interpreted relative to its stated prior driver; causal attribution remains tentative.", alternatives_json=json.dumps(["Seasonal portfolio rebalancing", "Source-definition change"]), interpretation_key=f"{observed.id}:{mechanism}:{kind}:{actor}:{revision}", revision_id=revision, supersedes_id=None, assessed_at=at or observed.retrieved_at + timedelta(hours=1), entered_by=actor)
    db.add(row)
    db.flush()
    return row


def feedback(db, day, stance="supports", suffix=""):
    driver = observation(db, f"valuation_driver{suffix}", day)
    response = observation(db, f"flow_response{suffix}", day)
    interpretation(db, response, "savings_loop", stance, "feedback_link", driver)
    return response


def initial_regime(db):
    feedback(db, date(2026, 7, 1))
    feedback(db, date(2026, 8, 1))
    trend = observation(db, "sip_net", date(2026, 8, 1))
    interpretation(db, trend, "savings_loop", "supports", "trend")
    as_of = datetime(2026, 8, 15, 16, tzinfo=UTC)
    result = evaluate(db, as_of)
    assert cycle(result)["state"] == "mature / persistent"
    snapshot = persist_assessment(db, as_of, "synthetic-prior-regime", "test", as_of)
    return snapshot


def transition(db, second_break=False):
    feedback(db, date(2026, 9, 1), "contradicts")
    correction = observation(db, "redemption_net", date(2026, 9, 15))
    interpretation(db, correction, "redemption_loop", "supports", "corrective_response")
    correction2 = observation(db, "redemption_net", date(2026, 10, 1))
    interpretation(db, correction2, "redemption_loop", "supports", "corrective_response")
    if second_break:
        feedback(db, date(2026, 10, 1), "contradicts")


def cycle(result, cid="flows"):
    return next(item for item in result["cycles"] if item["id"] == cid)


def test_catalog_and_rules_are_versioned_with_falsifiers():
    cfg = catalog()
    assert cfg["version"] == "cycle-mechanisms-v1"
    assert set(cfg["cycles"]) == {"fx", "energy", "flows", "earnings", "it", "global"}
    for definition in cfg["cycles"].values():
        assert {m["role"] for m in definition["mechanisms"]} == {"reinforcing", "balancing"}
        assert definition["alternatives"] and definition["invalidated_when"]


def test_two_trends_do_not_prove_feedback_and_missing_is_not_counter(db):
    for day in (date(2026, 9, 1), date(2026, 10, 1)):
        row = observation(db, "sip_net", day)
        interpretation(db, row, "savings_loop", "supports", "trend")
    assessed = cycle(evaluate(db, NOW))
    assert assessed["state"] == "indeterminate"
    assert assessed["reinforcing"]["status"] == "directional_only"
    assert assessed["balancing"]["status"] == "missing"
    assert assessed["candidate"] is None


def test_feedback_links_without_independent_trend_remain_indeterminate(db):
    feedback(db, date(2026, 9, 1))
    feedback(db, date(2026, 10, 1))
    assessed = cycle(evaluate(db, NOW))
    assert assessed["state"] == "indeterminate"
    assert assessed["reinforcing"]["status"] == "missing"


def test_strengthening_requires_new_supported_link_after_recorded_emergence(db):
    feedback(db, date(2026, 7, 1))
    trend = observation(db, "sip_net", date(2026, 7, 1))
    interpretation(db, trend, "savings_loop", "supports", "trend")
    emerging_at = datetime(2026, 7, 15, 16, tzinfo=UTC)
    assert cycle(evaluate(db, emerging_at))["state"] == "emerging"
    persist_assessment(db, emerging_at, "synthetic-emergence", "test", emerging_at)
    feedback(db, date(2026, 8, 1))
    assessed = cycle(evaluate(db, datetime(2026, 8, 15, 16, tzinfo=UTC)))
    assert assessed["state"] == "strengthening"


def test_feedback_link_requires_distinct_actor_response_and_explicit_rationale(db):
    import apps.api.main as api
    from fastapi import HTTPException
    driver = observation(db, "valuation_driver", date(2026, 9, 1))
    response = observation(db, "flow_response", date(2026, 9, 1))
    payload = api.ResearchInterpretationRequest(observation_id=response.id, related_observation_id=driver.id, cycle_id="flows", mechanism_id="savings_loop", evidence_type="feedback_link", stance="supports", rationale="Synthetic return expectations changed the allocation response, subject to a competing seasonal explanation.", alternative_explanations=["Seasonal rotation"], interpretation_key="synthetic-feedback-1", revision_id="v1")
    import apps.api.main as main
    from unittest.mock import patch
    with patch.object(main, "DB", db.bind):
        assert main.add_research_interpretation(payload, {"operator_id": "analyst"})["status"] == "recorded"
        with pytest.raises(HTTPException):
            main.add_research_interpretation(payload.model_copy(update={"related_observation_id": response.id, "interpretation_key": "synthetic-feedback-2"}), {"operator_id": "analyst"})
    assert db.scalars(select(ResearchInterpretation)).first().rationale


def test_prior_regime_and_ordered_balancing_required(db):
    transition(db)
    assert cycle(evaluate(db, NOW))["state"] == "indeterminate"  # no recorded prior regime
    db.rollback()


def test_balancing_before_reinforcement_does_not_trigger(db):
    old = observation(db, "redemption_net", date(2026, 5, 1))
    interpretation(db, old, "redemption_loop", "supports", "corrective_response")
    initial_regime(db)
    feedback(db, date(2026, 9, 1), "contradicts")
    assessed = cycle(evaluate(db, NOW))
    assert assessed["state"] == "indeterminate"
    assert assessed["candidate"] is None


def test_weakening_then_reversing_requires_feedback_and_response_sequence(db):
    prior = initial_regime(db)
    transition(db)
    weak = cycle(evaluate(db, NOW))
    assert weak["state"] == "weakening"
    assert weak["prior_assessment_id"] == prior.id
    assert weak["candidate"]["type"] == "reinforcing_force_losing_momentum"
    assert len({item["period_end"] for item in weak["candidate"]["supporting_observations"]}) >= 2
    feedback(db, date(2026, 10, 1), "contradicts")
    reverse = cycle(evaluate(db, NOW))
    assert reverse["state"] == "reversing"
    assert reverse["candidate"]["type"] == "balancing_force_dominance"


def test_one_indicator_reversal_does_not_reverse_cycle(db):
    initial_regime(db)
    trend = observation(db, "sip_net", date(2026, 9, 1))
    interpretation(db, trend, "savings_loop", "contradicts", "trend")
    for day in (date(2026, 9, 15), date(2026, 10, 1)):
        row = observation(db, "redemption_net", day)
        interpretation(db, row, "redemption_loop", "supports", "corrective_response")
    assessed = cycle(evaluate(db, NOW))
    assert assessed["state"] != "reversing"
    assert assessed["candidate"] is None


def test_conflicting_sources_and_free_text_do_not_conflate_indicators(db):
    a = observation(db, "series_a", date(2026, 10, 1), value="up", source="Synthetic A", claim="inflows")
    b = observation(db, "series_b", date(2026, 10, 1), value="up", source="Synthetic B", claim="inflows")
    assert a.indicator_or_claim == b.indicator_or_claim and a.indicator_key != b.indicator_key
    interpretation(db, a, "savings_loop", "supports", "trend")
    interpretation(db, b, "savings_loop", "supports", "trend")
    assessed = cycle(evaluate(db, NOW))
    assert len(assessed["reinforcing"]["supporting_evidence"]) == 2
    conflicting = observation(db, "series_a", date(2026, 10, 1), value="down", source="Synthetic C", claim="inflows")
    interpretation(db, conflicting, "savings_loop", "contradicts", "trend")
    assessed = cycle(evaluate(db, NOW))
    assert assessed["reinforcing"]["status"] == "conflicting"
    assert assessed["state"] == "conflicting"
    assert assessed["conflicting_source_observations"]


def test_cadence_staleness_and_market_confirmation(db):
    old = date(2026, 7, 1)
    for key, frequency in (("monthly_old", "monthly"), ("quarterly_old", "quarterly")):
        row = observation(db, key, old, frequency=frequency)
        interpretation(db, row, "savings_loop", "supports", "trend")
    assessed = cycle(evaluate(db, NOW))
    assert [item["indicator_key"] for item in assessed["reinforcing"]["stale_evidence"]] == ["monthly_old"]
    assert [item["indicator_key"] for item in assessed["reinforcing"]["supporting_evidence"]] == ["quarterly_old"]
    bars = [MarketBar(instrument_id="nifty50", provider="yahoo", provider_symbol="^NSEI", market="NSE", currency="INR", exchange_timezone="Asia/Kolkata", session_date=day, open=Decimal(value), high=Decimal(value), low=Decimal(value), close=Decimal(value), adjusted_close=None, volume=100, price_basis="raw", source_url="https://finance.yahoo.com/quote/%5ENSEI/", retrieved_at=instant(date(2026, 10, 20)), quality="secondary_unverified", content_hash=f"synthetic-{day}") for day, value in ((date(2026, 9, 1), 100), (date(2026, 10, 1), 110))]
    db.add(bars[0])
    db.flush()
    assert evaluate(db, NOW)["market_confirmation"]["nifty50"]["status"] == "INCOMPLETE_STALE"
    db.add(bars[1])
    db.flush()
    result = evaluate(db, NOW)
    assert result["market_confirmation"]["nifty50"]["status"] == "STALE"
    assert result["market_confirmation"]["nifty50"]["change_pct"] == 10
    assert all(c["state"] == "indeterminate" for c in result["cycles"])
    assert {o["horizon"] for o in result["outlooks"]} == {"1-3 months", "3-6 months"}


def test_historical_snapshot_freezes_inputs_revisions_and_catalog(db, monkeypatch, tmp_path):
    prior = initial_regime(db)
    replay = replay_snapshot(prior)
    original_ids = replay["evidence_ids"]
    assert replay["catalog_version"] == "cycle-mechanisms-v1"
    assert replay["rule_version"] == "cycle-evaluation-v2"
    assert replay["input_revisions"]["observations"]
    # A later vendor revision of the same source period is not known in August.
    revised = observation(db, "sip_net", date(2026, 8, 1), value="revised", retrieved=instant(date(2026, 10, 1)), revision="v2")
    interpretation(db, revised, "savings_loop", "contradicts", "trend", at=instant(date(2026, 10, 1), 13), revision="v2")
    assert cycle(evaluate(db, prior.as_of))["state"] == "mature / persistent"
    assert replay_snapshot(prior)["evidence_ids"] == original_ids
    assert replay_snapshot(prior)["assessment"] == replay["assessment"]
    late = observation(db, "late_monthly", date(2026, 7, 1), retrieved=instant(date(2026, 10, 1)), revision="late")
    interpretation(db, late, "savings_loop", "supports", "trend", at=instant(date(2026, 10, 1), 13))
    assert late.id not in evaluate(db, prior.as_of)["used_evidence_ids"]
    import packages.scoring.cycle_intelligence as engine
    changed = tmp_path / "catalog-changed.yaml"
    changed.write_text("version: future-catalog\ncycles: {}\n")
    monkeypatch.setattr(engine, "CATALOG_PATH", changed)
    assert replay_snapshot(prior)["assessment"] == replay["assessment"]
    with pytest.raises(ValueError):
        evaluate(db, NOW)


def test_investigation_preserves_candidate_snapshot_and_status_audit(db, monkeypatch):
    import apps.api.main as api
    from packages.domain.models import CycleInvestigation
    initial_regime(db)
    transition(db)
    candidate = cycle(evaluate(db, NOW))["candidate"]
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setattr(api, "evaluate_cycles", lambda session, when: evaluate(session, NOW))
    request = api.InvestigationRequest(candidate_key=candidate["key"], initial_observation="Synthetic corrective mechanism needs investigation", competing_hypotheses=["Seasonal fund rebalancing"], questions=["Does a distinct source confirm?"], confirmation_criteria="Another monthly release supports corrective flows", falsification_criteria="Feedback link and fund inflows recover")
    first = api.start_investigation(request, {"operator_id": "analyst"})
    assert api.start_investigation(request, {"operator_id": "analyst"})["duplicate"]
    detail = api.get_investigation(first["id"], {"operator_id": "analyst"})
    assert detail["evidence_snapshot"]["prior_assessment_id"]
    assert detail["evidence_snapshot"]["rule_version"] == "cycle-evaluation-v2"
    assert detail["competing_hypotheses"] == ["Seasonal fund rebalancing"]
    assert api.update_investigation(first["id"], api.InvestigationStatusRequest(status="monitoring"), {"operator_id": "analyst"})["status"] == "monitoring"
    assert db.get(CycleInvestigation, first["id"]).status == "monitoring"
    assert db.scalar(select(AdminAudit.details).where(AdminAudit.action == "research_investigation_status")).find("from=open;to=monitoring") >= 0


def test_scopes_audit_and_production_gate(db, monkeypatch):
    import apps.api.main as api
    from packages.jobs.operators import issue
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setenv("APP_ENV", "development")
    read = issue(db, "reader", {"research:read"}, 1)
    write = issue(db, "writer", {"research:write"}, 1)
    client = TestClient(api.app)
    assert client.get("/api/v1/research/overview").status_code == 401
    assert client.get("/api/v1/research/overview", headers={"X-Admin-Token": write}).status_code == 403
    assert client.get("/api/v1/research/overview", headers={"X-Admin-Token": read}).status_code == 200
    raw = {"indicator_key": "synthetic_series", "indicator_or_claim": "Synthetic claim", "frequency": "monthly", "value_numeric": 5.24, "unit": "pct", "period_start": "2026-07-01", "period_end": "2026-07-01", "source_name": "Synthetic fixture", "source_reference": "https://example.org/test", "reliability_note": "Synthetic test observation only", "usage_basis": "Synthetic test fixture is permitted here", "quality": "estimated", "revision_id": "v1", "observation_key": "synthetic-http-observation"}
    assert client.post("/api/v1/research/evidence", json=raw, headers={"X-Admin-Token": read}).status_code == 403
    response = client.post("/api/v1/research/evidence", json=raw, headers={"X-Admin-Token": write})
    assert response.status_code == 200
    assert client.post("/api/v1/research/evidence", json=raw, headers={"X-Admin-Token": write}).json()["status"] == "duplicate"
    legacy = {key: value for key, value in raw.items() if key not in {"indicator_key", "frequency", "revision_id"}}
    legacy.update({"observation_key": "synthetic-legacy-http", "cycle_id": "flows", "mechanism_id": "savings_loop", "stance": "supports"})
    legacy_result = client.post("/api/v1/research/evidence", json=legacy, headers={"X-Admin-Token": write})
    assert legacy_result.status_code == 200 and legacy_result.json()["legacy_causal_fields_ignored"]
    assert db.get(ResearchEvidence, legacy_result.json()["id"]).indicator_key.startswith("legacy_")
    assert db.scalar(select(ResearchInterpretation.id).where(ResearchInterpretation.observation_id == legacy_result.json()["id"])) is None
    assert client.get("/api/v1/research/assessments/1", headers={"X-Admin-Token": write}).status_code == 403
    assert client.post("/api/v1/research/interpretations", json={}, headers={"X-Admin-Token": read}).status_code == 403
    assert client.post("/api/v1/research/investigations", json={}, headers={"X-Admin-Token": read}).status_code == 403
    assert client.patch("/api/v1/research/investigations/1", json={"status": "monitoring"}, headers={"X-Admin-Token": read}).status_code == 403
    assert client.get("/api/v1/research/investigations/1", headers={"X-Admin-Token": write}).status_code == 403
    recorded = client.post("/api/v1/research/assessments", json={"assessment_key": "synthetic-http-assessment"}, headers={"X-Admin-Token": write})
    assert recorded.status_code == 200
    assert client.get(f"/api/v1/research/assessments/{recorded.json()['id']}", headers={"X-Admin-Token": read}).status_code == 200
    assert db.scalars(select(AdminAudit).where(AdminAudit.action == "research_assessment_record")).first()
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./unused-test.db")
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "db")
    assert client.get("/api/v1/research/overview", headers={"X-Admin-Token": read}).status_code == 403


def test_legacy_research_migration_preserves_raw_and_noncausal_stance(tmp_path, monkeypatch):
    from alembic import command
    from alembic.config import Config
    from pathlib import Path
    url = f"sqlite:///{tmp_path / 'legacy.db'}"
    monkeypatch.setenv("DATABASE_URL", url)
    config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    command.upgrade(config, "research_1")
    engine = create_engine(url)
    with engine.begin() as connection:
        connection.execute(text("""INSERT INTO research_evidence
            (cycle_id, mechanism_id, indicator_or_claim, value_text, period_start, period_end, source_name, source_reference, retrieved_at, reliability_note, usage_basis, quality, stance, observation_key, entered_by)
            VALUES ('flows', 'savings_loop', 'Synthetic SIP claim', 'synthetic', '2026-07-01', '2026-07-01', 'fixture', 'https://example.org/test', '2026-07-01 12:00:00', 'Legacy synthetic caveat', 'Synthetic use', 'estimated', 'supports', 'legacy-synthetic-key', 'old-analyst')"""))
    command.upgrade(config, "research_2")
    with engine.connect() as connection:
        row = connection.execute(text("SELECT indicator_key, frequency, revision_id FROM research_evidence WHERE observation_key='legacy-synthetic-key'")).one()
        claim = connection.execute(text("SELECT evidence_type, stance, rationale, assessed_at FROM research_interpretations WHERE interpretation_key='legacy_pr16_1'")).one()
    assert row == ("legacy_observation_1", "event", "legacy-v1")
    assert claim[0] == "trend" and claim[1] == "supports"
    assert "lacked a documented causal rationale" in claim[2]
    assert claim[3]  # retained at migration time, not backdated to 2026-07-01
    engine.dispose()
