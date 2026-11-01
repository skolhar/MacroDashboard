"""Idempotent secondary-price ingestion and point-in-time research reads."""
import hashlib
import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from .base import Instrument, MarketBatch, MarketProvider
from packages.domain.models import MarketBar, MarketFetchRun


def _digest(batch: MarketBatch, candle) -> str:
    fields = [batch.instrument.id, batch.provider, batch.symbol, candle.session_date.isoformat(), *(str(getattr(candle, key)) for key in ("open", "high", "low", "close", "adjusted_close", "volume"))]
    return hashlib.sha256(json.dumps(fields, separators=(",", ":")).encode()).hexdigest()


def ingest_batch(session: Session, batch: MarketBatch) -> dict:
    if not batch.provider:
        raise ValueError("Provider required")
    if batch.retrieved_at.tzinfo is None or not batch.candles or batch.instrument.symbol(batch.provider) != batch.symbol:
        raise ValueError("Invalid provider batch")
    if batch.quality not in {"secondary_unverified", "secondary_partial"} or batch.exchange_timezone != batch.instrument.timezone or not batch.source_url.startswith("https://"):
        raise ValueError("Invalid market provenance or quality")
    if len({item.session_date for item in batch.candles}) != len(batch.candles):
        raise ValueError("Conflicting duplicate market sessions in one provider batch")
    inserted = 0
    duplicates = 0
    revisions = 0
    for candle in batch.candles:
        if candle.session_date >= batch.retrieved_at.astimezone(ZoneInfo(batch.exchange_timezone)).date():
            raise ValueError("Incomplete or future market session")
        prices = (candle.open, candle.high, candle.low, candle.close)
        if any(not value.is_finite() for value in prices) or (candle.adjusted_close is not None and not candle.adjusted_close.is_finite()) or candle.low > min(candle.open, candle.close) or candle.high < max(candle.open, candle.close) or (batch.instrument.kind != "futures_proxy" and min(prices) <= 0) or (candle.volume is not None and candle.volume < 0):
            raise ValueError("Invalid normalized OHLCV")
        digest = _digest(batch, candle)
        existing = session.scalar(select(MarketBar.id).where(MarketBar.instrument_id == batch.instrument.id, MarketBar.provider == batch.provider, MarketBar.session_date == candle.session_date, MarketBar.content_hash == digest))
        if existing:
            duplicates += 1
            continue
        prior = session.scalar(select(MarketBar.id).where(MarketBar.instrument_id == batch.instrument.id, MarketBar.provider == batch.provider, MarketBar.session_date == candle.session_date).limit(1))
        try:
            with session.begin_nested():
                session.add(MarketBar(instrument_id=batch.instrument.id, provider=batch.provider, provider_symbol=batch.symbol, market=batch.instrument.market, currency=batch.instrument.currency, exchange_timezone=batch.exchange_timezone, provider_exchange=batch.provider_exchange, session_date=candle.session_date, open=candle.open, high=candle.high, low=candle.low, close=candle.close, adjusted_close=candle.adjusted_close, volume=candle.volume, price_basis="raw_ohlc_adjusted_close", source_url=batch.source_url, retrieved_at=batch.retrieved_at, quality=batch.quality, content_hash=digest, contract_identity=batch.contract_identity, roll_policy=batch.roll_policy))
                session.flush()
            inserted += 1
            revisions += int(prior is not None)
        except IntegrityError:
            duplicates += 1
    return {"inserted": inserted, "duplicates": duplicates, "revisions": revisions, "rejected_rows": batch.rejected_rows}


def refresh(session: Session, provider: MarketProvider, instrument: Instrument, start: date | None = None, end: date | None = None, now: datetime | None = None) -> dict:
    now = now or datetime.now(timezone.utc)
    end = end or now.date() + timedelta(days=1)
    if start is None:
        latest = session.scalar(select(MarketBar.session_date).where(MarketBar.instrument_id == instrument.id, MarketBar.provider == provider.name).order_by(MarketBar.session_date.desc()).limit(1))
        start = latest - timedelta(days=7) if latest else end - timedelta(days=365)
    if start >= end or end > now.date() + timedelta(days=1) or (end - start).days > 365 * 15:
        raise ValueError("Invalid market backfill range")
    started = datetime.now(timezone.utc)
    try:
        batch = provider.fetch_daily(instrument, start, end)
        result = ingest_batch(session, batch)
        session.add(MarketFetchRun(instrument_id=instrument.id, provider=provider.name, requested_start=start, requested_end=end, started_at=started, finished_at=datetime.now(timezone.utc), status="partial" if result["rejected_rows"] else "success", item_count=result["inserted"], rejected_count=result["rejected_rows"], error_code="InvalidRows" if result["rejected_rows"] else None))
        session.commit()
        return {**result, "status": "partial" if result["rejected_rows"] else "success", "start": start.isoformat(), "end_exclusive": end.isoformat()}
    except Exception as exc:
        session.rollback()
        session.add(MarketFetchRun(instrument_id=instrument.id, provider=provider.name, requested_start=start, requested_end=end, started_at=started, finished_at=datetime.now(timezone.utc), status="failed", item_count=0, rejected_count=0, error_code=type(exc).__name__))
        session.commit()
        raise


def history_at(session: Session, instrument_id: str, provider: str, as_of: datetime, start: date | None = None, end: date | None = None) -> list[MarketBar]:
    if as_of.tzinfo is None:
        raise ValueError("As-of timestamp requires timezone")
    query = select(MarketBar).where(MarketBar.instrument_id == instrument_id, MarketBar.provider == provider, MarketBar.retrieved_at <= as_of)
    if start:
        query = query.where(MarketBar.session_date >= start)
    if end:
        query = query.where(MarketBar.session_date <= end)
    rows = session.scalars(query.order_by(MarketBar.session_date, MarketBar.retrieved_at, MarketBar.id)).all()
    latest = {row.session_date: row for row in rows}
    return list(latest.values())


def status_at(session: Session, instrument: Instrument, provider: str, as_of: datetime) -> dict:
    rows = history_at(session, instrument.id, provider, as_of)
    last = rows[-1] if rows else None
    run = session.scalar(select(MarketFetchRun).where(MarketFetchRun.instrument_id == instrument.id, MarketFetchRun.provider == provider, MarketFetchRun.finished_at <= as_of).order_by(MarketFetchRun.finished_at.desc(), MarketFetchRun.id.desc()).limit(1))
    age = (as_of.date() - last.session_date).days if last else None
    possible_gaps = []
    recent = rows[-61:]
    for previous, current in zip(recent, recent[1:]):
        cursor = previous.session_date + timedelta(days=1)
        while cursor < current.session_date:
            if cursor.weekday() < 5:
                possible_gaps.append(cursor.isoformat())
            cursor += timedelta(days=1)
    status = "DATA_UNAVAILABLE" if last is None else "STALE" if age is not None and age > 4 else "PARTIAL" if run and run.status == "partial" else "AVAILABLE"
    if run and run.status == "failed":
        status = "SOURCE_FAILED" if last is None else "SOURCE_FAILED_USING_PRIOR_BAR"
    return {"status": status, "last_session_date": last.session_date.isoformat() if last else None, "last_retrieved_at": last.retrieved_at.isoformat() if last else None, "age_calendar_days": age, "last_fetch_status": run.status if run else "never", "last_fetch_at": run.finished_at.isoformat() if run else None, "last_error_code": run.error_code if run else None, "last_rejected_rows": run.rejected_count if run else None, "possible_weekday_gaps_last_60": possible_gaps, "gap_caveat": "Weekday candidates only; exchange holidays and futures sessions need separate confirmation", "quality": last.quality if last else None, "bar_count": len(rows)}
