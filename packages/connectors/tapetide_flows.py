"""Permitted daily FII/DII net-flow retrieval from Tapetide.

Tapetide is an AI-first research platform that explicitly supports machine
access: every page has a Markdown twin (see llms.txt), and the same data is
available through the documented REST API (api.tapetide.com/v1, bearer token,
free tier). This adapter prefers the tokened REST endpoint, whose cumulative
flow chart yields exact daily net flows for a full year, and falls back to
parsing the Markdown twin of the FII/DII page when no token is configured.
Failures fail closed; no values are invented.
"""
import os
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
API_BASE = "https://api.tapetide.com/v1"
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


def _record(indicator_id: str, value: Decimal, day: date, now: datetime) -> SourceObservation:
    digest = sha256(f"{indicator_id}:{day}:{value}".encode()).hexdigest()
    declared = datetime(day.year, day.month, day.day, _DECLARED_RELEASE_HOUR, tzinfo=IST)
    return SourceObservation(
        indicator_id=indicator_id, value=value, unit="inr_crore",
        period_start=day, period_end=day,
        published_at=min(declared, now),
        provider=PROVIDER, source_reference=SOURCE_REFERENCE,
        vintage_id=f"tapetide-{digest[:12]}", quality="provisional", is_demo=False,
    )


def parse_flows_markdown(raw: bytes, min_date: date, end_date: date) -> list[SourceObservation]:
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
        if not min_date <= day <= end_date:
            continue
        fii_net, dii_net = _amount(cells[3]), _amount(cells[6])
        for indicator_id, value in ((FPI, fii_net), (DII, dii_net)):
            if value is not None:
                records.append(_record(indicator_id, value, day, now))
    if not records:
        raise ValueError("Tapetide Markdown page contained no attributable net-flow rows")
    return records


def parse_flows_chart(payload: dict, min_date: date, end_date: date) -> list[SourceObservation]:
    """Derive daily net flows by differencing the cumulative flow chart series."""
    chart = payload.get("data", {}).get("chart", {}).get("data", {})
    series, fii_cum, dii_cum = chart.get("t", []), chart.get("fii", []), chart.get("dii", [])
    if len({len(series), len(fii_cum), len(dii_cum)}) != 1 or len(series) < 2:
        raise ValueError("Tapetide flow chart structure changed or incomplete")
    now = datetime.now(timezone.utc)
    records = []
    for index in range(1, len(series)):
        day = date.fromisoformat(series[index])
        if not min_date <= day <= end_date:
            continue
        fii_net = (Decimal(str(fii_cum[index])) - Decimal(str(fii_cum[index - 1]))).quantize(Decimal("0.01"))
        dii_net = (Decimal(str(dii_cum[index])) - Decimal(str(dii_cum[index - 1]))).quantize(Decimal("0.01"))
        for indicator_id, value in ((FPI, fii_net), (DII, dii_net)):
            if value.is_finite():
                records.append(_record(indicator_id, value, day, now))
    if not records:
        raise ValueError("No eligible FPI/DII net-flow observations in the retrieval window")
    return records


def fetch(min_date: date, end_date: date | None = None, client=None) -> tuple[bytes, list[SourceObservation]]:
    """Fetch daily FII/DII net flows: tokened REST chart first, Markdown twin fallback."""
    now = datetime.now(timezone.utc)
    end_date = end_date or now.date()
    owns_client = client is None
    client = client or httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False)
    try:
        token = os.environ.get("TAPETIDE_API_TOKEN", "").strip()
        if token:
            try:
                response = client.get(f"{API_BASE}/market/fii-dii", params={"chart_interval": "1y"}, headers={"Authorization": f"Bearer {token}"})
                response.raise_for_status()
                records = parse_flows_chart(response.json(), min_date, end_date)
                return response.content, records
            except (httpx.HTTPError, ValueError, KeyError):
                pass  # fail soft to the Markdown twin; the job reports per-source errors
        response = client.get(PAGE_URL)
        response.raise_for_status()
        raw = response.content
        return raw, parse_flows_markdown(raw, min_date, end_date)
    finally:
        if owns_client:
            client.close()
