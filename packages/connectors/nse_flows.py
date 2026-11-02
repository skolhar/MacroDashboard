"""Permitted secondary FII/DII cash-market net-flow retrieval.

NSE's own FII/DII API endpoint is bot-protected; bypassing that protection is
not permitted. This adapter reads the Groww FII/DII activity page, which
republishes NSE cash-market disclosures with attribution, using a plain
unauthenticated GET request. Failures fail closed; no values are invented and
no gross-turnover column is ever read as a net flow.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from zoneinfo import ZoneInfo
import json
import re

import httpx

from .base import SourceObservation
from .india_capital_flows import FPI, DII

PAGE_URL = "https://groww.in/fii-dii-data"
SOURCE_REFERENCE = "https://groww.in/fii-dii-data"
PROVIDER = "groww_fii_dii"
IST = ZoneInfo("Asia/Kolkata")
_DECLARED_RELEASE_HOUR = 18  # exchange flows are published after market close


@dataclass(frozen=True)
class FlowRow:
    day: date
    fii_net: Decimal | None
    dii_net: Decimal | None


def _enclosing_object(text: str, position: int) -> str | None:
    """Return the complete JSON object enclosing `position` (order-agnostic)."""
    depth = 0
    start = None
    for index in range(position, -1, -1):
        char = text[index]
        if char == "}":
            depth += 1
        elif char == "{":
            if depth == 0:
                start = index
                break
            depth -= 1
    if start is None:
        return None
    depth = 0
    for index in range(start, min(start + 4000, len(text))):
        if text[index] == "{":
            depth += 1
        elif text[index] == "}":
            depth -= 1
            if depth == 0:
                return text[start:index + 1]
    return None


def _iter_objects(text: str):
    """Yield complete JSON objects that contain a "date" key."""
    for match in re.finditer(r'"date"\s*:\s*"(\d{4}-\d{2}-\d{2})"', text):
        chunk = _enclosing_object(text, match.start())
        if chunk is not None:
            yield chunk


def _net(value: dict | None) -> Decimal | None:
    if not isinstance(value, dict) or "netBuySell" not in value:
        return None
    try:
        result = Decimal(str(value["netBuySell"]))
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def parse_flows_page(raw: bytes) -> list[FlowRow]:
    """Extract daily FPI/DII net-flow rows from the attributed secondary page."""
    if not raw or len(raw) > 4_000_000:
        raise ValueError("Secondary flow page is empty or oversized")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Secondary flow page is not valid UTF-8") from exc
    rows: dict[date, FlowRow] = {}
    for chunk in _iter_objects(text):
        try:
            item = json.loads(chunk)
        except ValueError:
            continue
        if not isinstance(item, dict) or not item.get("date"):
            continue
        try:
            day = date.fromisoformat(str(item["date"]))
        except ValueError:
            continue
        fii, dii = _net(item.get("fii")), _net(item.get("dii"))
        if fii is None and dii is None:
            continue
        if day in rows:
            continue  # first occurrence wins; page order is not standardised
        rows[day] = FlowRow(day, fii, dii)
    if not rows:
        raise ValueError("Secondary flow page contained no attributable net-flow rows")
    return [rows[day] for day in sorted(rows)]


def _published_at(day: date, now: datetime) -> datetime:
    """Declared exchange convention (post-close release); never a future time."""
    declared = datetime(day.year, day.month, day.day, _DECLARED_RELEASE_HOUR, tzinfo=IST)
    return min(declared, now)


def fetch(min_date: date, end_date: date | None = None, client=None) -> tuple[bytes, list[SourceObservation]]:
    """Fetch daily FPI/DII net flows from the attributed secondary source."""
    now = datetime.now(timezone.utc)
    end_date = end_date or now.date()
    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False, headers={"User-Agent": "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 Chrome/120.0 Safari/537.36"})
    try:
        response = client.get(PAGE_URL)
        response.raise_for_status()
        raw = response.content
    finally:
        if owns_client:
            client.close()
    rows = [row for row in parse_flows_page(raw) if min_date <= row.day <= end_date]
    records = []
    for row in rows:
        for indicator_id, value in ((FPI, row.fii_net), (DII, row.dii_net)):
            if value is None:
                continue
            digest = sha256(f"{indicator_id}:{row.day}:{value}".encode()).hexdigest()
            records.append(SourceObservation(
                indicator_id=indicator_id, value=value, unit="inr_crore",
                period_start=row.day, period_end=row.day,
                published_at=_published_at(row.day, now),
                provider=PROVIDER, source_reference=SOURCE_REFERENCE,
                vintage_id=f"groww-{digest[:12]}", quality="provisional", is_demo=False,
            ))
    if not records:
        raise ValueError("No eligible FPI/DII net-flow observations in the retrieval window")
    return raw, records
