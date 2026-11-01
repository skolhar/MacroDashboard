"""Read-only, in-memory discovery smoke using actual U.S. Treasury 10Y XML.

The feed proves dated values, not original publication timestamps. It does
not persist data, infer a feedback loop, or imply public redistribution rights.
"""
from datetime import datetime, timedelta, timezone
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from packages.connectors.treasury import TreasuryAdapter
from packages.domain.models import Base, ResearchEvidence
from packages.scoring.discovery import evaluate


def main():
    now = datetime.now(timezone.utc)
    as_of_feed = now.replace(day=1) - timedelta(days=1)
    _, records = TreasuryAdapter().fetch(as_of_feed)
    db = create_engine("sqlite://")
    Base.metadata.create_all(db)
    with Session(db) as session:
        for row in records:
            session.add(ResearchEvidence(indicator_key="us_10y_treasury_par_yield", indicator_or_claim="U.S. Treasury 10-year par yield", frequency="business_daily", value_numeric=row.value, value_text=None, unit="pct", period_start=row.period_start, period_end=row.period_end, source_name="U.S. Treasury", source_reference=row.source_reference, retrieved_at=now, published_at=None, reliability_note="Official XML observation date is known; original publication timestamp and historical vintage are not verified.", usage_basis="Read-only private research using public U.S. Treasury XML; no public redistribution", quality="secondary", revision_id=f"retrieved-{now.isoformat()}", observation_key=f"treasury-smoke-{row.period_end}", entered_by="smoke"))
        session.flush()
        result = evaluate(session, now)
        series = result["series"].get("us_10y_treasury_par_yield")
        print({"source": records[-1].source_reference, "actual_records": len(records), "latest_observation": records[-1].period_end.isoformat(), "latest_value_pct": str(records[-1].value), "publication_time": "unknown", "retrieved_at": now.isoformat(), "discovery_status": series["status"] if series else "DATA_UNAVAILABLE", "anomaly_types": [item["type"] for item in series["anomalies"]] if series else [], "candidate_count": len(result["candidate_hypotheses"]), "storage": "in-memory only"})


if __name__ == "__main__":
    main()
