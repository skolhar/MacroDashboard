"""Regression tests: capital-flow reflexivity, point-in-time evidence, spurious causality."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import pytest
from fastapi.testclient import TestClient

from packages.connectors.india_capital_flows import (
    CapitalFlowRecord, CapitalFlowTable, DII, FPI, NIFTY_CLOSE, SIP, parse_flows,
    monthly_returns_from_closes,
)
from packages.scoring.capital_flow_reflexivity import (
    evaluate, matched_sessions, offset, persistence, sip_response, spurious_association_check,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 1, 10, tzinfo=UTC)
MONTHLY = "india_nifty50_monthly_return_pct"


def flow(series, day, value, retrieved_at=NOW, revision="v1", flow_basis="net"):
    return CapitalFlowRecord(
        series=series, period_end=day, value=Decimal(str(value)), revision=revision,
        published_at=None, retrieved_at=retrieved_at, source_name="fixture",
        source_reference="fixture://", quality="secondary", flow_basis=flow_basis,
        definition_note="test",
    )


def sessions(n, start=date(2026, 10, 1), series=FPI, values=None, retrieved_at=NOW, flow_basis="net"):
    vals = values or ["-3000"]
    return [flow(series, start + timedelta(days=i), vals[i % len(vals)],
                 retrieved_at=retrieved_at, flow_basis=flow_basis) for i in range(n)]


# --- offset: identical reporting sessions, no zero-filling ---

def test_fpi_dii_offset_detected_cooccurrence_only():
    fpi = sessions(5, values=["-3000"])
    dii = sessions(5, series=DII, values=[3000])
    result = offset(fpi, dii, date(2026, 10, 6))
    assert result is not None
    assert result["state"] == "dii_offset_fpi_selling"
    assert result["matched_sessions"] == 5
    assert result["basis"].startswith("co-occurrence")


def test_offset_requires_same_reporting_sessions():
    fpi = sessions(5)                                   # Oct 1-5
    dii = sessions(5, series=DII, values=[3000], start=date(2026, 10, 2))  # Oct 2-6
    result = offset(fpi, dii, date(2026, 10, 6))
    assert result is None  # dates never coincide; nothing may be zero-filled


def test_offset_counts_unmatched_and_gross_exclusions():
    day = date(2026, 10, 6)
    fpi = sessions(6, start=date(2026, 10, 1))                       # Oct 1-6
    dii = sessions(5, series=DII, values=[3000], start=date(2026, 10, 2))  # Oct 2-6
    dii.append(flow(DII, date(2026, 10, 4), 9000, flow_basis="gross"))
    result = offset(fpi, dii, day)
    assert result is not None
    assert result["matched_sessions"] == 5
    assert result["unmatched_sessions_excluded"] == 1  # FPI Oct 1 has no DII session
    assert result["gross_rows_excluded"] == 1          # turnover never mixes with net flows


def test_offset_window_includes_latest_reported_session():
    fpi = sessions(5)                       # Oct 1-5
    dii = sessions(5, series=DII, values=[3000])
    result = offset(fpi, dii, date(2026, 10, 5))  # evaluation on the latest session itself
    assert result is not None
    assert result["fpi_net_cr"] == -15000.0
    assert result["dii_net_cr"] == 15000.0


def test_no_offset_when_fpi_net_positive():
    fpi = sessions(5, values=[3000])
    dii = sessions(5, series=DII, values=[3000])
    assert offset(fpi, dii, date(2026, 10, 6)) is None


def test_offset_below_threshold_returns_none():
    fpi = sessions(5, values=["-200"])
    dii = sessions(5, series=DII, values=[200])
def test_offset_below_threshold_returns_none():
    fpi = sessions(5, values=["-200"])
    dii = sessions(5, series=DII, values=[200])
    assert offset(fpi, dii, date(2026, 10, 6)) is None


def test_offset_full_offset_when_dii_matches_fpi_selling():
    """Full offset: DII buying exactly matches FPI selling magnitude."""
    fpi = sessions(5, values=["-1000"])
    dii = sessions(5, series=DII, values=[1000])
    result = offset(fpi, dii, date(2026, 10, 6))
    assert result is not None
    assert result["offset_size_cr"] == 5000.0
    assert result["gross_opposing_flow_cr"] == 10000.0
    assert result["unoffset_fpi_selling_cr"] == 0.0
    assert result["excess_dii_buying_cr"] == 0.0


def test_offset_partial_offset_reports_remaining_selling():
    """Partial offset: DII buying is less than FPI selling; remainder is unoffset."""
    fpi = sessions(5, values=["-1000"])
    dii = sessions(5, series=DII, values=[600])
    result = offset(fpi, dii, date(2026, 10, 6))
    assert result is not None
    assert result["offset_size_cr"] == 3000.0   # min(3000, 5000)
    assert result["gross_opposing_flow_cr"] == 8000.0
    assert result["unoffset_fpi_selling_cr"] == 2000.0
    assert result["excess_dii_buying_cr"] == 0.0


def test_offset_excess_dii_buying_capped_at_fpi_selling():
    """Excess domestic buying: matched offset is capped at FPI selling magnitude."""
    fpi = sessions(5, values=["-1000"])
    dii = sessions(5, series=DII, values=[1500])
    result = offset(fpi, dii, date(2026, 10, 6))
    assert result is not None
    assert result["offset_size_cr"] == 5000.0   # min(7500, 5000)
    assert result["gross_opposing_flow_cr"] == 12500.0
    assert result["unoffset_fpi_selling_cr"] == 0.0
    assert result["excess_dii_buying_cr"] == 2500.0


def test_offset_threshold_applies_to_matched_amount_not_gross():
    """The minimum threshold must gate the matched offset amount, not the gross opposing magnitude."""
    fpi = sessions(5, values=["-10000"])
    dii = sessions(5, series=DII, values=[400])
    # matched offset = min(2000, 50000) = 2000 < OFFSET_MIN(2500); the old gross
    # formula (2000 - (-50000) = 52000) would have passed this threshold.
    assert offset(fpi, dii, date(2026, 10, 6)) is None
    assert offset(fpi, dii, date(2026, 10, 6)) is None


def test_matched_sessions_reports_exclusions():
    fpi = sessions(3) + [flow(FPI, date(2026, 10, 9), -3000)]
    dii = sessions(3, series=DII, values=[3000], start=date(2026, 10, 2))
    fpi_by_date, dii_by_date, common, exclusions = matched_sessions(fpi, dii)
    assert len(common) == 2
    assert exclusions["fpi_unmatched_sessions"] == 2
    assert exclusions["dii_unmatched_sessions"] == 1


# --- persistence: detection observable at the date, follow-up retrospective ---

def test_persistence_weakening_when_ratio_decays():
    fpi = sessions(10, values=["-3000"])
    dii = sessions(10, series=DII, values=[3000] * 3 + [1000] * 7)
    result = persistence(fpi, dii, date(2026, 10, 4))
    assert result is not None
    assert result["state"] == "persistence_weakening"
    assert result["persistence"] == "weakening"
    assert result["detection"]["semantics"].startswith("signal observable")
    assert "retrospective" in result["follow_up"]["semantics"]


def test_persistence_insufficient_history_is_retrospective():
    fpi = sessions(4, values=["-3000"])
    dii = sessions(4, series=DII, values=[3000])
    result = persistence(fpi, dii, date(2026, 10, 5))
    assert result is not None
    assert result["state"] == "first"
    assert result["persistence"] == "insufficient_history"
    assert result["follow_up"]["sessions"] == 0


def test_persistence_ignores_rows_not_known_at_as_of():
    early = datetime(2026, 10, 4, 12, tzinfo=UTC)
    later = datetime(2026, 10, 8, 12, tzinfo=UTC)
    fpi = sessions(4, retrieved_at=early) + sessions(6, start=date(2026, 10, 5), retrieved_at=later)
    dii = sessions(4, series=DII, values=[3000], retrieved_at=early) + \
        sessions(6, series=DII, values=[3000], start=date(2026, 10, 5), retrieved_at=later)
    as_of = datetime(2026, 10, 5, 0, tzinfo=UTC)
    limited = persistence(fpi, dii, date(2026, 10, 4), as_of=as_of)
    assert limited is not None
    assert limited["persistence"] == "insufficient_history"  # follow-up not yet ingested
    full = persistence(fpi, dii, date(2026, 10, 4))
    assert full is not None and full["persistence"] != "insufficient_history"


# --- SIP response: lagged returns, growth vs levels, no look-ahead ---

def test_sip_response_uses_lagged_returns_and_names_lag():
    sip = [flow(SIP, date(2026, 1, 31), 10000), flow(SIP, date(2026, 2, 28), 11000),
           flow(SIP, date(2026, 3, 31), 12000), flow(SIP, date(2026, 4, 30), 13000)]
    returns = [flow(MONTHLY, date(2025, 10, 31), 5), flow(MONTHLY, date(2025, 11, 30), -2),
               flow(MONTHLY, date(2025, 12, 31), 3), flow(MONTHLY, date(2026, 1, 31), -1)]
    result = sip_response(sip, returns, NOW)
    assert result is not None
    assert result["state"] == "sip_falling_after_recent_returns"
    assert result["lag_months"] == 3
    assert result["months_observed"] == 4
    assert result["rising_return_months"] == 2 and result["falling_return_months"] == 2
    assert result["months_skipped_missing_prior_sip"] == 1


def test_sip_response_reports_growth_separately_from_levels():
    sip = [flow(SIP, date(2026, 1, 31), 10000), flow(SIP, date(2026, 2, 28), 11000),
           flow(SIP, date(2026, 3, 31), 12000), flow(SIP, date(2026, 4, 30), 13000)]
    returns = [flow(MONTHLY, date(2025, 10, 31), 5), flow(MONTHLY, date(2025, 11, 30), -2),
               flow(MONTHLY, date(2025, 12, 31), 3), flow(MONTHLY, date(2026, 1, 31), -1)]
    result = sip_response(sip, returns, NOW)
    assert result is not None
    assert result["avg_sip_cr_after_rising_returns"] == 11000.0
    assert result["avg_sip_cr_after_falling_returns"] == 12000.0
    assert result["median_sip_mom_growth_pct"] == pytest.approx(9.09, abs=0.05)
    assert result["limited_directions"] is False
    assert "growth" in result["basis"] and "registrations" in result["basis"]


def test_sip_response_ignores_returns_ingested_after_as_of():
    sip = [flow(SIP, date(2026, 1, 31), 10000), flow(SIP, date(2026, 2, 28), 11000),
           flow(SIP, date(2026, 3, 31), 12000), flow(SIP, date(2026, 4, 30), 13000)]
    returns = [flow(MONTHLY, date(2025, 10, 31), 5), flow(MONTHLY, date(2025, 11, 30), -2),
               flow(MONTHLY, date(2025, 12, 31), 3),
               flow(MONTHLY, date(2026, 1, 31), -1, retrieved_at=datetime(2026, 12, 1, tzinfo=UTC))]
    result = sip_response(sip, returns, NOW)
    assert result is not None
    assert result["state"] == "sip_flat_after_recent_returns"  # April pairs with an unknown return: skipped


def test_sip_response_requires_both_return_directions():
    sip = [flow(SIP, date(2026, 1, 31), 10000), flow(SIP, date(2026, 2, 28), 11000),
           flow(SIP, date(2026, 3, 31), 12000), flow(SIP, date(2026, 4, 30), 13000)]
    returns = [flow(MONTHLY, date(2025, 10, 31), 5), flow(MONTHLY, date(2025, 11, 30), 4),
               flow(MONTHLY, date(2025, 12, 31), 3), flow(MONTHLY, date(2026, 1, 31), 2)]
    assert sip_response(sip, returns, NOW) is None


# --- spurious association: co-occurrence, compounding, no order inference ---

def test_spurious_same_session_flows_are_co_occurrence_without_order_inference():
    day = date(2026, 10, 5)
    fpi = [flow(FPI, day, -3000, retrieved_at=NOW)]
    dii = [flow(DII, day, 3000, retrieved_at=NOW - timedelta(hours=1))]  # reported earlier that day
    returns = [flow(MONTHLY, date(2026, 11, 30), 5), flow(MONTHLY, date(2026, 12, 31), -2),
               flow(MONTHLY, date(2027, 1, 31), 3)]
    result = spurious_association_check(fpi, dii, returns, day)
    assert result["state"] == "co_occurrence_observed"  # retrieval order is never an economic order
    assert result["forward_return_pct"] == pytest.approx(5.987, abs=0.01)
    assert "cannot establish" in result["caveat"]


def test_spurious_flags_missing_session_pairing():
    fpi = [flow(FPI, date(2026, 10, 5), -3000)]
    dii = [flow(DII, date(2026, 10, 6), 3000)]
    result = spurious_association_check(fpi, dii, [], date(2026, 10, 5))
    assert result["state"] == "unresolved"
    assert result["reason"] == "no same-session pairing"


def test_spurious_requires_complete_forward_month():
    day = date(2026, 10, 5)
    fpi = [flow(FPI, day, -3000)]
    dii = [flow(DII, day, 3000)]
    result = spurious_association_check(fpi, dii, [flow(MONTHLY, day - timedelta(days=10), 1.5)], day)
    assert result["state"] == "unresolved"
    assert result["reason"] == "no complete forward return month available"


def test_spurious_compounds_multiple_forward_months():
    day = date(2026, 10, 5)
    fpi = [flow(FPI, day, -3000)]
    dii = [flow(DII, day, 3000)]
    returns = [flow(MONTHLY, date(2026, 11, 30), 5), flow(MONTHLY, date(2026, 12, 31), -2),
               flow(MONTHLY, date(2027, 1, 31), 3)]
    result = spurious_association_check(fpi, dii, returns, day)
    assert result["state"] == "co_occurrence_observed"
    assert result["forward_months"] == 3
    assert result["forward_return_pct"] == pytest.approx(5.987, abs=0.01)  # 1.05*0.98*1.03 - 1


def test_spurious_excludes_return_month_overlapping_offset_window():
    day = date(2026, 10, 5)
    fpi = [flow(FPI, day, -3000)]
    dii = [flow(DII, day, 3000)]
    returns = [flow(MONTHLY, date(2026, 10, 31), 10), flow(MONTHLY, date(2026, 11, 30), 5),
               flow(MONTHLY, date(2026, 12, 31), -2), flow(MONTHLY, date(2027, 1, 31), 3)]
    result = spurious_association_check(fpi, dii, returns, day)
    assert result["state"] == "co_occurrence_observed"
    assert result["forward_months"] == 3  # October's return overlaps the offset window and is excluded
    assert result["forward_return_pct"] == pytest.approx(5.987, abs=0.01)


def test_spurious_flags_gap_in_forward_window():
    day = date(2026, 10, 5)
    fpi = [flow(FPI, day, -3000)]
    dii = [flow(DII, day, 3000)]
    returns = [flow(MONTHLY, date(2026, 11, 30), 5), flow(MONTHLY, date(2026, 12, 31), -2),
               flow(MONTHLY, date(2027, 2, 28), 3)]  # January missing between December and February
    result = spurious_association_check(fpi, dii, returns, day)
    assert result["state"] == "unresolved"
    assert "incomplete" in result["reason"]
    assert "missing monthly return between observed months" in result["reason"]


def test_spurious_rejects_incomplete_horizon():
    """Fewer forward months than configured must be unresolved, never an outcome."""
    day = date(2026, 10, 5)
    fpi = [flow(FPI, day, -3000)]
    dii = [flow(DII, day, 3000)]
    returns = [flow(MONTHLY, date(2026, 11, 30), 5), flow(MONTHLY, date(2026, 12, 31), -2)]
    result = spurious_association_check(fpi, dii, returns, day)
    assert result["state"] == "unresolved"
    assert "only 2 of 3" in result["reason"]


def test_spurious_rejects_window_starting_late():
    """If the first required forward month is missing, the window never starts."""
    day = date(2026, 10, 5)
    fpi = [flow(FPI, day, -3000)]
    dii = [flow(DII, day, 3000)]
    returns = [flow(MONTHLY, date(2026, 12, 31), 5), flow(MONTHLY, date(2027, 1, 31), -2),
               flow(MONTHLY, date(2027, 2, 28), 3)]  # November missing: window cannot start
    result = spurious_association_check(fpi, dii, returns, day)
    assert result["state"] == "unresolved"
    assert "first required forward month" in result["reason"]
def test_evaluate_excludes_future_dated_and_late_ingested_rows():
    fpi = sessions(5) + [flow(FPI, date(2026, 11, 20), -3000),
                         flow(FPI, date(2026, 10, 5), -3000, retrieved_at=NOW + timedelta(days=1))]
    dii = sessions(5, series=DII, values=[3000])
    result = evaluate(fpi, dii, [], [], NOW)
    assert result["excluded_observations"]["fpi"] == {"future_dated": 1, "late_ingested": 1}
    assert result["offset"]["fpi_net_cr"] == -15000.0  # only the five known sessions count
    assert result["data_freshness"]["fpi"]["latest_period_end"] == "2026-10-05"


def test_evaluate_separates_observed_facts_from_hypotheses():
    result = evaluate(sessions(5), sessions(5, series=DII, values=[3000]), [], [], NOW)
    assert "observed" in result["observed_vs_hypothesized"]
    assert "hypothesized_not_observed" in result["observed_vs_hypothesized"]
    assert "not evidence of a" in result["limitation"]


def test_evaluate_includes_limitation_and_states():
    result = evaluate(sessions(10), sessions(10, series=DII, values=[3000]), [], [], NOW)
    assert "limitation" in result
    assert result["offset"] is not None or result["spurious_check"] is not None


# --- connector: parsing and derived monthly returns ---

def test_parse_flows_handles_mixed_columns_and_missing_values():
    table = CapitalFlowTable(
        columns=("Date", "FII/FPI Net (Cr)", "DII Net (Cr)"),
        rows=(("05-Oct-2026", "-3,000", "3,000"), ("06-Oct-2026", "-", "2,500"),
              ("07-Oct-2026", "NA", "NA")),
        loaded_at=NOW, report_title="fixture", period_to="2026-10-07",
    )
    records = parse_flows(table, {"Date": None, "FII/FPI Net (Cr)": FPI, "DII Net (Cr)": DII})
    fpi = [r for r in records if r.series == FPI]
    dii = [r for r in records if r.series == DII]
    assert len(fpi) == 1 and fpi[0].value == Decimal("-3000")
    assert len(dii) == 2  # missing values skipped, never zero-filled


def test_parse_flows_rejects_changed_column_headers():
    table = CapitalFlowTable(
        columns=("Trade Date", "FPI Net Value"), rows=(("05-Oct-2026", "-3000"),),
        loaded_at=NOW, report_title="fixture", period_to=None,
    )
    with pytest.raises(ValueError, match="columns changed"):
        parse_flows(table, {"FII/FPI Net (Cr)": FPI, "DII Net (Cr)": DII})


# --- private research API: authorization and point-in-time history ---

def _authorise_api(db, monkeypatch):
    from types import SimpleNamespace
    import apps.api.main as api_module
    from packages.jobs.operators import issue
    monkeypatch.setattr(api_module, "DB", db.bind)
    monkeypatch.setattr(api_module, "DEMO", False)
    monkeypatch.setattr(api_module, "LIMITER", SimpleNamespace(allow=lambda *args, **kwargs: True))
    monkeypatch.setenv("APP_ENV", "development")
    return api_module, issue(db, "flow-reader", {"research:read"}, 1), issue(db, "flow-writer", {"research:write"}, 1)


def _add_observation(db, indicator, day, value, *, published, ingested, vintage="v1", revision=False):
    from packages.domain.models import Observation
    db.add(Observation(
        indicator_id=indicator, period_start=day, period_end=day, value=value, unit="INR crore",
        published_at=published, ingested_at=ingested, provider="exchange-fixture",
        vintage_id=vintage, quality="verified", is_demo=False, is_revision=revision,
    ))


def test_capital_flows_endpoint_requires_research_scope(db, monkeypatch):
    from fastapi.testclient import TestClient
    api_module, read, write = _authorise_api(db, monkeypatch)
    client = TestClient(api_module.app)
    assert client.get("/api/v1/capital-flows").status_code == 401  # unauthenticated refused
    assert client.get("/api/v1/capital-flows", headers={"X-Admin-Token": write}).status_code == 403  # wrong scope
    ok = client.get("/api/v1/capital-flows", headers={"X-Admin-Token": read})
    assert ok.status_code == 200
    assert ok.json()["state"] == "data_unavailable"  # nothing stored; nothing fabricated


def test_capital_flows_historical_as_of_excludes_late_revisions(db, monkeypatch):
    from datetime import date
    from fastapi.testclient import TestClient
    api_module, read, _ = _authorise_api(db, monkeypatch)
    FPI_ID, DII_ID = "india_fpi_equity_net_flow_inr_cr", "india_dii_equity_net_flow_inr_cr"
    for i in range(5):
        day = date(2026, 10, 1) + timedelta(days=i)
        published = datetime(2026, 10, 1, 18, tzinfo=UTC) + timedelta(days=i)
        _add_observation(db, FPI_ID, day, Decimal("-3000"), published=published, ingested=published + timedelta(hours=1))
        _add_observation(db, DII_ID, day, Decimal("3000"), published=published, ingested=published + timedelta(hours=1))
    _add_observation(db, FPI_ID, date(2026, 10, 3), Decimal("50000"), published=datetime(2026, 10, 3, 18, tzinfo=UTC),
                     ingested=datetime(2026, 11, 1, 9, tzinfo=UTC), vintage="v2", revision=True)
    db.commit()
    client = TestClient(api_module.app)
    historical = client.get("/api/v1/capital-flows", params={"as_of": "2026-10-06T00:00:00+00:00"},
                            headers={"X-Admin-Token": read}).json()
    assert historical["state"] == "investigation_available"
    assert historical["offset"]["fpi_net_cr"] == pytest.approx(-15000.0)  # revision ingested later cannot leak backward
    assert historical["offset"]["matched_sessions"] == 5
