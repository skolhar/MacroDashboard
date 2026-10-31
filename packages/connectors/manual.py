"""Strict human-reviewed CSV mapping; no network or provider scraping."""
import csv
import io
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from .base import SourceObservation

FIELDS = {"indicator_id", "value", "unit", "period_start", "period_end", "published_at", "vintage_id", "source_reference", "quality"}


def parse_manual_csv(raw: bytes, provider: str) -> list[SourceObservation]:
    if not raw or len(raw) > 1_000_000:
        raise ValueError("CSV must be nonempty and at most 1 MB")
    try:
        text = raw.decode("utf-8-sig", errors="strict")
    except UnicodeDecodeError as exc:
        raise ValueError("CSV must be UTF-8") from exc
    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames or set(reader.fieldnames) != FIELDS:
        raise ValueError("CSV columns must exactly match the documented schema")
    output = []
    for row in reader:
        if None in row or any(value is None for value in row.values()):
            raise ValueError("Malformed CSV row")
        if any(value.lstrip().startswith(("=", "+", "-", "@")) for key, value in row.items() if key not in {"value"}):
            raise ValueError("Formula-like CSV field rejected")
        try:
            published = datetime.fromisoformat(row["published_at"].replace("Z", "+00:00"))
            output.append(SourceObservation(indicator_id=row["indicator_id"], value=Decimal(row["value"]), unit=row["unit"], period_start=date.fromisoformat(row["period_start"]), period_end=date.fromisoformat(row["period_end"]), published_at=published, provider=provider, source_reference=row["source_reference"], vintage_id=row["vintage_id"], quality=row["quality"], is_demo=False))
        except (ValueError, InvalidOperation) as exc:
            raise ValueError("Invalid CSV value, date or timestamp") from exc
        if len(output) > 5000:
            raise ValueError("Too many CSV rows")
    if not output:
        raise ValueError("CSV contains no data rows")
    return output
