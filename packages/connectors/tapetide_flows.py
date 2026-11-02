"""Permitted secondary daily FII/DII net-flow retrieval from Tapetide.

Tapetide is an AI-first research platform that explicitly supports machine
access: every page has a Markdown twin (see llms.txt) and the FII/DII figures
are stated as daily cash-market net flows in ₹ crore from exchange
publications. This adapter parses the Markdown table of the .md twin with a
plain unauthenticated GET. Failures fail closed; no values are invented.
"""
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from zoneinfo import ZoneInfo
import re

import httpx

from .base import SourceObservation
from .india_capital_flows import FPI, DII

PAGE_URL = "https://tapetide.com/fii-dii-data.md"
SOURCE_REFERENCE = "https://tapetide.com/fii-dii-data.md"
PROVIDER = "tapetide_fii_dii"
IST = ZoneInfo("Asia/Kolkata")
_DECLARED_RELEASE_HOUR = 18  # exchange flows are published after market close


def _amount(text: str) -> Decimal | None:
    cleaned = text.strip().replace(",", "").replace("₹", "").replace("−", "-").replace("Cr", "").strip()
    if not cleaned or cleaned in {"-", "NA", "N.A."}:
        return None
    try:
        result = Decimal(cleaned)
    except InvalidOperation:
        return None
    return result if result.is_finite() else None


def parse_flows_markdown(raw: bytes) -> list[SourceObservation]:
    """Parse the Markdown twin's daily FII/DII net-flow table."""
    if not raw or len(raw) > 2_000_000:
        raise ValueError("Tapetide Markdown page is empty or oversized")
    try:
        text = raw.decode("utf-8", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("Tapetide Markdown page is not valid UTF-8") from exc
    now = datetime.now(timezone.utc)
    records = []
    for line in text.splitlines():
        if not line.startswith("|"):
            continue
        cells = [cell.strip() for cell in line.strip("|").split("|")]
        if len(cells) != 7 or not re.match(r"^\d{4}-\d{2}-\d{2}$", cells[0]):
            continue
        try:
            day = date.fromisoformat(cells[0])
        except ValueError:
            continue
        fii_net, dii_net = _amount(cells[3]), _amount(cells[6])
        for indicator_id, value in ((FPI, fii_net), (DII, dii_net)):
            if value is None:
                continue
            digest = sha256(f"{indicator_id}:{day}:{value}".encode()).hexdigest()
            declared = datetime(day.year, day.month, day.day, _DECLARED_RELEASE_HOUR, tzinfo=IST)
            records.append(SourceObservation(
                indicator_id=indicator_id, value=value, unit="inr_crore",
                period_start=day, period_end=day,
                published_at=min(declared, now),
                provider=PROVIDER, source_reference=SOURCE_REFERENCE,
                vintage_id=f"tapetide-{digest[:12]}", quality="provisional", is_demo=False,
            ))
    if not records:
        raise ValueError("Tapetide Markdown page contained no attributable net-flow rows")
    return records


def fetch(min_date: date, end_date: date | None = None, client=None) -> tuple[bytes, list[SourceObservation]]:
    """Fetch daily FII/DII net flows from the Markdown twin."""
    now = datetime.now(timezone.utc)
    end_date = end_date or now.date()
    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False)
    try:
        response = client.get(PAGE_URL)
        response.raise_for_status()
        raw = response.content
    finally:
        if owns_client:
            client.close()
    records = [record for record in parse_flows_markdown(raw) if record.period_end >= min_date and record.period_end <= end_date]
    if not records:
        raise ValueError("No eligible FPI/DII net-flow observations in the retrieval window")
    return raw, records
