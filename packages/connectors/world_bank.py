"""Public WDI Indicators API adapter for private Indian macro research."""
from dataclasses import dataclass
from calendar import monthrange
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import time
import httpx
import yaml

REGISTRY_PATH = Path(__file__).resolve().parents[2] / "config/indian_research.v1.yaml"
BASE = "https://api.worldbank.org/v2/country/IND/indicator/"


def indicator_registry():
    data = yaml.safe_load(REGISTRY_PATH.read_text())
    if data.get("version") != "indian-research-v1" or data.get("source_id") != 2:
        raise ValueError("Unsupported Indian research registry")
    return data


@dataclass(frozen=True)
class WDIRecord:
    indicator_key: str
    period_end: date
    value: Decimal
    unit: str
    source_url: str
    dataset_updated: str
    frequency: str = "annual"


def parse_wdi(payload, requested, source_url):
    if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[0], dict) or not isinstance(payload[1], list):
        raise ValueError("Invalid WDI response shape")
    metadata, data = payload
    if int(metadata.get("pages", 0)) != 1 or str(metadata.get("sourceid")) not in {"2", "None"}:
        raise ValueError("Unexpected WDI source or pagination")
    updated = metadata.get("lastupdated")
    if not isinstance(updated, str) or len(updated) != 10:
        raise ValueError("WDI dataset update metadata missing")
    registry = indicator_registry()["indicators"]
    codes = {item["code"]: (key, item) for key, item in registry.items() if key in requested}
    output = []
    for row in data:
        code = row.get("indicator", {}).get("id")
        if code not in codes or row.get("countryiso3code") != "IND" or not isinstance(row.get("date"), str) or len(row["date"]) != 4 or not row["date"].isdigit():
            raise ValueError("Unexpected country, indicator or period in WDI data")
        if row.get("value") is None:
            continue
        try:
            value = Decimal(str(row["value"]))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("Invalid WDI numeric observation") from exc
        if not value.is_finite() or abs(value) > Decimal("1e15"):
            raise ValueError("Out-of-range WDI observation")
        key, spec = codes[code]
        output.append(WDIRecord(key, date(int(row["date"]), 12, 31), value, spec["unit"], source_url, updated))
    if len({(row.indicator_key, row.period_end) for row in output}) != len(output):
        raise ValueError("Conflicting duplicate WDI periods")
    return output


def parse_gem(payload, requested, source_url):
    if not isinstance(payload, list) or len(payload) != 2 or not isinstance(payload[0], dict) or not isinstance(payload[1], list):
        raise ValueError("Invalid GEM response shape")
    metadata, data = payload
    if int(metadata.get("pages", 0)) != 1 or str(metadata.get("sourceid")) not in {"15", "None"}:
        raise ValueError("Unexpected GEM source or pagination")
    updated = metadata.get("lastupdated")
    if not isinstance(updated, str) or len(updated) != 10:
        raise ValueError("GEM dataset update metadata missing")
    registry = indicator_registry()["gem_indicators"]
    codes = {item["code"]: (key, item) for key, item in registry.items() if key in requested}
    output = []
    for row in data:
        code = row.get("indicator", {}).get("id")
        period = row.get("date")
        if code not in codes or (row.get("countryiso3code") != "IND" and row.get("country", {}).get("id") != "IND") or not isinstance(period, str) or len(period) != 7 or period[4] != "M" or not (period[:4] + period[5:]).isdigit():
            raise ValueError("Unexpected country, indicator or period in GEM data")
        year, month = int(period[:4]), int(period[5:])
        if not 1 <= month <= 12:
            raise ValueError("Invalid GEM month")
        if row.get("value") is None:
            continue
        try:
            value = Decimal(str(row["value"]))
        except (InvalidOperation, TypeError) as exc:
            raise ValueError("Invalid GEM numeric observation") from exc
        if not value.is_finite() or abs(value) > Decimal("1e15"):
            raise ValueError("Out-of-range GEM observation")
        key, spec = codes[code]
        output.append(WDIRecord(key, date(year, month, monthrange(year, month)[1]), value, spec["unit"], source_url, updated, "monthly"))
    if len({(row.indicator_key, row.period_end) for row in output}) != len(output):
        raise ValueError("Conflicting duplicate GEM periods")
    return output


class WorldBankIndiaAdapter:
    provider = "world_bank_wdi_research"

    def __init__(self, client=None):
        self.client = client

    def fetch(self, start_year=2000, end_year=None):
        end_year = end_year or datetime.now(timezone.utc).year
        if start_year < 1960 or end_year > datetime.now(timezone.utc).year or end_year < start_year or end_year - start_year > 70:
            raise ValueError("Invalid WDI date range")
        registry = indicator_registry()["indicators"]
        url = BASE + ";".join(spec["code"] for spec in registry.values())
        params = {"format": "json", "date": f"{start_year}:{end_year}", "source": 2, "per_page": 1000}
        response = self._request(url, params)
        return parse_wdi(json.loads(response.content, parse_float=Decimal), set(registry), str(response.url))

    def _request(self, url, params):
        client = self.client or httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False)
        try:
            for attempt in range(3):
                try:
                    response = client.get(url, params=params)
                    response.raise_for_status()
                    break
                except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {429, 500, 502, 503, 504}:
                        raise
                    if attempt == 2:
                        raise
                    time.sleep(0.5 * 2 ** attempt)
            if len(response.content) > 5_000_000:
                raise ValueError("Oversized WDI response")
            return response
        finally:
            if self.client is None:
                client.close()


class WorldBankGEMAdapter(WorldBankIndiaAdapter):
    provider = "world_bank_gem_research"

    def fetch(self, start_year=2018, end_year=None):
        end_year = end_year or datetime.now(timezone.utc).year
        if start_year < 2000 or end_year > datetime.now(timezone.utc).year or end_year < start_year or end_year - start_year > 10:
            raise ValueError("Invalid GEM date range")
        registry = indicator_registry()["gem_indicators"]
        url = BASE + ";".join(spec["code"] for spec in registry.values())
        params = {"format": "json", "date": f"{start_year}M01:{end_year}M12", "source": 15, "per_page": 1000}
        response = self._request(url, params)
        return parse_gem(json.loads(response.content, parse_float=Decimal), set(registry), str(response.url))
