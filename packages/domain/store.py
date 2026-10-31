import os
from datetime import datetime, timezone
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from .models import IndicatorDefinition, Observation


def engine():
    return create_engine(os.getenv("DATABASE_URL", "sqlite:///./macro.db"), pool_pre_ping=True)


def observations_at(session: Session, indicator_id: str, as_of: datetime, mode="system_known", demo=True):
    as_of = as_of.astimezone(timezone.utc)
    query = select(Observation).where(Observation.indicator_id == indicator_id, Observation.published_at <= as_of)
    if mode == "system_known":
        query = query.where(Observation.ingested_at <= as_of)
    elif mode != "source_known":
        raise ValueError("Invalid vintage mode")
    if demo:
        query = query.where(Observation.quality == "demo")
    else:
        query = query.where(Observation.quality != "demo")
    records = session.scalars(query.order_by(Observation.period_end, Observation.published_at, Observation.ingested_at)).all()
    latest = {}
    for row in records:
        key = (row.period_start, row.period_end)
        latest[key] = row
    return sorted(latest.values(), key=lambda o: o.period_end)
