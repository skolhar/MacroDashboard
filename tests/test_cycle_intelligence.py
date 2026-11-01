"""Synthetic economic scenarios only; no fixture is a real market finding."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from fastapi import HTTPException
from sqlalchemy import select

from packages.domain.models import ResearchEvidence, CycleInvestigation, MarketBar
from packages.scoring.cycle_intelligence import catalog, evaluate

AS_OF = datetime(2026, 10, 31, 12, tzinfo=timezone.utc)


def add(db, mechanism, stance, day, claim, source="Synthetic research fixture"):
    row = ResearchEvidence(cycle_id="flows", mechanism_id=mechanism, indicator_or_claim=claim, value_text="synthetic finding", unit=None, period_start=day, period_end=day, source_name=source, source_reference="https://example.org/synthetic-test", retrieved_at=datetime.combine(day, datetime.min.time(), timezone.utc) + timedelta(hours=12), published_at=None, reliability_note="Synthetic scenario, not actual economic data", usage_basis="Synthetic test fixture only", quality="estimated", stance=stance, observation_key=f"{mechanism}:{stance}:{day}:{claim}:{source}", entered_by="test-operator")
    db.add(row)
    db.flush()
    return row


def flow_scenario(db):
    add(db, "savings_loop", "supports", date(2026, 7, 1), "SIP inflows")
    add(db, "savings_loop", "supports", date(2026, 8, 1), "SIP inflows")
    add(db, "savings_loop", "contradicts", date(2026, 9, 1), "SIP inflows")
    add(db, "redemption_loop", "supports", date(2026, 9, 1), "fund redemptions")
    add(db, "redemption_loop", "supports", date(2026, 10, 1), "fund redemptions")


def test_catalog_has_six_explicit_mechanisms_and_falsifiers():
    cycles = catalog()["cycles"]
    assert set(cycles) == {"fx", "energy", "flows", "earnings", "it", "global"}
    for value in cycles.values():
        assert {m["role"] for m in value["mechanisms"]} == {"reinforcing", "balancing"}
        assert value["alternatives"] and value["invalidated_when"] and value["unresolved"]


def test_research_request_accepts_numeric_or_qualitative_but_no_empty_claim():
    import apps.api.main as api
    common = dict(cycle_id="global", mechanism_id="funding_constraint", indicator_or_claim="Treasury yield", period_start=date(2026, 10, 1), period_end=date(2026, 10, 1), source_name="Synthetic fixture", source_reference="https://example.org/test", reliability_note="Synthetic scenario only, no actual yield", usage_basis="Synthetic test fixture is permitted here", quality="estimated", stance="neutral", observation_key="synthetic-numeric-claim")
    assert api.ResearchEvidenceRequest(**common, value_numeric=Decimal("5.24"), unit="pct").value_numeric == Decimal("5.24")
    assert api.ResearchEvidenceRequest(**common, value_text="No credible pricing evidence").value_text
    with pytest.raises(ValueError):
        api.ResearchEvidenceRequest(**common)


def test_weakening_reversing_missing_vs_counter_and_persistence(db):
    flow_scenario(db)
    before = evaluate(db, datetime(2026, 8, 15, tzinfo=timezone.utc))
    assert next(c for c in before["cycles"] if c["id"] == "flows")["state"] == "mature / persistent"
    weak = evaluate(db, AS_OF)
    flow = next(c for c in weak["cycles"] if c["id"] == "flows")
    assert flow["state"] == "weakening"
    assert flow["balancing"]["distinct_periods"] == 2
    assert flow["candidate"]["type"] == "reinforcing_force_losing_momentum"
    assert flow["candidate"]["supporting_observations"]
    assert flow["candidate"]["competing_explanations"]
    assert next(c for c in weak["cycles"] if c["id"] == "it")["state"] == "indeterminate"
    assert next(c for c in weak["cycles"] if c["id"] == "it")["candidate"] is None
    add(db, "savings_loop", "contradicts", date(2026, 10, 1), "SIP inflows")
    reversed_cycle = next(c for c in evaluate(db, AS_OF)["cycles"] if c["id"] == "flows")
    assert reversed_cycle["state"] == "reversing"
    assert reversed_cycle["candidate"]["type"] == "balancing_force_dominance"


def test_price_is_confirmation_only_and_instrument_effects_differ(db):
    db.add_all([MarketBar(instrument_id="nifty50", provider="yahoo", provider_symbol="^NSEI", market="NSE", currency="INR", exchange_timezone="Asia/Kolkata", session_date=day, open=Decimal(value), high=Decimal(value), low=Decimal(value), close=Decimal(value), adjusted_close=None, volume=100, price_basis="raw", source_url="https://finance.yahoo.com/quote/%5ENSEI/", retrieved_at=AS_OF - timedelta(days=1), quality="secondary_unverified", content_hash=f"synthetic-{day}") for day, value in ((date(2026, 9, 1), 100), (date(2026, 10, 1), 110))])
    db.flush()
    empty = evaluate(db, AS_OF)
    assert all(c["state"] == "indeterminate" for c in empty["cycles"])
    assert empty["market_confirmation"]["nifty50"]["change_pct"] == 10
    flow_scenario(db)
    result = evaluate(db, AS_OF)
    nifty = next(x for x in result["outlooks"] if x["instrument_id"] == "nifty50" and x["horizon"] == "1-3 months")
    crude = next(x for x in result["outlooks"] if x["instrument_id"] == "brent_front_yahoo" and x["horizon"] == "1-3 months")
    assert nifty["influences"] and not crude["influences"]
    assert nifty["direction"] == "unresolved as the loop weakens"
    assert crude["direction"] == "conditional / unresolved"
    assert {o["horizon"] for o in result["outlooks"]} == {"1-3 months", "3-6 months"}
    assert "probability" not in str(result["outlooks"]).lower()
    assert "weight" not in str(result["outlooks"]).lower()
    later = next(x for x in result["outlooks"] if x["instrument_id"] == "nifty50" and x["horizon"] == "3-6 months")
    assert nifty["influences"][0]["horizon_reason"] != later["influences"][0]["horizon_reason"]


def test_conflicting_sources_and_duplicate_causal_evidence(db):
    day = date(2026, 9, 1)
    add(db, "savings_loop", "supports", day, "SIP inflows", "Synthetic source A")
    add(db, "savings_loop", "supports", day, "SIP inflows", "Synthetic source B")
    flow = next(c for c in evaluate(db, AS_OF)["cycles"] if c["id"] == "flows")
    assert flow["reinforcing"]["supports"] == 1
    add(db, "savings_loop", "contradicts", day, "SIP inflows", "Synthetic source C")
    flow = next(c for c in evaluate(db, AS_OF)["cycles"] if c["id"] == "flows")
    assert flow["reinforcing"]["supports"] == 0
    assert flow["reinforcing"]["contradicts"] == 0
    assert len(flow["conflicting_source_observations"]) == 3
    assert flow["material"]


def test_api_private_evidence_idempotence_investigation_snapshot(db, monkeypatch):
    import apps.api.main as api
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setenv("APP_ENV", "development")
    operator = {"operator_id": "researcher"}
    payload = api.ResearchEvidenceRequest(cycle_id="flows", mechanism_id="savings_loop", indicator_or_claim="SIP inflows", value_text="synthetic", period_start=date(2026, 7, 1), period_end=date(2026, 7, 1), source_name="Synthetic fixture", source_reference="https://example.org/test", reliability_note="Synthetic evidence for a regression test", usage_basis="Synthetic fixture can be used in this test", quality="estimated", stance="supports", observation_key="synthetic-evidence-key-1")
    assert api.add_research_evidence(payload, operator)["status"] == "recorded"
    assert api.add_research_evidence(payload, operator)["status"] == "duplicate"
    with pytest.raises(HTTPException) as exc:
        api.add_research_evidence(payload.model_copy(update={"value_text": "different"}), operator)
    assert exc.value.status_code == 409
    flow_scenario(db)
    # The API uses current time; this synthetic 2026 scenario may be in the
    # future on older CI clocks, so exercise the durable workflow at engine time.
    candidate = next(c for c in evaluate(db, AS_OF)["candidates"] if c["cycle_id"] == "flows")
    monkeypatch.setattr(api, "evaluate_cycles", lambda session, when: evaluate(session, AS_OF))
    request = api.InvestigationRequest(candidate_key=candidate["key"], initial_observation="Synthetic flow reversal is under investigation", competing_hypotheses=["Seasonal allocation shift"], questions=["Are fund outflows persistent?"], confirmation_criteria="Another independent fund release supports reversal", falsification_criteria="Fund flows and earnings recover together")
    first = api.start_investigation(request, operator)
    assert api.start_investigation(request, operator)["duplicate"]
    detail = api.get_investigation(first["id"], operator)
    assert detail["evidence_snapshot"]["supporting_observations"]
    assert detail["competing_hypotheses"] == ["Seasonal allocation shift"]
    assert api.update_investigation(first["id"], api.InvestigationStatusRequest(status="monitoring"), operator)["status"] == "monitoring"
    assert db.scalars(select(CycleInvestigation)).first().status == "monitoring"


def test_demo_and_private_gate_do_not_mix(db, monkeypatch):
    import apps.api.main as api
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", True)
    assert evaluate(db, AS_OF, demo=True)["evidence_count"] == 0
    with pytest.raises(HTTPException) as exc:
        api.private_research_operator("research:read", "any-token")
    assert exc.value.status_code == 403
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./unused-test.db")
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "db")
    with pytest.raises(HTTPException) as exc:
        api.private_research_operator("research:read", "any-token")
    assert exc.value.status_code == 403


def test_research_http_scopes_and_production_block(db, monkeypatch):
    import apps.api.main as api
    from fastapi.testclient import TestClient
    from packages.jobs.operators import issue
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setenv("APP_ENV", "development")
    read_token = issue(db, "reader", {"research:read"}, 1)
    write_token = issue(db, "writer", {"research:write"}, 1)
    client = TestClient(api.app)
    assert client.get("/api/v1/research/overview").status_code == 401
    assert client.get("/api/v1/research/overview", headers={"X-Admin-Token": write_token}).status_code == 403
    response = client.get("/api/v1/research/overview", headers={"X-Admin-Token": read_token})
    assert response.status_code == 200 and response.json()["mode"] == "private_research"
    payload = {"cycle_id": "flows", "mechanism_id": "savings_loop", "indicator_or_claim": "Synthetic SIP flow claim", "value_text": "synthetic", "period_start": "2026-07-01", "period_end": "2026-07-01", "source_name": "Synthetic fixture", "source_reference": "https://example.org/test", "reliability_note": "Synthetic evidence for scoped API test", "usage_basis": "Synthetic test fixture is permitted here", "quality": "estimated", "stance": "supports", "observation_key": "http-synthetic-evidence-1"}
    assert client.post("/api/v1/research/evidence", json=payload, headers={"X-Admin-Token": read_token}).status_code == 403
    assert client.post("/api/v1/research/evidence", json=payload, headers={"X-Admin-Token": write_token}).status_code == 200
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./unused-test.db")
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "db")
    assert client.get("/api/v1/research/overview", headers={"X-Admin-Token": read_token}).status_code == 403
