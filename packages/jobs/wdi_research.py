"""Idempotent private WDI ingestion; never writes governed macro releases."""
from datetime import datetime, timezone
from hashlib import sha256
import argparse
from sqlalchemy import select
from sqlalchemy.orm import Session
from packages.connectors.world_bank import WorldBankIndiaAdapter, WorldBankGEMAdapter, indicator_registry
from packages.domain.models import IngestionRun, ResearchEvidence
from packages.domain.settings import settings
from packages.domain.store import engine


def ingest(session, adapter=None, start_year=2000, end_year=None):
    adapter = adapter or WorldBankIndiaAdapter()
    started = datetime.now(timezone.utc)
    try:
        records = adapter.fetch(start_year, end_year)
        registry = indicator_registry()["gem_indicators" if adapter.provider == "world_bank_gem_research" else "indicators"]
        inserted = duplicates = 0
        counts = {key: 0 for key in registry}
        for record in records:
            digest = sha256(f"{record.indicator_key}:{record.period_end}:{record.value.normalize()}:{record.unit}".encode()).hexdigest()
            key = f"wb:{record.indicator_key}:{record.period_end}:{digest[:16]}"
            counts[record.indicator_key] += 1
            if session.scalar(select(ResearchEvidence.id).where(ResearchEvidence.observation_key == key)):
                duplicates += 1
                continue
            spec = registry[record.indicator_key]
            session.add(ResearchEvidence(indicator_key=record.indicator_key, indicator_or_claim=spec["name"], frequency=record.frequency, value_numeric=record.value, value_text=str(record.value), unit=record.unit, period_start=record.period_end.replace(month=1, day=1) if record.frequency == "annual" else record.period_end.replace(day=1), period_end=record.period_end, source_name="World Bank GEM" if record.frequency == "monthly" else "World Bank WDI", source_reference=record.source_url, retrieved_at=started, published_at=None, reliability_note=f"{record.frequency.capitalize()} secondary World Bank release; dataset updated {record.dataset_updated}. Original observation publication time and historical vintages are unverified; source definition must be reviewed.", usage_basis="Private exploratory research under World Bank Data Terms; indicator-level third-party redistribution rights not assumed", quality="secondary", revision_id=f"wb-{record.dataset_updated}-{digest[:12]}", observation_key=key, entered_by="world-bank-research-job"))
            inserted += 1
        session.add(IngestionRun(provider=adapter.provider, started_at=started, finished_at=datetime.now(timezone.utc), status="success" if records else "unavailable", item_count=inserted, error_code=None if records else "NoObservations"))
        session.commit()
        return {"provider": adapter.provider, "status": "success" if records else "unavailable", "records": len(records), "inserted": inserted, "duplicates": duplicates, "counts": counts, "publication_time": "unknown; retrieval bounded", "rights": "private research only; source-specific redistribution unverified"}
    except Exception as exc:
        session.rollback()
        session.add(IngestionRun(provider=adapter.provider, started_at=started, finished_at=datetime.now(timezone.utc), status="failed", item_count=0, error_code=type(exc).__name__))
        session.commit()
        raise


def main():
    options = argparse.ArgumentParser(description="Private research: retrieve India annual WDI indicators")
    options.add_argument("--start-year", type=int, default=2000)
    options.add_argument("--end-year", type=int)
    options.add_argument("--dataset", choices=["wdi", "gem", "both"], default="both")
    args = options.parse_args()
    current = settings()
    if current.demo_mode or current.environment not in {"development", "staging"}:
        raise SystemExit("WDI research ingestion is available only in isolated non-demo development/staging")
    with Session(engine()) as session:
        if args.dataset in {"wdi", "both"}:
            print(ingest(session, WorldBankIndiaAdapter(), start_year=args.start_year, end_year=args.end_year))
        if args.dataset in {"gem", "both"}:
            print(ingest(session, WorldBankGEMAdapter(), start_year=max(args.start_year, 2018), end_year=args.end_year))


if __name__ == "__main__":
    main()
