from datetime import date, datetime, timedelta
from functools import lru_cache
import yaml
from .config import ROOT


@lru_cache
def calendar_data():
    return yaml.safe_load((ROOT / "config/calendars.yaml").read_text())


def market_for(indicator_id: str) -> str:
    return "us" if indicator_id.startswith(("us_", "nasdaq", "dxy", "hyperscaler")) else "india"


def is_session(day: date, market: str) -> bool | None:
    year = calendar_data()[market].get(str(day.year))
    if year is None:
        return None
    if day in year["special_open"]:
        return True
    return day.weekday() < 5 and day not in year["closed"]


def sessions_between(start: date, end: date, market: str) -> int | None:
    current = start + timedelta(days=1)
    count = 0
    while current <= end:
        open_day = is_session(current, market)
        if open_day is None:
            return None
        count += int(open_day)
        current += timedelta(days=1)
    return count


def recent_sessions(as_of: datetime, market: str, count: int) -> list[date]:
    day = as_of.date()
    result = []
    for _ in range(370):
        if is_session(day, market):
            result.append(day)
            if len(result) >= count:
                break
        day -= timedelta(days=1)
    return list(reversed(result))
