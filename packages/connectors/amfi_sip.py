"""Permitted secondary AMFI monthly SIP-contribution retrieval.

AMFI no longer serves its SIP-data page at a stable automated URL; this adapter
reads the Vrid AMFI monthly dataset, a public JSON republishing AMFI monthly
releases with attribution. Plain unauthenticated GET; failures fail closed;
values are never invented for unpublished months.
"""
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from zoneinfo import ZoneInfo
import json

import httpx

from .base import SourceObservation
from .india_capital_flows import SIP

DATA_URL = "https://storage.googleapis.com/vrid-12.appspot.com/data/amfi_overall_data.json"
SOURCE_REFERENCE = "https://vrid.in/mutual_fund_insights"
PROVIDER = "vrid_amfi_secondary"
IST = ZoneInfo("Asia/Kolkata")
_DECLARED_RELEASE_DAY = 10  # AMFI monthly releases are published around the 10th


def parse_sip_months(raw: bytes, min_month: tuple[int, int], end_month: tuple[int, int]) -> list[SourceObservation]:
    """Extract monthly SIP contribution observations from the attributed dataset."""
    if not raw or len(raw) > 4_000_000:
        raise ValueError("AMFI secondary dataset is empty or oversized")
    try:
        data = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise ValueError("AMFI secondary dataset is not valid JSON") from exc
    months = data.get("monthly") if isinstance(data, dict) else None
    if not isinstance(months, list):
        raise ValueError("AMFI secondary dataset structure changed")
    now = datetime.now(timezone.utc)
    records = []
    for item in months:
        if not isinstance(item, dict):
            continue
        try:
            year, mon = (int(part) for part in str(item.get("month", "")).split("-"))
        except ValueError:
            continue
        if (year, mon) < min_month or (year, mon) > end_month:
            continue
        raw_value = item.get("sipInflows")
        if raw_value is None:
            continue  # unpublished month; never zero-filled
        try:
            amount = Decimal(str(raw_value))
        except InvalidOperation:
            continue
        if not amount.is_finite():
            continue
        period_start = date(year, mon, 1)
        period_end = date(year, mon, monthrange(year, mon)[1])
        digest = sha256(f"{SIP}:{year:04d}-{mon:02d}:{amount}".encode()).hexdigest()
        declared = datetime(year + (mon == 12), mon % 12 + 1, _DECLARED_RELEASE_DAY, 18, tzinfo=IST)
        records.append(SourceObservation(
            indicator_id=SIP, value=amount, unit="inr_crore",
            period_start=period_start, period_end=period_end,
            published_at=min(declared, now),
            provider=PROVIDER, source_reference=SOURCE_REFERENCE,
            vintage_id=f"vrid-{digest[:12]}", quality="provisional", is_demo=False,
        ))
    if not records:
        raise ValueError("No eligible SIP contribution months in the retrieval window")
    return records


def fetch_sip(min_month: tuple[int, int], end_month: tuple[int, int] | None = None, client=None) -> tuple[bytes, list[SourceObservation]]:
    """Fetch monthly SIP contributions from the attributed secondary source."""
    now = datetime.now(timezone.utc)
    end_month = end_month or (now.year, now.month)
    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False)
    try:
        response = client.get(DATA_URL)
        response.raise_for_status()
        raw = response.content
    finally:
        if owns_client:
            client.close()
    return raw, parse_sip_months(raw, min_month, end_month)
