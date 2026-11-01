from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Protocol
from zoneinfo import ZoneInfo
import yaml

REGISTRY = Path(__file__).resolve().parents[2] / "config" / "market_instruments.yaml"


@dataclass(frozen=True)
class Instrument:
    id: str
    name: str
    kind: str
    market: str
    currency: str
    timezone: str
    yahoo: str | None
    upstox: str | None

    def symbol(self, provider: str) -> str | None:
        if provider not in {"yahoo", "upstox"}:
            raise ValueError("Unknown market provider")
        return getattr(self, provider)


@dataclass(frozen=True)
class MarketCandle:
    session_date: date
    open: Decimal
    high: Decimal
    low: Decimal
    close: Decimal
    adjusted_close: Decimal | None
    volume: int | None


@dataclass(frozen=True)
class MarketBatch:
    instrument: Instrument
    provider: str
    symbol: str
    retrieved_at: datetime
    source_url: str
    candles: tuple[MarketCandle, ...]
    exchange_timezone: str
    provider_exchange: str | None = None
    rejected_rows: int = 0
    quality: str = "secondary_unverified"
    contract_identity: str | None = None
    roll_policy: str | None = None


class MarketProvider(Protocol):
    name: str
    def fetch_daily(self, instrument: Instrument, start: date, end: date) -> MarketBatch: ...


def instruments() -> dict[str, Instrument]:
    raw = yaml.safe_load(REGISTRY.read_text())
    result = {}
    for item in raw["instruments"]:
        spec = Instrument(**item)
        ZoneInfo(spec.timezone)
        if spec.id in result:
            raise ValueError("Duplicate market instrument")
        result[spec.id] = spec
    return result
