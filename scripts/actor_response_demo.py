"""Actual-source, in-memory private actor-response research; never writes production."""
from datetime import date, datetime, timezone
import json
from sqlalchemy import create_engine
from sqlalchemy.orm import Session
from packages.domain.models import Base
from packages.jobs.rbi_mirror_research import ingest
from packages.scoring.discovery import evaluate
from packages.scoring.economic_coverage import coverage


def summarize(result):
    actor = result["actor_responses"][0]
    return {"episode_end": result["episode_end"], "analysis_basis": result["analysis_basis"], "status": actor["status"], "disturbance_periods": actor["disturbance_periods"], "disturbance_growth": actor["disturbance_growth"], "response_periods": actor["response_periods"], "observed_response_value_cr_days": actor.get("observed_response_value_cr_days"), "followup_periods": actor["followup_periods"], "followup_growth": actor["followup_growth"], "evidence_count": len(actor["observations"]), "evidence_strength": actor["evidence_strength"], "explanation": actor["explanation"], "missing_confirmation": actor["missing_confirmation"], "source_observations": [{"series": item["series"], "period_end": item["period_end"], "value": item["source_value_text"], "source_reference": item["source_reference"], "retrieved_at": item["retrieved_at"], "published_at": item["published_at"], "revision": item["revision"]} for item in actor["observations"]]}


def main():
    database = create_engine("sqlite://")
    Base.metadata.create_all(database)
    with Session(database) as session:
        imported = [ingest(session, key, min_date=date(2018, 1, 1)) for key in ("bank", "liquidity", "reserves")]
        now = datetime.now(timezone.utc)
        episodes = [summarize(evaluate(session, now, episode_end=day)) for day in (date(2022, 12, 31), date(2025, 6, 30), date(2026, 10, 31))]
        current = evaluate(session, now)["actor_responses"][0]
        print(json.dumps({"retrieved_at": now.isoformat(), "source": "public read-only RBI Innovation Hub DBIE secondary mirror", "storage": "in-memory private research only", "imports": imported, "coverage": coverage(session, now)["summary"], "episodes": episodes, "current_status": current["status"], "current_explanation": current["explanation"], "publication_dates": "unknown at original RBI release level; this is retrospective current-vintage research and not historical point-in-time evidence"}, indent=2))


if __name__ == "__main__":
    main()
