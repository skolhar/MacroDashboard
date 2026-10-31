"""Read-only Indian source coverage and point-in-time gap report.

Run in isolated staging: python -m scripts.phase3b_gap_report > gaps.json
Unverified historical trading calendars are reported, never guessed.
"""
import json
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from packages.domain.calendar import is_session
from packages.domain.config import registry
from packages.domain.models import Observation
from packages.domain.settings import settings
from packages.domain.store import engine, observations_at

INDICATORS = ("usd_inr_spot", "fx_gross_reserves_usd", "rbi_net_forward_usd", "india_10y_yield", "fpi_equity_net_inr", "fpi_debt_net_inr", "sip_contribution_inr", "midcap_mf_net_inr", "smallcap_mf_net_inr", "brent_usd")
START = date(2018, 1, 1)


def _months(start: date, end: date) -> list[str]:
    current = date(start.year, start.month, 1)
    output = []
    while current <= end:
        output.append(current.strftime("%Y-%m"))
        current = date(current.year + (current.month == 12), current.month % 12 + 1, 1)
    return output


def coverage(session: Session, as_of: datetime) -> dict:
    if as_of.tzinfo is None:
        raise ValueError("as_of must have timezone")
    end = as_of.astimezone(timezone.utc).date()
    definitions = registry(phase2=True)
    output = {}
    for indicator in INDICATORS:
        system = observations_at(session, indicator, as_of, "system_known", demo=False)
        source = observations_at(session, indicator, as_of, "source_known", demo=False)
        system_periods = {row.period_end for row in system}
        source_months = {row.period_end.strftime("%Y-%m") for row in source}
        missing_dates = []
        unverified_years = []
        if definitions[indicator]["frequency"] == "business_daily":
            for year in range(START.year, end.year + 1):
                if is_session(date(year, 1, 2), "india") is None:
                    unverified_years.append(year)
                    continue
                day = max(START, date(year, 1, 1))
                final = min(end, date(year, 12, 31))
                while day <= final:
                    if is_session(day, "india") and day not in system_periods:
                        missing_dates.append(day.isoformat())
                    day += timedelta(days=1)
        raw = session.scalars(select(Observation).where(Observation.indicator_id == indicator, Observation.is_demo.is_(False), Observation.published_at <= as_of).order_by(Observation.period_end, Observation.published_at)).all()
        output[indicator] = {
            "frequency": definitions[indicator]["frequency"],
            "system_known_count": len(system), "source_known_count": len(source),
            "missing_months_system_known": [month for month in _months(START, end) if month not in {row.period_end.strftime("%Y-%m") for row in system}],
            "missing_months_source_known": [month for month in _months(START, end) if month not in source_months],
            "missing_verified_calendar_dates_system_known": missing_dates,
            "calendar_unverified_years": unverified_years,
            "vintages": [{"period_end": row.period_end.isoformat(), "vintage_id": row.vintage_id, "published_at": row.published_at.isoformat(), "ingested_at": row.ingested_at.isoformat(), "release_review_id": row.release_review_id, "quality": row.quality} for row in raw],
            "unreviewed_vintage_periods": sorted({row.period_end.isoformat() for row in raw if row.release_review_id is None}),
        }
    return {"as_of": as_of.isoformat(), "start": START.isoformat(), "calendar_policy": "Exact missing business dates only for independently verified India calendar years; historical years without a reviewed calendar remain unknown", "indicators": output}


def main():
    config = settings()
    if config.environment not in {"staging", "development", "demo"}:
        raise ValueError("Gap audit is restricted to isolated environments")
    with Session(engine()) as session:
        print(json.dumps(coverage(session, datetime.now(timezone.utc)), indent=2))


if __name__ == "__main__":
    main()
