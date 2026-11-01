"""Read-only RBI Innovation Hub DBIE mirror adapter for private research.

This is a secondary mirror, not an original RBI release or a rights grant.
"""
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
import json
import re
import time
import httpx
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config/actor_research.v1.yaml"
MAX_ROWS = 6000
PAGE_SIZE = 500


def registry():
    config = yaml.safe_load(CONFIG_PATH.read_text())
    if config.get("version") != "actor-research-v1" or config.get("source") != "rbi_innovation_hub_dbie_mirror":
        raise ValueError("Unsupported actor research source registry")
    return config


@dataclass(frozen=True)
class MirrorRecord:
    indicator_key: str
    period_end: date
    value: Decimal
    unit: str
    frequency: str
    source_reference: str
    mirror_loaded_at: str
    publisher_path: str
    definition_note: str


def _date(value):
    if not isinstance(value, str):
        return None
    value = value.strip()
    for pattern in ("%b %d, %Y", "%d-%b-%Y"):
        try:
            return datetime.strptime(value, pattern).date()
        except ValueError:
            pass
    return None


def _number(value, signed):
    if value is None or not isinstance(value, str) or not value.strip() or value.strip() in {"-", "−", ".."}:
        return None
    cleaned = value.strip().replace(",", "").replace("−", "-")
    if not re.fullmatch(r"[+-]?\d+(?:\.\d+)?", cleaned):
        raise ValueError("Unexpected RBI mirror numeric value")
    try:
        result = Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError("Invalid RBI mirror numeric value") from exc
    if not result.is_finite() or abs(result) > Decimal("1e12") or (not signed and result < 0):
        raise ValueError("Out-of-range RBI mirror observation")
    return result


def parse_table(metadata, payload, table_key, min_date=date(2018, 1, 1)):
    """Validate publisher labels and units before accepting any numeric row."""
    config = registry()
    spec = config["tables"][table_key]
    info, provenance = metadata.get("data"), metadata.get("provenance")
    if not isinstance(info, dict) or not isinstance(provenance, dict) or any((info.get(k) != expected for k, expected in {"title": spec["title"], "frequency": spec["frequency"], "source": spec["source"], "layout": "columns", "key": spec["path"].replace("/", ".")}.items())):
        raise ValueError("RBI mirror table definition changed")
    if provenance.get("report_name") != spec["title"] or not provenance.get("exported_at") or not info.get("loaded_at"):
        raise ValueError("RBI mirror provenance incomplete")
    columns, matrix = payload.get("columns"), payload.get("rows")
    if not isinstance(columns, list) or not isinstance(matrix, list) or len(matrix) != info.get("row_count") or len(matrix) > MAX_ROWS:
        raise ValueError("RBI mirror row count changed or exceeded bound")
    if "row_no" not in columns or spec["date_column"] not in columns:
        raise ValueError("RBI mirror columns changed")
    rows = []
    for position, raw in enumerate(matrix, 1):
        if not isinstance(raw, list) or len(raw) != len(columns):
            raise ValueError("RBI mirror row width changed")
        row = dict(zip(columns, raw))
        if row["row_no"] != position:
            raise ValueError("RBI mirror row order changed")
        rows.append(row)
    header = rows[spec["header_row"] - 1]
    unit = rows[spec["unit_row"] - 1]
    if spec["unit_marker"] not in str(unit["c1"]):
        raise ValueError("RBI mirror reporting unit changed")
    for key, field in spec["indicators"].items():
        if header[field.get("header_column", field["column"])] != field["header"]:
            raise ValueError(f"RBI mirror definition changed for {key}")
        if spec.get("subheader_row") and rows[spec["subheader_row"] - 1][field["column"]] != spec["subheader_marker"]:
            raise ValueError(f"RBI mirror subunit changed for {key}")
    output = []
    seen = set()
    reported_end = None
    try:
        reported_end = datetime.strptime(provenance.get("period_to", ""), "%d-%b-%Y").date()
    except ValueError:
        pass
    for row in rows[spec["header_row"]:]:
        day = _date(row[spec["date_column"]])
        if day is None:
            if row["row_no"] > spec["header_row"] + 1 and any(str(row[field["column"]] or "").strip() for field in spec["indicators"].values()):
                raise ValueError("RBI mirror numeric row has an unparseable reporting date")
            continue
        if day < min_date:
            continue
        if day > datetime.now(timezone.utc).date():
            raise ValueError("RBI mirror observation is future-dated")
        for key, field in spec["indicators"].items():
            value = _number(row[field["column"]], field["unit"] == "inr_crore_signed")
            if value is None:
                continue
            identity = (key, day)
            if identity in seen:
                raise ValueError("Conflicting RBI mirror duplicate period")
            seen.add(identity)
            note = "Mirror of RBI DBIE; original RBI publication time and historical vintage unknown."
            if table_key == "bank":
                note += " Bank merger affected levels from July 2023; RBI fortnight definition changed in December 2025."
            if table_key == "reserves":
                note += " Foreign-currency asset valuation affects reserves; changes do not prove intervention."
            if table_key == "liquidity":
                note += " Signed positive means net injection and negative means net absorption; operation motive is not identified."
            if reported_end and day > reported_end:
                note += " Mirror catalogue period_to predates this visible row; verify against original RBI release."
            output.append(MirrorRecord(key, day, value, field["unit"], field["frequency"], f"{config['source_url']}/{spec['path']}#row-{row['row_no']}", info["loaded_at"], info["dbie_path"], note))
    return sorted(output, key=lambda item: (item.period_end, item.indicator_key))


class RBIResearchMirrorAdapter:
    provider = "rbi_innovation_hub_dbie_mirror_research"

    def __init__(self, client=None):
        self.client = client

    def _get(self, client, url, params=None):
        for attempt in range(3):
            try:
                response = client.get(url, params=params)
                response.raise_for_status()
                if len(response.content) > 4_000_000:
                    raise ValueError("Oversized RBI mirror response")
                return json.loads(response.content)
            except (httpx.TimeoutException, httpx.NetworkError, httpx.HTTPStatusError) as exc:
                if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code not in {429, 500, 502, 503, 504}:
                    raise
                if attempt == 2:
                    raise
                time.sleep(0.5 * 2 ** attempt)

    def fetch(self, table_key, min_date=date(2018, 1, 1)):
        spec = registry()["tables"].get(table_key)
        if not spec or min_date < date(1990, 1, 1) or min_date > datetime.now(timezone.utc).date():
            raise ValueError("Unsupported RBI mirror table or date")
        url = f"{registry()['source_url']}/{spec['path']}"
        client = self.client or httpx.Client(timeout=httpx.Timeout(30, connect=5), follow_redirects=False)
        try:
            metadata = self._get(client, url)
            count = metadata.get("data", {}).get("row_count")
            if not isinstance(count, int) or count < 1 or count > MAX_ROWS:
                raise ValueError("Invalid RBI mirror row count")
            columns, rows = None, []
            for offset in range(0, count, PAGE_SIZE):
                page = self._get(client, url + "/rows", {"limit": PAGE_SIZE, "offset": offset})
                if columns is None:
                    columns = page.get("columns")
                if page.get("columns") != columns or page.get("offset") != offset or not isinstance(page.get("rows"), list):
                    raise ValueError("RBI mirror pagination changed")
                rows.extend(page["rows"])
            after = self._get(client, url)
            if after.get("data", {}).get("loaded_at") != metadata["data"].get("loaded_at") or after.get("data", {}).get("row_count") != count:
                raise ValueError("RBI mirror refreshed during fetch; retry later")
            return parse_table(metadata, {"columns": columns, "rows": rows}, table_key, min_date)
        finally:
            if self.client is None:
                client.close()
