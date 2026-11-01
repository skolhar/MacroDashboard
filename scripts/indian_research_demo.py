"""Reproducible, read-only-source Indian macro research in disposable memory.

It fetches public WDI/GEM JSON, creates an in-memory private research store,
and never writes to a configured SmartHedge database or public release table.
"""
from datetime import date, datetime, timezone
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from packages.connectors.world_bank import WorldBankGEMAdapter, WorldBankIndiaAdapter
from packages.domain.models import Base
from packages.jobs.wdi_research import ingest
from packages.scoring.discovery import evaluate
from packages.scoring.economic_coverage import coverage


def summarize(result):
    return {"episode_end": result["episode_end"], "analysis_basis": result["analysis_basis"], "persistent": [{"indicator": item["series"], "period": item["latest_period"], "transformation": item["transformation"], "latest_transformed": item["observations"][-1]["value"], "source_reference": item["observations"][-1]["source_reference"]} for item in result["persistent_anomalies"]], "base_effect_review": [item["series"] for item in result["series"].values() if item["status"] == "BASE_EFFECT_REVIEW"], "relationships": [{"id": item["relationship_id"], "status": item["status"], "competing_explanations": item["competing_explanations"], "confirmation_needed": item["hypothesis"]["confirmation_needed"]} for item in result["relationships"]], "candidate_count": len(result["candidate_hypotheses"])}


def main():
    database = create_engine("sqlite://")
    Base.metadata.create_all(database)
    with Session(database) as session:
        imports = [ingest(session, WorldBankIndiaAdapter(), 2000, 2026), ingest(session, WorldBankGEMAdapter(), 2018, 2026)]
        now = datetime.now(timezone.utc)
        assessment = [summarize(evaluate(session, now, episode_end=day)) for day in (date(2021, 5, 31), date(2025, 6, 30), date(2026, 7, 31))]
        present = coverage(session, now)
        print(json.dumps({"retrieved_at": now.isoformat(), "source_imports": imports, "coverage": present["summary"], "source_status": present["source_status"], "episodes": assessment, "publication_time": "unknown for source observations; retrospective current-vintage research only", "storage": "in-memory only; no public or production import"}, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
