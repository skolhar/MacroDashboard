"""Tests for the reflexivity-cycle research view (assignment 7).

The cycle view composes the existing capital-flow investigation into one
analyst-facing narrative. It must never manufacture evidence from missing
data, must keep the hypothesis labelled as a hypothesis, and must remain
usable when observations are missing or stale.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest

from packages.scoring.reflexivity_cycle import (
    DAILY_STALE_DAYS, MONTHLY_STALE_DAYS,
    classify_evidence, implications, inflection_conditions,
    reflexivity_cycle_view, unavailable_view,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 1, 10, tzinfo=UTC)


def summary(key, status="current", days=1):
    base = {"indicator_id": f"india_{key}", "label": key, "unit": "INR crore", "status": status}
    if status != "missing":
        base.update({"latest_period_end": "2026-10-31", "value": 100.0,
                     "days_behind_as_of": days, "observation_count": 5})
    return base


def summaries(**overrides):
    base = {k: summary(k) for k in ("fpi", "dii", "sip", "returns")}
    base.update(overrides)
    return base


def evaluation(**overrides):
    base = {
        "as_of": NOW.isoformat(),
        "offset": None,
        "persistence": None,
        "sip_response": None,
        "spurious_check": None,
        "limitation": "Descriptive co-occurrence only.",
    }
    base.update(overrides)
    return base


# --- evidence classification: never manufactured from absence ---

def test_offset_evidence_is_supporting_and_descriptive():
    ev = classify_evidence(evaluation(offset={
        "dii_net_cr": 15000.0, "fpi_net_cr": -15000.0, "matched_sessions": 5,
        "offset_size_cr": 15000.0, "basis": "co-occurrence of opposite-sign net flows",
    }), summaries())
    item = next(e for e in ev if e["stance"] == "supporting")
    assert "co-occurred" in item["statement"] and "15,000" in item["statement"]


def test_missing_offset_window_is_insufficient_not_contradictory():
    ev = classify_evidence(evaluation(), summaries())
    item = next(e for e in ev if "No qualified offset window" in e["statement"])
    assert item["stance"] == "insufficient"


def test_persistence_verdicts_classify_supporting_and_contradictory():
    base = {"offset_ratio": 0.9, "follow_up": {"semantics": "retrospective follow-up evidence"}}
    sustained = classify_evidence(evaluation(persistence={**base, "persistence": "sustained"}), summaries())
    assert any(e["stance"] == "supporting" and "sustained" in e["statement"] for e in sustained)
    weakening = classify_evidence(evaluation(persistence={**base, "persistence": "weakening"}), summaries())
    assert any(e["stance"] == "contradictory" for e in weakening)


def test_sip_response_directions_classify_correctly():
    sip = {"state": "sip_rising_after_recent_returns", "avg_sip_cr_after_rising_returns": 12000.0,
           "avg_sip_cr_after_falling_returns": 10000.0, "months_observed": 4,
           "median_sip_mom_growth_pct": 9.1, "basis": "levels and growth reported separately"}
    ev = classify_evidence(evaluation(sip_response=sip), summaries())
    assert any(e["stance"] == "supporting" and "SIP" in e["statement"] for e in ev)
    sip["state"] = "sip_falling_after_recent_returns"
    ev = classify_evidence(evaluation(sip_response=sip), summaries())
    assert any(e["stance"] == "contradictory" and "SIP" in e["statement"] for e in ev)


def test_stale_and_missing_series_are_insufficient_evidence():
    ev = classify_evidence(evaluation(), summaries(
        fpi=summary("fpi", status="stale", days=DAILY_STALE_DAYS + 1),
        sip=summary("sip", status="missing"),
    ))
    assert any(e["stance"] == "insufficient" and "stale" in e["statement"] and "FPI" in e["statement"] for e in ev)
    assert any(e["stance"] == "insufficient" and "No SIP contributions observations" in e["statement"] for e in ev)

# --- full view composition and unavailable fallback ---

def test_cycle_view_composes_five_research_sections():
    view = reflexivity_cycle_view(evaluation(offset={
        "dii_net_cr": 15000.0, "fpi_net_cr": -15000.0, "matched_sessions": 5,
        "offset_size_cr": 15000.0, "basis": "co-occurrence",
    }), summaries())
    assert view["cycle"] == "domestic_equity_flows_market_reflexivity"
    assert "not an established causal" in view["hypothesis"]
    assert set(view["observations"]) == {"fpi", "dii", "sip", "returns"}
    assert all(e["stance"] in {"supporting", "contradictory", "insufficient"} for e in view["evidence"])
    assert len(view["inflection"]) == 3 and len(view["implications"]) == 2
    assert "escriptive" in view["limitation"]


def test_unavailable_view_stays_useful_without_data():
    view = unavailable_view("No attributable FPI/DII flow observations",
                            summaries(sip=summary("sip", status="missing")), NOW)
    assert view["state"] == "data_unavailable"
    assert view["evidence"] == []                       # no manufactured evidence
    assert "not an established causal" in view["hypothesis"]
    assert len(view["inflection"]) == 3 and len(view["implications"]) == 2


# --- endpoint: access control and composition over stored observations ---

def _authorise_api(db, monkeypatch):
    from types import SimpleNamespace
    import apps.api.main as api_module
    from packages.jobs.operators import issue
    monkeypatch.setattr(api_module, "DB", db.bind)
    monkeypatch.setattr(api_module, "DEMO", False)
    monkeypatch.setattr(api_module, "LIMITER", SimpleNamespace(allow=lambda *args, **kwargs: True))
    monkeypatch.setenv("APP_ENV", "development")
    return api_module, issue(db, "cycle-reader", {"research:read"}, 1), issue(db, "cycle-writer", {"research:write"}, 1)


def _add_observation(db, indicator, day, value, *, published, ingested, unit="INR crore"):
    from packages.domain.models import Observation
    db.add(Observation(
        indicator_id=indicator, period_start=day, period_end=day, value=value, unit=unit,
        published_at=published, ingested_at=ingested, provider="exchange-fixture",
        vintage_id="v1", quality="verified", is_demo=False, is_revision=False,
    ))


def test_reflexivity_cycle_endpoint_requires_research_scope(db, monkeypatch):
    from fastapi.testclient import TestClient
    api_module, read, write = _authorise_api(db, monkeypatch)
    client = TestClient(api_module.app)
    assert client.get("/api/v1/research/reflexivity-cycle").status_code == 401
    assert client.get("/api/v1/research/reflexivity-cycle", headers={"X-Admin-Token": write}).status_code == 403
    ok = client.get("/api/v1/research/reflexivity-cycle", headers={"X-Admin-Token": read})
    assert ok.status_code == 200
    body = ok.json()
    assert body["state"] == "data_unavailable"          # nothing stored; nothing fabricated
    assert "not an established causal" in body["hypothesis"]
    assert body["evidence"] == []
    assert len(body["implications"]) == 2


def test_reflexivity_cycle_endpoint_composes_stored_observations(db, monkeypatch):
    from fastapi.testclient import TestClient
    api_module, read, _ = _authorise_api(db, monkeypatch)
    FPI, DII = "india_fpi_equity_net_flow_inr_cr", "india_dii_equity_net_flow_inr_cr"
    SIP, NIFTY = "india_mf_sip_contribution_inr_cr", "india_nifty50_close_level"
    for i in range(10):  # 10 matched sessions: detection window + retrospective follow-up
        day = date(2026, 10, 1) + timedelta(days=i)
        published = datetime(2026, 10, 1, 18, tzinfo=UTC) + timedelta(days=i)
        _add_observation(db, FPI, day, Decimal("-3000"), published=published, ingested=published + timedelta(hours=1))
        _add_observation(db, DII, day, Decimal("3000"), published=published, ingested=published + timedelta(hours=1))
        _add_observation(db, NIFTY, day, Decimal(24000) + i, published=published,
                         ingested=published + timedelta(hours=1), unit="index points")
    for i in range(4):   # monthly SIP contributions
        month = date(2026, 7, 31) + timedelta(days=31 * i)
        _add_observation(db, SIP, month, Decimal(20000) + 1000 * i,
                         published=datetime(month.year, month.month, month.day, 12, tzinfo=UTC),
                         ingested=datetime(month.year, month.month, month.day, 13, tzinfo=UTC))
    db.commit()
    client = TestClient(api_module.app)
    body = client.get("/api/v1/research/reflexivity-cycle", params={"as_of": "2026-11-01T00:00:00+00:00"},
                      headers={"X-Admin-Token": read}).json()
    assert body["state"] == "investigation_available"
    for key in ("fpi", "dii", "sip", "returns"):
        assert body["observations"][key]["observation_count"] >= 1
        assert body["observations"][key]["status"] in {"current", "stale"}
    assert all(e["stance"] in {"supporting", "contradictory", "insufficient"} for e in body["evidence"])
    assert [i["horizon"] for i in body["implications"]] == ["1-3 months", "3-6 months"]
    assert "not an established causal" in body["hypothesis"]


# --- inflection and implications: conditions to monitor, no predictions ---

def test_inflection_conditions_monitor_weakening_reinforcement():
    conditions = inflection_conditions(evaluation())
    assert len(conditions) == 3
    assert all(c["status"] != "observed" for c in conditions)  # nothing observed without stored evidence
    weakening = inflection_conditions(evaluation(persistence={"persistence": "weakening"}))
    assert weakening[0]["status"] == "observed"  # only when stored evidence already shows it


def test_implications_are_conditional_scenarios_without_predictions():
    result = implications(evaluation(sip_response={"median_sip_mom_growth_pct": 9.1}))
    assert [i["horizon"] for i in result] == ["1-3 months", "3-6 months"]
    text = " ".join(i["scenario"] for i in result).lower()
    assert "if " in text
    for forbidden in ("buy signal", "sell signal", "price target", "probability"):
        assert forbidden not in text
