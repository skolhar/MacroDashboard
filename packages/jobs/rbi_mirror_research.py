"""Isolated private ingestion from the read-only RBI Innovation Hub DBIE mirror."""
from datetime import date, datetime, timezone
from hashlib import sha256
import argparse
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from packages.connectors.rbi_research_mirror import RBIResearchMirrorAdapter, registry
from packages.domain.models import IngestionRun, ResearchEvidence
from packages.domain.settings import settings
from packages.domain.store import engine


def ingest(session, table_key, adapter=None, min_date=date(2018, 1, 1)):
    adapter = adapter or RBIResearchMirrorAdapter()
    started = datetime.now(timezone.utc)
    provider = adapter.provider + ":" + table_key
    try:
        records = adapter.fetch(table_key, min_date)
        existing = set(session.scalars(select(ResearchEvidence.observation_key).where(ResearchEvidence.indicator_key.in_({r.indicator_key for r in records}))))
        inserted = duplicates = 0
        names = registry()["tables"][table_key]["indicators"]
        for record in records:
            digest = sha256(f"{record.indicator_key}:{record.period_end}:{record.value.normalize()}:{record.unit}".encode()).hexdigest()
            key = f"rbihub:{record.indicator_key}:{record.period_end}:{digest[:16]}"
            if key in existing:
                duplicates += 1
                continue
            existing.add(key)
            session.add(ResearchEvidence(
                indicator_key=record.indicator_key, indicator_or_claim=names[record.indicator_key]["name"], frequency=record.frequency,
                value_numeric=record.value, value_text=str(record.value), unit=record.unit, period_start=record.period_end,
                period_end=record.period_end, source_name="RBI Innovation Hub DBIE mirror (secondary)", source_reference=record.source_reference,
                retrieved_at=started, published_at=None, reliability_note=f"{record.definition_note} Mirror loaded {record.mirror_loaded_at}; RBI path: {record.publisher_path}",
                usage_basis="Private exploratory research from a public read-only secondary mirror; source-data redistribution rights unverified",
                quality="secondary", revision_id=f"rbihub-{digest[:16]}", observation_key=key, entered_by="rbi-mirror-research-job",
            ))
            try:
                with session.begin_nested():
                    session.flush()
                inserted += 1
            except IntegrityError:
                # A concurrent worker inserted the same observation first; the unique
                # observation_key keeps a concurrent retry idempotent.
                duplicates += 1
        session.add(IngestionRun(provider=provider, started_at=started, finished_at=datetime.now(timezone.utc), status="success" if records else "unavailable", item_count=inserted, error_code=None if records else "NoObservations"))
        session.commit()
        return {"provider": provider, "records": len(records), "inserted": inserted, "duplicates": duplicates, "status": "success" if records else "unavailable"}
    except Exception as exc:
        session.rollback()
        session.add(IngestionRun(provider=provider, started_at=started, finished_at=datetime.now(timezone.utc), status="failed", item_count=0, error_code=type(exc).__name__))
        session.commit()
        raise


def main():
    parser = argparse.ArgumentParser(description="Ingest private RBI mirror research observations.")
    parser.add_argument("--table", required=True, choices=["bank", "liquidity", "reserves"])
    parser.add_argument("--min-date", default="2018-01-01")
    args = parser.parse_args()
    if settings().environment in {"production", "demo"}:
        raise SystemExit("Refusing to write mirror research into a production or demo environment")
    min_date = date.fromisoformat(args.min_date)
    with Session(engine()) as session:
        result = ingest(session, args.table, min_date=min_date)
        print(result)


if __name__ == "__main__":
    main()
