"""Tests for the reflexivity chart series block (assignment 8).

The charts must read only stored point-in-time observations: no interpolation,
no zero-filling, preserved dates/units/attribution, and explicit 422 on an
unknown range.
"""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal

from test_reflexivity_cycle import _authorise_api, _add_observation

UTC = timezone.utc


def test_reflexivity_series_block_charts_data(db, monkeypatch):
    """The series block returns chart-ready point-in-time rows with units and attribution."""
    from datetime import date as date_type
    from fastapi.testclient import TestClient
    api_module, read, _ = _authorise_api(db, monkeypatch)
    FPI, DII = "india_fpi_equity_net_flow_inr_cr", "india_dii_equity_net_flow_inr_cr"
    SIP, NIFTY = "india_mf_sip_contribution_inr_cr", "india_nifty50_close_level"
    for i in range(8):
        day = date_type(2026, 10, 1) + timedelta(days=i)
        published = datetime(2026, 10, 1, 18, tzinfo=UTC) + timedelta(days=i)
        _add_observation(db, FPI, day, Decimal("-3000") if i % 2 else Decimal("-1000"), published=published, ingested=published + timedelta(hours=1))
        _add_observation(db, DII, day, Decimal("2000"), published=published, ingested=published + timedelta(hours=1))
        _add_observation(db, NIFTY, day, Decimal(24000) + i, published=published, ingested=published + timedelta(hours=1), unit="index points")
    for i in range(3):  # June, July, August 2026 — no May value: growth must skip June
        month_day = date_type(2026, 6, 30) + timedelta(days=31 * i)
        _add_observation(db, SIP, month_day, Decimal(20000) + 1000 * i,
                         published=datetime(month_day.year, month_day.month, month_day.day, 12, tzinfo=UTC),
                         ingested=datetime(month_day.year, month_day.month, month_day.day, 13, tzinfo=UTC))
    db.commit()
    client = TestClient(api_module.app)
    body = client.get("/api/v1/research/reflexivity-cycle",
                      params={"as_of": "2026-11-01T00:00:00+00:00", "range": "since_april"},
                      headers={"X-Admin-Token": read}).json()
    series = body["series"]
    assert series["range"] == "since_april" and series["start"] == "2026-04-01"
    # flows: paired dates, negative FPI net below zero, rolling 5-session totals after 5 sessions
    flows = series["flows"]
    assert len(flows) == 8
    assert flows[0]["fpi_net"] == -1000.0 and flows[1]["fpi_net"] == -3000.0
    assert flows[0]["dii_net"] == 2000.0
    assert flows[0]["fpi_roll5"] is None and flows[4]["fpi_roll5"] == -9000.0  # -1000-3000-1000-3000-1000
    assert flows[0]["fpi_provider"] == "exchange-fixture"
    # nifty: rebased to 100 at the first stored close; level preserved
    nifty = series["nifty"]
    assert nifty[0]["normalized"] == 100.0 and nifty[0]["close"] == 24000.0
    assert nifty[-1]["normalized"] == round((24007.0 / 24000.0) * 100, 4)
    # sip: stored months only, growth null when the prior calendar month is missing
    sip = series["sip"]
    assert [row["period_end"] for row in sip] == ["2026-06-30", "2026-07-31", "2026-08-31"] or \
           [row["period_end"] for row in sip] == ["2026-06-30", "2026-07-31", "2026-08-30"]
    assert sip[0]["mom_growth_pct"] is None      # May is missing; never interpolated
    assert sip[1]["mom_growth_pct"] == 5.0       # 20000 → 21000
    assert sip[1]["unit"] == "INR crore"


def test_reflexivity_series_range_and_validation(db, monkeypatch):
    """Range selection filters rows; an invalid range is a 422; empty storage yields empty series."""
    from fastapi.testclient import TestClient
    api_module, read, _ = _authorise_api(db, monkeypatch)
    FPI = "india_fpi_equity_net_flow_inr_cr"
    for i in range(10):
        day = date(2026, 10, 1) + timedelta(days=i)
        published = datetime(2026, 10, 1, 18, tzinfo=UTC) + timedelta(days=i)
        _add_observation(db, FPI, day, Decimal(-500), published=published, ingested=published + timedelta(hours=1))
    db.commit()
    client = TestClient(api_module.app)
    assert client.get("/api/v1/research/reflexivity-cycle", params={"range": "2m"},
                      headers={"X-Admin-Token": read}).status_code == 422
    body = client.get("/api/v1/research/reflexivity-cycle",
                      params={"range": "1m", "as_of": "2026-11-01T00:00:00+00:00"},
                      headers={"X-Admin-Token": read}).json()
    flows = body["series"]["flows"]
    assert all(row["date"] >= "2026-10-01" for row in flows)   # 31-day window
    assert all(row["fpi_net"] == -500.0 for row in flows)
    empty = client.get("/api/v1/research/reflexivity-cycle",
                       params={"range": "1m", "as_of": "2026-09-01T00:00:00+00:00"},
                       headers={"X-Admin-Token": read}).json()
    assert empty["series"]["flows"] == [] and empty["series"]["nifty"] == []   # nothing stored in window; nothing fabricated


def test_reflexivity_series_absent_without_data(db, monkeypatch):
    """An empty database returns the unavailable view with an empty series block."""
    from fastapi.testclient import TestClient
    api_module, read, _ = _authorise_api(db, monkeypatch)
    client = TestClient(api_module.app)
    body = client.get("/api/v1/research/reflexivity-cycle", params={"range": "3m"},
                      headers={"X-Admin-Token": read}).json()
    assert body["state"] == "data_unavailable"
    assert body["series"]["flows"] == [] and body["series"]["nifty"] == [] and body["series"]["sip"] == []
    assert body["series"]["range"] == "3m" and body["series"]["start"].startswith("2026-08")
