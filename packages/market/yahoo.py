"""Yahoo/yfinance daily-history adapter for isolated research use only."""
import math
import time
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from urllib.parse import quote
from zoneinfo import ZoneInfo

from .base import Instrument, MarketBatch, MarketCandle


class MarketSourceUnavailable(RuntimeError):
    pass


class YahooProvider:
    name = "yahoo"

    def __init__(self, ticker_factory=None, sleep=time.sleep, clock=None):
        if ticker_factory is None:
            import yfinance as yf
            ticker_factory = yf.Ticker
        self.ticker_factory = ticker_factory
        self.sleep = sleep
        self.clock = clock or (lambda: datetime.now(timezone.utc))

    def fetch_daily(self, instrument: Instrument, start: date, end: date) -> MarketBatch:
        symbol = instrument.symbol(self.name)
        if not symbol or start >= end or (end - start).days > 365 * 15:
            raise ValueError("Yahoo symbol or requested history range is invalid")
        ticker = self.ticker_factory(symbol)
        frame = None
        for attempt in range(3):
            try:
                frame = ticker.history(start=start.isoformat(), end=end.isoformat(), interval="1d", auto_adjust=False, back_adjust=False, repair=False, actions=False, keepna=False, timeout=15, raise_errors=True)
                break
            except Exception as exc:
                transient = any(part in type(exc).__name__.lower() for part in ("rate", "timeout", "connection", "http"))
                if attempt == 2 or not transient:
                    raise MarketSourceUnavailable(type(exc).__name__) from exc
                self.sleep(2 ** attempt)
        if frame is None or frame.empty:
            raise MarketSourceUnavailable("EmptyHistory")
        try:
            metadata = ticker.get_history_metadata()
        except Exception as exc:
            raise MarketSourceUnavailable("MissingMetadata") from exc
        currency = metadata.get("currency")
        exchange_timezone = metadata.get("exchangeTimezoneName")
        if currency != instrument.currency or not exchange_timezone:
            raise MarketSourceUnavailable("CurrencyOrTimezoneMismatch")
        try:
            zone = ZoneInfo(exchange_timezone)
        except Exception as exc:
            raise MarketSourceUnavailable("InvalidExchangeTimezone") from exc
        if exchange_timezone != instrument.timezone:
            raise MarketSourceUnavailable("MappedTimezoneMismatch")
        rows = []
        rejected = 0
        seen = set()
        for timestamp, row in frame.iterrows():
            try:
                if timestamp.tzinfo is None:
                    raise ValueError("Daily bar lacks exchange timezone")
                session_date = timestamp.to_pydatetime().astimezone(zone).date()
                if session_date < start or session_date >= end or session_date >= self.clock().astimezone(zone).date():
                    # A still-open local session is not a bad historical row.
                    continue
                if session_date in seen:
                    rejected += 1
                    continue
                values = {key: _decimal(row[key]) for key in ("Open", "High", "Low", "Close")}
                adjusted = _decimal(row["Adj Close"]) if "Adj Close" in row and not _missing(row["Adj Close"]) else None
                volume = None if "Volume" not in row or _missing(row["Volume"]) else int(row["Volume"])
                positive_required = instrument.kind != "futures_proxy"
                if (positive_required and min(values.values()) <= 0) or values["Low"] > min(values["Open"], values["Close"]) or values["High"] < max(values["Open"], values["Close"]) or values["High"] < values["Low"] or (adjusted is not None and positive_required and adjusted <= 0) or (volume is not None and (volume < 0 or float(row["Volume"]) != volume)):
                    raise ValueError("Invalid OHLCV")
                seen.add(session_date)
                rows.append(MarketCandle(session_date, values["Open"], values["High"], values["Low"], values["Close"], adjusted, volume))
            except (ValueError, KeyError, TypeError, InvalidOperation, OverflowError):
                rejected += 1
        if not rows:
            raise MarketSourceUnavailable("NoValidCompletedBars")
        rows.sort(key=lambda item: item.session_date)
        futures = instrument.kind == "futures_proxy"
        return MarketBatch(instrument, self.name, symbol, self.clock(), f"https://finance.yahoo.com/quote/{quote(symbol, safe='')}/history/", tuple(rows), exchange_timezone, metadata.get("exchangeName"), rejected, "secondary_partial" if rejected else "secondary_unverified", f"{symbol}:continuous_front_month" if futures else None, "vendor_roll_unknown" if futures else None)


def _missing(value):
    try:
        return value is None or math.isnan(float(value))
    except (TypeError, ValueError):
        return False


def _decimal(value):
    number = Decimal(str(value))
    if not number.is_finite():
        raise ValueError("Nonfinite price")
    return number
