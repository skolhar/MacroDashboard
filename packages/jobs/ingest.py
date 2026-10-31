"""Validated, idempotent, immutable observation ingestion."""
import hashlib
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from sqlalchemy import select
from sqlalchemy.orm import Session
from packages.connectors.base import SourceObservation
from packages.domain.config import registry
from packages.domain.models import IngestionRun, Observation, RawSnapshot, RBIReserveComponent

POSITIVE_UNITS = {"INR_per_USD", "USD_per_bbl", "index", "index_points", "multiple", "count"}
OUTLIER_UNITS = POSITIVE_UNITS | {"pct"}
ACCEPTED_QUALITY = {"verified", "provisional", "revised", "estimated", "source_conflict", "demo"}


def validate_record(record: SourceObservation, demo_mode: bool):
    definition = registry(phase2=True).get(record.indicator_id)
    if definition is None:
        raise ValueError("Unknown indicator")
    if record.unit != definition["unit"]:
        raise ValueError(f"Unsupported unit for {record.indicator_id}")
    if record.quality not in ACCEPTED_QUALITY:
        raise ValueError("Unsupported quality")
    if record.is_demo != demo_mode or (record.quality == "demo") != demo_mode:
        raise ValueError("Demo/live quality mismatch")
    if record.period_start > record.period_end:
        raise ValueError("Invalid observation period")
    if record.published_at.tzinfo is None:
        raise ValueError("Publication timestamp requires timezone")
    if record.published_at > datetime.now(timezone.utc):
        raise ValueError("Future publication timestamp")
    if not record.value.is_finite() or (record.unit in POSITIVE_UNITS and record.value <= 0):
        raise ValueError("Invalid numeric value")
    if not record.source_reference or not record.source_reference.startswith("https://"):
        raise ValueError("Source reference must be an HTTPS URL")
    if not record.vintage_id or len(record.vintage_id) > 100 or len(record.provider) > 100:
        raise ValueError("Invalid provider or vintage")


def ingest_records(session: Session, records: list[SourceObservation], raw: bytes, provider: str, demo_mode=False, original_raw: bytes | None = None, release_review_id: int | None = None, reserve_release=None) -> dict:
    if len(raw) > 5_000_000 or not records:
        raise ValueError("Empty or oversized source snapshot")
    for record in records:
        validate_record(record, demo_mode)
        if record.provider != provider:
            raise ValueError("Provider mismatch")
    if reserve_release is not None and (len(records) != 1 or provider != "rbi" or records[0].indicator_id != "fx_gross_reserves_usd" or records[0].period_end != reserve_release.reference_week or records[0].value != reserve_release.total_usd_bn or release_review_id is None):
        raise ValueError("Parsed WSS release does not match reviewed observation")
    digest = hashlib.sha256(original_raw if original_raw is not None else raw).hexdigest()
    now = datetime.now(timezone.utc)
    run = IngestionRun(provider=provider, started_at=now, status="running", item_count=0)
    session.add(run)
    session.flush()
    if session.scalar(select(RawSnapshot.id).where(RawSnapshot.content_hash == digest)) is None:
        session.add(RawSnapshot(provider=provider, content_hash=digest, received_at=now, source_url=records[0].source_reference))
    inserted = 0
    revisions = 0
    for record in records:
        existing = session.scalar(select(Observation).where(Observation.indicator_id == record.indicator_id, Observation.period_start == record.period_start, Observation.period_end == record.period_end, Observation.provider == provider, Observation.vintage_id == record.vintage_id))
        if existing:
            if existing.value != record.value or existing.unit != record.unit:
                raise ValueError("Conflicting duplicate observation")
            if release_review_id is not None and (existing.release_review_id != release_review_id or existing.content_hash != digest or existing.published_at != record.published_at):
                raise ValueError("Conflicting reviewed release for existing vintage")
            if reserve_release is not None and not _matching_components(session.get(RBIReserveComponent, existing.id), reserve_release):
                raise ValueError("Conflicting WSS components for existing vintage")
            continue
        prior = session.scalar(select(Observation).where(Observation.indicator_id == record.indicator_id, Observation.period_start == record.period_start, Observation.period_end == record.period_end, Observation.provider == provider).order_by(Observation.published_at.desc()))
        quality = record.quality
        if record.unit in OUTLIER_UNITS:
            previous_period = session.scalar(select(Observation).where(Observation.indicator_id == record.indicator_id, Observation.period_end < record.period_end, Observation.provider == provider).order_by(Observation.period_end.desc()))
            if previous_period and previous_period.value > 0 and record.value > 0 and abs(record.value / previous_period.value - 1) > Decimal("0.5"):
                quality = "source_conflict"
        rate_kind = "published_reference_rate" if record.indicator_id == "usd_inr_spot" and provider in {"rbi", "fbil"} else "provider_defined_fx_rate" if record.indicator_id == "usd_inr_spot" else None
        observation = Observation(indicator_id=record.indicator_id, period_start=record.period_start, period_end=record.period_end, value=record.value, unit=record.unit, published_at=record.published_at, ingested_at=now, provider=provider, source_url=record.source_reference, vintage_id=record.vintage_id, quality=quality, is_revision=prior is not None, is_demo=record.is_demo, source_identifier=provider, source_reference=record.source_reference, content_hash=digest, release_review_id=release_review_id, rate_kind=rate_kind)
        session.add(observation)
        if reserve_release is not None:
            session.flush()
            session.add(RBIReserveComponent(observation_id=observation.id, **_component_values(reserve_release)))
        inserted += 1
        revisions += int(prior is not None)
    run.status = "success"
    run.finished_at = datetime.now(timezone.utc)
    run.item_count = inserted
    session.commit()
    return {"inserted": inserted, "duplicate": len(records) - inserted, "revisions": revisions, "snapshot_sha256": digest, "run_id": run.id}


def _component_values(release):
    return {name: getattr(release, name) for name in ("total_usd_mn", "foreign_currency_assets_usd_mn", "gold_usd_mn", "sdr_usd_mn", "imf_reserve_tranche_usd_mn")}


def _matching_components(stored, release):
    return stored is not None and all(getattr(stored, key) == value for key, value in _component_values(release).items())
