"""Read-only official-source smoke: evaluate an attributed neutral Treasury fact.

Uses an in-memory database. No source value is copied to production or demo.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from packages.connectors.treasury import TreasuryAdapter
from packages.domain.models import Base, ResearchEvidence
from packages.scoring.cycle_intelligence import evaluate


def main():
    now = datetime.now(timezone.utc)
    try:
        _, records = TreasuryAdapter().fetch(now)
    except ValueError:
        _, records = TreasuryAdapter().fetch(now.replace(day=1) - timedelta(days=1))
    latest = records[-1]
    db = create_engine("sqlite://")
    Base.metadata.create_all(db)
    with Session(db) as session:
        session.add(ResearchEvidence(cycle_id="global", mechanism_id="funding_constraint", indicator_or_claim="U.S. Treasury 10-year par yield", value_text=None, value_numeric=latest.value, unit=latest.unit, period_start=latest.period_start, period_end=latest.period_end, source_name="U.S. Treasury", source_reference=latest.source_reference, retrieved_at=now, published_at=None, reliability_note="Official XML contains observation date; exact original publication time is unverified. Yield alone cannot establish a credit or AI feedback loop.", usage_basis="Read-only private research using public U.S. Treasury XML; no public redistribution of a derived dataset", quality="secondary", stance="neutral", observation_key=f"treasury-neutral-{latest.period_end}", entered_by="research-smoke"))
        session.flush()
        result = evaluate(session, now)
        global_cycle = next(c for c in result["cycles"] if c["id"] == "global")
        print({"source": latest.source_reference, "observation_date": latest.period_end.isoformat(), "yield_pct": str(latest.value), "retrieved_at": now.isoformat(), "cycle": global_cycle["id"], "state": global_cycle["state"], "evidence_count": result["evidence_count"], "publication_time": "unknown; no strict historical availability claim"})


if __name__ == "__main__":
    main()
