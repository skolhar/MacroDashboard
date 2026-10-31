"""Provider-neutral observations and explicit unavailable adapters."""
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from typing import Protocol


@dataclass(frozen=True)
class SourceObservation:
    indicator_id: str
    value: Decimal
    unit: str
    period_start: date
    period_end: date
    published_at: datetime
    provider: str
    source_reference: str
    vintage_id: str
    quality: str = "verified"
    is_demo: bool = False


class SourceAdapter(Protocol):
    provider: str
    indicators: tuple[str, ...]

    def fetch(self, as_of: datetime) -> tuple[bytes, list[SourceObservation]]: ...


class DataUnavailable(RuntimeError):
    pass


@dataclass(frozen=True)
class UnavailableAdapter:
    provider: str
    indicators: tuple[str, ...]
    reason: str

    def fetch(self, as_of: datetime) -> tuple[bytes, list[SourceObservation]]:
        raise DataUnavailable(self.reason)
