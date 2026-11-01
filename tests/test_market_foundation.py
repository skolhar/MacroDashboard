"""Mock Yahoo payloads only; no test makes an external market-data request."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
from zoneinfo import ZoneInfo
import pandas as pd
import pytest
from sqlalchemy import select
from packages.domain.models import MarketBar, MarketFetchRun, Observation
from packages.domain.settings import settings
from packages.market.base import MarketBatch, MarketCandle, instruments
from packages.market.yahoo import YahooProvider, MarketSourceUnavailable
from packages.market.operations import history_at, ingest_batch, refresh, status_at

NOW = datetime(2026, 11, 1, 12, tzinfo=timezone.utc)


def frame(tz="Asia/Kolkata"):
    index = pd.DatetimeIndex([datetime(2026, 10, 28, tzinfo=ZoneInfo(tz)), datetime(2026, 10, 29, tzinfo=ZoneInfo(tz))])
    return pd.DataFrame({"Open": [100.0, 103.0], "High": [105.0, 106.0], "Low": [99.0, 101.0], "Close": [104.0, 102.0], "Adj Close": [103.5, 101.5], "Volume": [1000, 1100]}, index=index)


class FakeTicker:
    def __init__(self, symbol, data=None, metadata=None, failures=0):
        self.symbol = symbol
        self.data = data if data is not None else frame()
        self.metadata = metadata if metadata is not None else {"currency": "INR", "exchangeTimezoneName": "Asia/Kolkata", "exchangeName": "NSE"}
        self.failures = failures
        self.calls = []

    def history(self, **kwargs):
        self.calls.append(kwargs)
        if len(self.calls) <= self.failures:
            raise TimeoutError("synthetic transient timeout")
        return self.data

    def get_history_metadata(self):
        return self.metadata


def provider(ticker):
    return YahooProvider(ticker_factory=lambda symbol: ticker, sleep=lambda seconds: None, clock=lambda: NOW)


def test_registry_symbols_and_future_adapter_slot():
    registry = instruments()
    assert len(registry) == 15
    assert registry["nifty50"].yahoo == "^NSEI"
    assert registry["usd_inr_yahoo"].yahoo == "INR=X"
    assert registry["wti_front_yahoo"].yahoo == "CL=F"
    assert registry["brent_front_yahoo"].yahoo == "BZ=F"
    assert registry["gold_front_yahoo"].yahoo == "GC=F"
    assert {item.yahoo for item in registry.values() if item.kind == "etf"} == {f"{symbol}.NS" for symbol in ("NIFTYBEES", "SETFNN50", "MIDCAPETF", "MON100", "MASPTOP50", "HNGSNGBEES", "GOLDBEES", "SILVERCASE", "LIQUIDCASE", "LTGILTBEES")}
    assert all(item.upstox is None for item in registry.values())
    from packages.market.providers import provider_for
    with pytest.raises(MarketSourceUnavailable, match="UpstoxAdapterUnavailable"):
        provider_for("upstox")


def test_yahoo_normalizes_raw_adjusted_timezone_currency_and_missing_rows():
    spec = instruments()["nifty50"]
    fake = FakeTicker("^NSEI")
    batch = provider(fake).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 1))
    assert len(batch.candles) == 2 and batch.candles[0].session_date == date(2026, 10, 28)
    assert batch.candles[0].close == Decimal("104.0") and batch.candles[0].adjusted_close == Decimal("103.5")
    assert batch.exchange_timezone == "Asia/Kolkata" and batch.instrument.currency == "INR"
    assert fake.calls[0]["auto_adjust"] is False and fake.calls[0]["interval"] == "1d"
    same_day = frame()
    same_day.loc[datetime(2026, 11, 1, tzinfo=ZoneInfo("Asia/Kolkata"))] = [105, 107, 104, 106, 105.5, 900]
    completed = provider(FakeTicker("^NSEI", same_day)).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 2))
    assert len(completed.candles) == 2 and completed.rejected_rows == 0
    bad = frame()
    bad.loc[bad.index[1], "High"] = 90
    partial = provider(FakeTicker("^NSEI", bad)).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 1))
    assert len(partial.candles) == 1 and partial.rejected_rows == 1 and partial.quality == "secondary_partial"
    with pytest.raises(MarketSourceUnavailable, match="CurrencyOrTimezoneMismatch"):
        provider(FakeTicker("^NSEI", metadata={"currency": "USD", "exchangeTimezoneName": "Asia/Kolkata"})).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 1))


def test_yahoo_retry_and_unavailable_are_explicit():
    spec = instruments()["nifty50"]
    fake = FakeTicker("^NSEI", failures=2)
    assert len(provider(fake).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 1)).candles) == 2
    assert len(fake.calls) == 3
    with pytest.raises(MarketSourceUnavailable):
        provider(FakeTicker("^NSEI", failures=3)).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 1))
    with pytest.raises(MarketSourceUnavailable, match="EmptyHistory"):
        provider(FakeTicker("^NSEI", pd.DataFrame())).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 1))


def test_futures_negative_price_and_roll_identity():
    spec = instruments()["wti_front_yahoo"]
    data = frame("America/New_York")
    data.loc[data.index[0], ["Open", "High", "Low", "Close", "Adj Close"]] = [-20, -10, -25, -15, -15]
    fake = FakeTicker("CL=F", data, {"currency": "USD", "exchangeTimezoneName": "America/New_York"})
    batch = provider(fake).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 1))
    assert batch.candles[0].close == Decimal("-15.0")
    assert batch.roll_policy == "vendor_roll_unknown" and batch.contract_identity == "CL=F:continuous_front_month"


def test_idempotent_incremental_revision_and_as_of(db):
    spec = instruments()["nifty50"]
    batch = provider(FakeTicker("^NSEI")).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 1))
    class Fixed:
        name = "yahoo"
        def __init__(self, payload): self.payload = payload; self.calls = []
        def fetch_daily(self, instrument, start, end): self.calls.append((start, end)); return self.payload
    p = Fixed(batch)
    assert refresh(db, p, spec, date(2026, 10, 20), date(2026, 11, 1), NOW)["inserted"] == 2
    assert refresh(db, p, spec, now=NOW)["duplicates"] == 2
    assert p.calls[-1][0] == date(2026, 10, 22)
    assert db.scalar(select(Observation.id).where(Observation.indicator_id == "nifty50")) is None
    assert status_at(db, spec, "yahoo", NOW + timedelta(days=10))["status"] == "STALE"
    assert history_at(db, spec.id, "yahoo", NOW - timedelta(minutes=1)) == []
    assert len(history_at(db, spec.id, "yahoo", NOW + timedelta(minutes=1))) == 2
    revised = MarketBatch(spec, "yahoo", "^NSEI", NOW + timedelta(minutes=2), batch.source_url, (MarketCandle(date(2026, 10, 29), Decimal("103"), Decimal("106"), Decimal("101"), Decimal("105"), Decimal("104.5"), 1100),), "Asia/Kolkata")
    p.payload = revised
    assert refresh(db, p, spec, date(2026, 10, 29), date(2026, 11, 1), NOW)["revisions"] == 1
    assert history_at(db, spec.id, "yahoo", NOW + timedelta(minutes=1))[-1].close == Decimal("102")
    assert history_at(db, spec.id, "yahoo", NOW + timedelta(minutes=3))[-1].close == Decimal("105")
    assert db.scalar(select(MarketBar.id).where(MarketBar.instrument_id == spec.id)) is not None


def test_failures_staleness_gaps_and_production_gate(db, monkeypatch):
    spec = instruments()["nifty50"]
    class Failing:
        name = "yahoo"
        def fetch_daily(self, *args): raise MarketSourceUnavailable("synthetic unavailable")
    with pytest.raises(MarketSourceUnavailable):
        refresh(db, Failing(), spec, date(2026, 10, 20), date(2026, 11, 1), NOW)
    assert status_at(db, spec, "yahoo", NOW)["status"] == "SOURCE_FAILED"
    assert db.scalar(select(MarketFetchRun).where(MarketFetchRun.instrument_id == spec.id)).error_code == "MarketSourceUnavailable"
    batch = MarketBatch(spec, "yahoo", "^NSEI", NOW, "https://finance.yahoo.com/quote/%5ENSEI/history/", (MarketCandle(date(2026, 10, 23), Decimal("100"), Decimal("102"), Decimal("99"), Decimal("101"), None, 100), MarketCandle(date(2026, 10, 29), Decimal("102"), Decimal("104"), Decimal("101"), Decimal("103"), None, 100)), "Asia/Kolkata")
    assert ingest_batch(db, batch)["inserted"] == 2
    db.commit()
    reported = status_at(db, spec, "yahoo", NOW + timedelta(days=6))
    assert reported["status"] == "SOURCE_FAILED_USING_PRIOR_BAR"
    assert "2026-10-26" in reported["possible_weekday_gaps_last_60"]
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "db")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///unused-test.db")
    monkeypatch.setenv("MARKET_DATA_RESEARCH_ENABLED", "true")
    with pytest.raises(ValueError, match="isolated"):
        settings()


def test_market_api_contract_and_disabled_mode(db, monkeypatch):
    from fastapi.testclient import TestClient
    import apps.api.main as api
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "LIMITER", SimpleNamespace(allow=lambda *args: True))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("MARKET_DATA_RESEARCH_ENABLED", "true")
    client = TestClient(api.app)
    listing = client.get("/api/v1/market/instruments").json()
    assert listing["mode"] == "isolated_research" and len(listing["items"]) == 15
    assert listing["items"][0]["status"]["status"] == "DATA_UNAVAILABLE"
    assert client.get("/api/v1/market/instruments/nifty50/history").json()["items"] == []
    spec = instruments()["nifty50"]
    batch = provider(FakeTicker("^NSEI")).fetch_daily(spec, date(2026, 10, 20), date(2026, 11, 1))
    from dataclasses import replace
    observed = replace(batch, retrieved_at=datetime.now(timezone.utc) - timedelta(minutes=1))
    assert ingest_batch(db, observed)["inserted"] == 2
    db.commit()
    actual = client.get("/api/v1/market/instruments/nifty50/history?basis=adjusted_close").json()
    assert len(actual["items"]) == 2
    assert actual["items"][0]["close"] == 103.5 and actual["items"][0]["raw_close"] == 104
    assert actual["adjusted_ohlc_available"] is False and actual["items"][0]["open"] is None and actual["items"][0]["raw_open"] == 100
    assert actual["items"][0]["currency"] == "INR" and actual["items"][0]["price_basis"] == "raw_ohlc_adjusted_close"
    assert client.get("/api/v1/market/instruments/nifty50/history", params={"as_of": (observed.retrieved_at - timedelta(seconds=1)).isoformat()}).json()["items"] == []
    assert client.get("/api/v1/market/instruments/nifty50/history?basis=bad").status_code == 422
    assert client.get("/api/v1/market/instruments/unknown/history").status_code == 404
    assert client.post("/api/v1/admin/market/refresh", json={"instrument_id": "nifty50"}).status_code == 401
    monkeypatch.setenv("MARKET_DATA_RESEARCH_ENABLED", "false")
    assert client.get("/api/v1/market/instruments").json()["mode"] == "unavailable"
