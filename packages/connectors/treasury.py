"""Official U.S. Treasury XML par yield feed; no key required."""
from datetime import datetime, time, timezone
from decimal import Decimal
from xml.etree import ElementTree as ET
import httpx
from .base import SourceObservation

TREASURY_URL = "https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml"


def parse_treasury_xml(content: bytes, received_at: datetime, source_url: str) -> list[SourceObservation]:
    if len(content) > 5_000_000 or b"<!DOCTYPE" in content.upper() or b"<!ENTITY" in content.upper():
        raise ValueError("Unsafe or oversized Treasury XML")
    root = ET.fromstring(content)
    result = []
    for entry in root.iter():
        if entry.tag.rsplit("}", 1)[-1] != "entry":
            continue
        fields = {node.tag.rsplit("}", 1)[-1]: (node.text or "").strip() for node in entry.iter()}
        raw_date = fields.get("NEW_DATE") or fields.get("DATE")
        raw_yield = fields.get("BC_10YEAR") or fields.get("BC_10_YEAR")
        if not raw_date or not raw_yield:
            continue
        day = datetime.fromisoformat(raw_date.replace("Z", "+00:00")).date()
        value = Decimal(raw_yield)
        if value <= 0 or value > 30:
            raise ValueError("Invalid Treasury 10-year yield")
        # XML 'updated' may change with later feed rebuilds. Ingestion time is
        # conservative and prevents an unverified historical release timestamp.
        published = received_at.astimezone(timezone.utc)
        result.append(SourceObservation("us_10y_yield", value, "pct", day, day, published, "us_treasury", source_url, f"treasury-{day.isoformat()}-{value}"))
    if not result:
        raise ValueError("Treasury feed contained no 10-year yields")
    return result


class TreasuryAdapter:
    provider = "us_treasury"
    indicators = ("us_10y_yield",)

    def __init__(self, client=None):
        self.client = client

    def fetch(self, as_of: datetime) -> tuple[bytes, list[SourceObservation]]:
        if as_of.tzinfo is None:
            raise ValueError("as_of needs timezone")
        month = as_of.strftime("%Y%m")
        url = f"{TREASURY_URL}?data=daily_treasury_yield_curve&field_tdr_date_value_month={month}"
        if self.client is None:
            with httpx.Client(timeout=10, follow_redirects=False) as client:
                response = client.get(url)
        else:
            response = self.client.get(url)
        response.raise_for_status()
        if len(response.content) > 5_000_000:
            raise ValueError("Treasury response too large")
        now = datetime.now(timezone.utc)
        records = [r for r in parse_treasury_xml(response.content, now, url) if r.period_end <= as_of.date()]
        return response.content, records
