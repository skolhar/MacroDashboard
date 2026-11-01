"""Strict parser for reviewed RBI WSS reserves tables (HTML or text-layer PDF).

Only the first as-of column is accepted. A publisher PDF with no extractable
text, a changed layout, or an ambiguous week is rejected for manual review.
"""
import re
import subprocess
import tempfile
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal
from html.parser import HTMLParser
from pathlib import Path

from .india_release import ReleaseManifest, validate_manifest


TOLERANCE_USD_MN = Decimal("3")  # five independently rounded USD-million cells
LABELS = {
    "total": r"(?:1\s*)?Total Reserves",
    "foreign_currency_assets": r"(?:1\.1\s*)?Foreign Currency Assets",
    "gold": r"(?:1\.2\s*)?Gold",
    "sdr": r"(?:1\.3\s*)?SDRs?",
    "imf_reserve_tranche": r"(?:1\.4\s*)?Reserve Position in the IMF",
}
NUMBER = re.compile(r"(?<![A-Za-z])(?:\d{1,3}(?:,\d{3})+|\d+)(?:\.\d+)?(?![A-Za-z])")
WEEK = re.compile(r"(?:week\s+ended|as\s+on)\s*:?\s*((?:\d{1,2}\s+[A-Za-z]+\s+\d{4})|(?:[A-Za-z]+\s+\d{1,2},?\s+\d{4})|(?:\d{4}-\d{2}-\d{2}))", re.I)


@dataclass(frozen=True)
class ReservesRelease:
    reference_week: date
    published_at: datetime
    total_usd_mn: Decimal
    foreign_currency_assets_usd_mn: Decimal
    gold_usd_mn: Decimal
    sdr_usd_mn: Decimal
    imf_reserve_tranche_usd_mn: Decimal

    @property
    def total_usd_bn(self) -> Decimal:
        return self.total_usd_mn / 1000


class _TableText(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts = []

    def handle_data(self, data):
        self.parts.append(data)

    def handle_endtag(self, tag):
        if tag in {"tr", "p", "br", "div", "h1", "h2", "h3"}:
            self.parts.append("\n")
        elif tag in {"td", "th"}:
            self.parts.append("  ")


def _text(raw: bytes) -> str:
    if raw.startswith(b"%PDF-"):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "release.pdf"
            path.write_bytes(raw)
            try:
                result = subprocess.run(["pdftotext", "-layout", "-nopgbrk", str(path), "-"], capture_output=True, timeout=15, check=True)
            except (OSError, subprocess.SubprocessError) as exc:
                raise ValueError("WSS PDF text extraction failed") from exc
            return result.stdout.decode("utf-8", errors="replace")
    if raw.lstrip().lower().startswith((b"<!doctype html", b"<html", b"<table")):
        parser = _TableText()
        parser.feed(raw.decode("utf-8-sig", errors="strict"))
        return "".join(parser.parts)
    raise ValueError("Unsupported original WSS format; use publisher HTML or text-layer PDF")


def parse_rbi_wss_reserves(raw: bytes, manifest: ReleaseManifest) -> ReservesRelease:
    validate_manifest(manifest)
    if manifest.provider != "rbi" or not manifest.definition_version.startswith("rbi-wss-gross-reserves-"):
        raise ValueError("RBI WSS gross-reserves definition required")
    text = _text(raw)
    if "Total Reserves" not in text or not re.search(r"US\s*\$?\s*(?:Mn\.?|Million)", text, re.I):
        raise ValueError("WSS gross-reserves table and USD-million unit required")
    if not re.search(r"(?:₹|Rs\.?|INR)\s*(?:Cr\.?|Crore)", text, re.I):
        raise ValueError("WSS INR-crore / USD-million paired columns required")
    weeks = set()
    for match in WEEK.finditer(text):
        raw_date = match.group(1).replace(",", "").strip()
        try:
            parsed = date.fromisoformat(raw_date)
        except ValueError:
            parsed = None
            for fmt in ("%d %B %Y", "%B %d %Y", "%d %b %Y", "%b %d %Y"):
                try:
                    parsed = datetime.strptime(raw_date, fmt).date()
                    break
                except ValueError:
                    pass
        if parsed is not None:
            weeks.add(parsed)
    if len(weeks) != 1:
        raise ValueError("Exactly one explicit WSS reference week is required")
    week = weeks.pop()
    if week > manifest.published_at.date():
        raise ValueError("WSS reference week follows reviewed publication date")
    values = {}
    for key, label in LABELS.items():
        matches = []
        for line in text.splitlines():
            found = re.search(r"^\s*" + label + r"\b", line, re.I)
            if not found:
                continue
            nums = NUMBER.findall(line[found.end():])
            if len(nums) >= 2:
                matches.append(Decimal(nums[1].replace(",", "")))
        if len(matches) != 1 or matches[0] < 0:
            raise ValueError(f"Exactly one nonnegative first USD-million value required for {key}")
        values[key] = matches[0]
    if values["total"] <= 0 or abs(values["total"] - sum(values[k] for k in values if k != "total")) > TOLERANCE_USD_MN:
        raise ValueError("WSS gross total differs from component sum by more than 3 USD million")
    return ReservesRelease(week, manifest.published_at, values["total"], values["foreign_currency_assets"], values["gold"], values["sdr"], values["imf_reserve_tranche"])
