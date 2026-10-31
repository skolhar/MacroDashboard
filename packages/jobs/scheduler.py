"""Staging-only, idempotent official-source polling worker."""
import os
import time
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from packages.connectors.treasury import TreasuryAdapter
from packages.domain.models import AdminAudit, IngestionRun
from packages.domain.settings import settings
from packages.domain.security import DatabaseRateLimiter
from packages.domain.store import engine
from packages.jobs.ingest import ingest_records
from packages.jobs.sync_registry import sync_registry
from packages.scoring.inflections import evaluate_v2, persist_transitions


def run_once(session: Session, adapter=None, as_of=None):
    adapter = adapter or TreasuryAdapter()
    as_of = as_of or datetime.now(timezone.utc)
    try:
        raw, records = adapter.fetch(as_of)
        if not records:
            raise ValueError("No eligible Treasury observations")
        result = ingest_records(session, records, raw, adapter.provider)
        if result["inserted"]:
            persist_transitions(session, evaluate_v2(session, as_of), as_of)
        session.add(AdminAudit(operator_id="system:treasury-scheduler", action="treasury_ingestion", result="success", at=as_of, details=f"run_id={result['run_id']};inserted={result['inserted']}"))
        if result["revisions"]:
            session.add(AdminAudit(operator_id="system:treasury-scheduler", action="observation_revision", result="recorded", at=as_of, details=f"run_id={result['run_id']};count={result['revisions']}"))
        session.commit()
        return result
    except Exception as exc:
        session.rollback()
        session.add(IngestionRun(provider=adapter.provider, started_at=as_of, finished_at=datetime.now(timezone.utc), status="failed", error_code=type(exc).__name__))
        session.add(AdminAudit(operator_id="system:treasury-scheduler", action="treasury_ingestion", result="failed", at=as_of, details=type(exc).__name__))
        session.commit()
        raise


def main():
    if settings().environment != "staging" or os.getenv("INGESTION_SCHEDULE_ENABLED") != "true":
        raise RuntimeError("Scheduler requires explicit staging enablement")
    db = engine()
    with Session(db) as session:
        sync_registry(session)
    while True:
        with Session(db) as session:
            try:
                run_once(session)
            except Exception as exc:
                print(f"Treasury ingestion failed: {type(exc).__name__}", flush=True)
        DatabaseRateLimiter(db).prune()
        time.sleep(21600)


if __name__ == "__main__":
    main()
