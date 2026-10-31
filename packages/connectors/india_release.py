"""Operator-supplied Indian release packages with explicit provenance and rights.

This parser does not fetch, scrape, or confer redistribution rights. The operator
must retain the original release and independent evidence of its publication time.
"""
import csv
import io
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation
from hashlib import sha256
from urllib.parse import urlparse

from .base import SourceObservation


FIELDS = {"indicator_id", "value", "unit", "period_start", "period_end", "vintage_id", "quality"}
PROVIDERS = {
    "rbi": ("rbi.org.in", "www.rbi.org.in", "statistics.rbi.org.in", "data.rbi.org.in", "wss.rbi.org.in"),
    "nsdl": ("nsdl.co.in", "fpi.nsdl.co.in", "pilot.fpi.nsdl.co.in"),
    "amfi": ("amfiindia.com", "www.amfiindia.com"),
    "licensed_brent": (),
}
INDICATORS = {
    "rbi": {"usd_inr_spot": "INR_per_USD", "fx_gross_reserves_usd": "USD_bn", "india_10y_yield": "pct"},
    "nsdl": {"fpi_equity_net_inr": "INR_cr", "fpi_debt_net_inr": "INR_cr"},
    "amfi": {"sip_contribution_inr": "INR_cr", "midcap_mf_net_inr": "INR_cr", "smallcap_mf_net_inr": "INR_cr"},
    "licensed_brent": {"brent_usd": "USD_per_bbl"},
}


def _valid_url(value: str, hosts: tuple[str, ...]) -> bool:
    parsed = urlparse(value)
    return parsed.scheme == "https" and bool(parsed.hostname) and not parsed.username and not parsed.password and not parsed.fragment and (not hosts or parsed.hostname in hosts)


@dataclass(frozen=True)
class ReleaseManifest:
    provider: str
    source_reference: str
    publication_evidence_url: str
    published_at: datetime
    source_sha256: str
    redistribution_basis: str
    definition_version: str


def parse_release_package(raw: bytes, manifest: ReleaseManifest) -> list[SourceObservation]:
    """Parse a reviewed extract; hash is of original publisher bytes, not this extract.

    Without a proven release timestamp, a historical extract cannot be imported.
    A license/permission record is required outside this payload for public display.
    """
    if manifest.provider not in INDICATORS:
        raise ValueError("Unknown source provider")
    hosts = PROVIDERS[manifest.provider]
    if not _valid_url(manifest.source_reference, hosts) or not _valid_url(manifest.publication_evidence_url, hosts):
        raise ValueError("Source and publication evidence must be HTTPS URLs on the approved provider host")
    if manifest.published_at.tzinfo is None or manifest.published_at > datetime.now(timezone.utc):
        raise ValueError("Verified publication timestamp with timezone required")
    if len(manifest.source_sha256) != 64 or any(c not in "0123456789abcdef" for c in manifest.source_sha256):
        raise ValueError("Original source SHA-256 required")
    if manifest.redistribution_basis not in {"written-permission", "open-license"}:
        raise ValueError("Documented redistribution right required")
    if not manifest.definition_version or len(manifest.definition_version) > 80:
        raise ValueError("Indicator definition version required")
    if not raw or len(raw) > 1_000_000:
        raise ValueError("Extract must be nonempty and at most 1 MB")
    try:
        reader = csv.DictReader(io.StringIO(raw.decode("utf-8-sig", errors="strict")))
        if not reader.fieldnames or set(reader.fieldnames) != FIELDS:
            raise ValueError("Unexpected extract columns")
        rows = []
        for row in reader:
            if None in row or any(v is None for v in row.values()):
                raise ValueError("Malformed extract row")
            if any(v.lstrip().startswith(("=", "+", "-", "@")) for k, v in row.items() if k != "value"):
                raise ValueError("Formula-like field rejected")
            indicator = row["indicator_id"]
            if INDICATORS[manifest.provider].get(indicator) != row["unit"]:
                raise ValueError("Indicator or unit not approved for provider")
            start, end = date.fromisoformat(row["period_start"]), date.fromisoformat(row["period_end"])
            if start > end or end > manifest.published_at.date():
                raise ValueError("Period must precede documented release")
            if row["quality"] not in {"verified", "provisional", "revised"}:
                raise ValueError("Unsupported quality")
            value = Decimal(row["value"])
            if not value.is_finite():
                raise ValueError("Non-finite value")
            vintage = f"{manifest.definition_version}:{row['vintage_id']}"
            if not row["vintage_id"] or len(vintage) > 100:
                raise ValueError("Vintage required")
            rows.append(SourceObservation(indicator, value, row["unit"], start, end, manifest.published_at, manifest.provider, manifest.source_reference, vintage, row["quality"]))
            if len(rows) > 5000:
                raise ValueError("Too many rows")
    except (UnicodeDecodeError, InvalidOperation) as exc:
        raise ValueError("Invalid extract encoding or number") from exc
    if not rows:
        raise ValueError("Empty extract")
    return rows


def extract_sha256(raw: bytes) -> str:
    return sha256(raw).hexdigest()
