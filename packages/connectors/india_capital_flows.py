"""Indian capital-flow observations: attributable FPI, DII and mutual-fund flows.

Private research only. Sources are secondary market-participant disclosures
(exchange FPI/DII turnover tables and AMFI mutual-fund releases). The adapter
normalises reporting dates, net versus gross amounts, revisions, units and
data freshness, and never treats a missing release as a zero-flow day.
"""
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Protocol, Sequence

FPI = "india_fpi_equity_net_flow_inr_cr"
DII = "india_dii_equity_net_flow_inr_cr"
MF_NET = "india_mf_equity_net_flow_inr_cr"
SIP = "india_mf_sip_contribution_inr_cr"
NIFTY_CLOSE = "india_nifty50_close_level"
DERIVED_RETURN = "india_nifty50_monthly_return_pct"

UNITS = {FPI: "inr_crore", DII: "inr_crore", MF_NET: "inr_crore", SIP: "inr_crore", NIFTY_CLOSE: "index_points", DERIVED_RETURN: "percent"}


@dataclass(frozen=True)
class CapitalFlowRecord:
    series: str
    period_end: date
    value: Decimal
    revision: str
    published_at: datetime | None
    retrieved_at: datetime
    source_name: str
    source_reference: str
    quality: str
    flow_basis: str
    definition_note: str

    @property
    def unit(self) -> str:
        return UNITS[self.series]

    @property
    def frequency(self) -> str:
        return "daily" if self.series in {FPI, DII, NIFTY_CLOSE} else "monthly"


@dataclass(frozen=True)
class CapitalFlowTable:
    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]
    loaded_at: datetime
    report_title: str
    period_to: str | None


class CapitalFlowSource(Protocol):
    def fetch(self, table: str, as_of: datetime) -> CapitalFlowTable: ...


def _date(value: str) -> date:
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%Y-%m-%d", "%d-%b-%y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    raise ValueError(f"Unrecognised capital-flow reporting date: {value!r}")


def _amount(value: str) -> Decimal:
    cleaned = value.strip().replace(",", "").replace("Rs", "").replace("₹", "").strip()
    if cleaned.endswith("-"):
        cleaned = "-" + cleaned[:-1]
    try:
        return Decimal(cleaned)
    except InvalidOperation as exc:
        raise ValueError(f"Unrecognised capital-flow amount: {value!r}") from exc


def parse_flows(table: CapitalFlowTable, expected: dict[str, str], *, gross_rows: Sequence[str] = ()) -> list[CapitalFlowRecord]:
    """Parse an exchange/AMFI flow table into attributable observations.

    `expected` maps column header -> series key. Headers renamed or re-ordered
    raise immediately so definition changes are never silently absorbed.
    Rows listed in `gross_rows` carry gross turnover, which is preserved but
    never summed with net rows.
    """
    positions = {}
    for index, column in enumerate(table.columns):
        series = expected.get(column.strip())
        if series is not None:
            positions[series] = index
    missing = {v for v in expected.values() if v is not None} - set(positions)
    if missing:
        raise ValueError(f"Capital-flow reporting columns changed; missing {sorted(missing)}")
    records = []
    for raw in table.rows:
        if not raw or all(not cell.strip() for cell in raw):
            continue
        day = _date(raw[0])
        for series, position in positions.items():
            text = raw[position].strip() if position < len(raw) else ""
            if text in {"", "-", "NA", "N.A."}:
                continue
            records.append(CapitalFlowRecord(
                series=series,
                period_end=day,
                value=_amount(text),
                revision="v1",
                published_at=None,
                retrieved_at=table.loaded_at,
                source_name=table.report_title,
                source_reference="",
                quality="secondary",
                flow_basis="gross" if series in gross_rows else "net",
                definition_note=f"Publisher-reported {series.rsplit('_', 2)[-2] if '_' in series else series}; gross rows never summed with net rows",
            ))
    return records


def monthly_returns_from_closes(close_records, *, series=DERIVED_RETURN):
    """Derive month-over-month percent returns from stored month-end closes.

    Index levels are points, not returns, and are never summed into a return
    window. Only month-end closes (last observation per calendar month) are
    used; months without a prior month-end close are skipped so no derived
    return is ever fabricated.
    """
    closes_by_month = {}
    for r in sorted(close_records, key=lambda x: x.period_end):
        if r.series != NIFTY_CLOSE:
            continue
        closes_by_month[(r.period_end.year, r.period_end.month)] = r  # last close wins
    records = []
    for (year, month), close in sorted(closes_by_month.items()):
        prior = (year - 1, 12) if month == 1 else (year, month - 1)
        previous = closes_by_month.get(prior)
        if previous is None or previous.value == 0:
            continue
        pct = (close.value - previous.value) / previous.value * Decimal("100")
        records.append(CapitalFlowRecord(
            series=series, period_end=close.period_end, value=pct,
            revision=close.revision, published_at=close.published_at,
            retrieved_at=close.retrieved_at, source_name=close.source_name,
            source_reference=close.source_reference, quality="derived",
            flow_basis="derived", definition_note="Derived month-over-month percent change of stored month-end index closes; not a publisher return series",
        ))
    return records
