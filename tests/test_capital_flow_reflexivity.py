"""Regression tests: capital-flow reflexivity, provenance and spurious causality."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
import pytest
from packages.connectors.india_capital_flows import (
    CapitalFlowRecord, CapitalFlowTable, DII, FPI, NIFTY_CLOSE, SIP, parse_flows,
    monthly_returns_from_closes,
)
from packages.scoring.capital_flow_reflexivity import (
    evaluate, offset, persistence, sip_response, spurious_association_check,
)

UTC = timezone.utc
NOW = datetime(2026, 11, 1, 10, tzinfo=UTC)


def flow(series, day, value, retrieved_at=NOW, revision="v1"):
    return CapitalFlowRecord(
        series=series, period_end=day, value=Decimal(str(value)), revision=revision,
        published_at=None, retrieved_at=retrieved_at, source_name="fixture",
        source_reference="fixture://", quality="secondary", flow_basis="net",
        definition_note="test",
    )


def sessions(n, start=date(2026, 10, 1), series=FPI, values=None):
    """Create n daily records; `values` is cycled if shorter than n."""
    vals = values or ["-3000"]
    return [flow(series, start + timedelta(days=i), vals[i % len(vals)]) for i in range(n)]


def test_fpi_dii_offset_detected_cooccurrence_only():
    fpi = sessions(5, values=["-3000"])
    dii = sessions(5, series=DII, values=[3000])
    result = offset(fpi, dii, date(2026, 10, 6))
    assert result is not None
    assert result["state"] == "dii_offset_fpi_selling"
    assert result["basis"].startswith("co-occurrence")


def test_no_offset_when_fpi_net_positive():
    fpi = sessions(5, values=[3000])
    dii = sessions(5, series=DII, values=[3000])
    assert offset(fpi, dii, date(2026, 10, 6)) is None


def test_offset_below_threshold_returns_none():
    fpi = sessions(5, values=["-200"])
    dii = sessions(5, series=DII, values=[200])
    assert offset(fpi, dii, date(2026, 10, 6)) is None


def test_persistence_weakening_when_ratio_decays():
    fpi = sessions(10, values=["-3000"])
    dii = sessions(10, series=DII, values=[3000] * 3 + [1000] * 7)
    result = persistence(fpi, dii, date(2026, 10, 4))
    assert result is not None
    assert result["persistence"] == "weakening"


def test_persistence_insufficient_history():
    fpi = sessions(4, values=["-3000"])
    dii = sessions(4, series=DII, values=[3000])
    result = persistence(fpi, dii, date(2026, 10, 5))
    assert result is not None
    assert result["persistence"] == "insufficient_history"


def test_sip_response_uses_lagged_returns_and_names_lag():
    sip = [flow(SIP, date(2026, 1, 31), 10000), flow(SIP, date(2026, 2, 28), 11000),
           flow(SIP, date(2026, 3, 31), 12000), flow(SIP, date(2026, 4, 30), 13000)]
    # lag_months=3: SIP in month M pairs with the return from month M-3.
    returns = [flow("india_nifty50_monthly_return_pct", date(2025, 10, 31), 5),
               flow("india_nifty50_monthly_return_pct", date(2025, 11, 30), -2),
               flow("india_nifty50_monthly_return_pct", date(2025, 12, 31), 3),
               flow("india_nifty50_monthly_return_pct", date(2026, 1, 31), -1)]
    result = sip_response(sip, returns, NOW)
    assert result is not None
    assert result["state"] == "sip_falling_after_recent_returns"
    assert result["lag_months"] == 3


def test_monthly_returns_derived_from_month_end_closes():
    closes = [flow(NIFTY_CLOSE, date(2026, 1, 30), 10000), flow(NIFTY_CLOSE, date(2026, 2, 27), 10200),
              flow(NIFTY_CLOSE, date(2026, 2, 28), 10100)]
    returns = monthly_returns_from_closes(closes)
    assert len(returns) == 1
    assert returns[0].period_end == date(2026, 2, 28)
    assert returns[0].value == Decimal("1")
    assert returns[0].quality == "derived"


def test_monthly_returns_skip_months_without_prior_close():
    closes = [flow(NIFTY_CLOSE, date(2026, 1, 30), 10000)]
    assert monthly_returns_from_closes(closes) == []


def test_spurious_association_flags_missing_session_pairing():
    fpi = [flow(FPI, date(2026, 10, 5), -3000)]
    dii = [flow(DII, date(2026, 10, 6), 3000)]
    returns = [flow("india_nifty50_return", date(2026, 10, 8), 1.5)]
    result = spurious_association_check(fpi, dii, returns, date(2026, 10, 5))
    assert result["state"] == "unresolved"
    assert result["reason"] == "no same-session pairing"


def test_spurious_association_flags_out_of_order_reporting():
    day = date(2026, 10, 5)
    fpi = [flow(FPI, day, -3000, retrieved_at=NOW)]
    dii = [flow(DII, day, 3000, retrieved_at=NOW - timedelta(hours=1))]
    returns = [flow("india_nifty50_return", day + timedelta(days=2), 1.5)]
    result = spurious_association_check(fpi, dii, returns, day)
    assert result["state"] == "not_a_response"
    assert "before FPI" in result["reason"]


def test_spurious_association_requires_forward_window():
    day = date(2026, 10, 5)
    fpi = [flow(FPI, day, -3000)]
    dii = [flow(DII, day, 3000, retrieved_at=NOW + timedelta(hours=1))]
    returns = [flow("india_nifty50_return", day - timedelta(days=2), 1.5)]
    result = spurious_association_check(fpi, dii, returns, day)
    assert result["state"] == "unresolved"
    assert result["reason"] == "no forward return window"


def test_evaluate_includes_limitation_and_states():
    fpi = sessions(10, values=["-3000"])
    dii = sessions(10, series=DII, values=[3000])
    sip = [flow(SIP, date(2026, 1, 31), 10000), flow(SIP, date(2026, 2, 28), 11000),
           flow(SIP, date(2026, 3, 31), 12000), flow(SIP, date(2026, 4, 30), 13000)]
    returns = [flow("india_nifty50_return", date(2026, 10, 6), 1.5)]
    result = evaluate(fpi, dii, sip, returns, NOW)
    assert "limitation" in result
    assert "not evidence of a" in result["limitation"]
    assert result["offset"] is not None or result["spurious_check"] is not None


def test_parse_flows_handles_mixed_columns_and_missing_values():
    table = CapitalFlowTable(
        columns=("Date", "FII/FPI Net (Cr)", "DII Net (Cr)"),
        rows=(("05-Oct-2026", "-3,000", "3,000"),
              ("06-Oct-2026", "-", "2,500"),
              ("07-Oct-2026", "NA", "NA")),
        loaded_at=NOW, report_title="fixture", period_to="2026-10-07",
    )
    records = parse_flows(table, {"Date": None, "FII/FPI Net (Cr)": FPI, "DII Net (Cr)": DII})
    fpi = [r for r in records if r.series == FPI]
    dii = [r for r in records if r.series == DII]
    assert len(fpi) == 1
    assert fpi[0].value == Decimal("-3000")
    assert len(dii) == 2  # missing values skipped, not zero-filled


def test_parse_flows_rejects_changed_column_headers():
    table = CapitalFlowTable(
        columns=("Trade Date", "FPI Net Value"), rows=(("05-Oct-2026", "-3000"),),
        loaded_at=NOW, report_title="fixture", period_to=None,
    )
    with pytest.raises(ValueError, match="columns changed"):
        parse_flows(table, {"FII/FPI Net (Cr)": FPI, "DII Net (Cr)": DII})
