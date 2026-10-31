"""Deterministic synthetic fixtures. Values are arbitrary test inputs, never quotes."""
import json
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from packages.domain.config import registry
from packages.domain.models import IndicatorDefinition, Observation
from packages.domain.store import engine

IST = timezone(timedelta(hours=5, minutes=30))
END = date(2026, 10, 30)


def synthetic_value(id, n):
    # Deliberately formulaic and unmistakably synthetic; never attributed to a market publisher.
    return {
        "usd_inr_spot": lambda: 70 + n * .018,
        "brent_usd": lambda: 75 + (n % 20) * .12,
        "india_10y_yield": lambda: 6 + n * .001,
        "us_10y_yield": lambda: 3 + n * .001,
        "dxy": lambda: 90 + n * .016,
        "fpi_equity_net_inr": lambda: -200 - (n % 5) * 20,
        "midcap150_pe": lambda: 20 + (n % 60) * .02,
        "smallcap250_pe": lambda: 25 + (n % 75) * .02,
        "fx_gross_reserves_usd": lambda: 500 - n * .1,
        "rbi_net_forward_usd": lambda: -10 - n * .05,
        "sip_contribution_inr": lambda: 10000 + n * 100,
        "nifty_eps_revision_3m": lambda: 1 - n * .02,
    }[id]()


def seed(session):
    for id, item in registry().items():
        if not session.get(IndicatorDefinition, id):
            session.add(IndicatorDefinition(**{**item, "source_priority": json.dumps(item["source_priority"])}))
    session.flush()
    for id, item in registry().items():
        frequency = item["frequency"]
        dates = []
        if frequency == "business_daily":
            d = END
            while len(dates) < 260:
                if d.weekday() < 5:
                    dates.append(d)
                d -= timedelta(days=1)
            dates.reverse()
        elif frequency == "weekly":
            dates = [END - timedelta(weeks=n) for n in range(17, -1, -1)]
        else:
            dates = [date(2025 + (5 + n) // 12, (5 + n) % 12 + 1, 1) for n in range(20)]
        for n, d in enumerate(dates):
            period_end = d if frequency != "monthly" else (date(d.year + (d.month == 12), d.month % 12 + 1, 1) - timedelta(days=1))
            released = datetime.combine(period_end + timedelta(days=item["publication_lag_days"]), time(18), IST).astimezone(timezone.utc)
            # All fixtures are known by the demo as-of; later monthly periods remain excluded.
            if released > datetime(2026, 10, 31, tzinfo=timezone.utc):
                continue
            vintage = f"synthetic-{id}-{period_end.isoformat()}"
            exists = session.scalar(select(Observation.id).where(Observation.indicator_id == id, Observation.vintage_id == vintage))
            if exists:
                continue
            session.add(Observation(indicator_id=id, period_start=d, period_end=period_end, value=Decimal(str(round(synthetic_value(id, n), 5))), unit=item["unit"], published_at=released, ingested_at=released + timedelta(minutes=10), provider="synthetic_fixture", source_url=None, vintage_id=vintage, quality="demo", is_revision=False))
    session.commit()


if __name__ == "__main__":
    with Session(engine()) as session:
        seed(session)
