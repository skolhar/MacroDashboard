"""Private Indian research coverage, including explicit unavailable questions."""
from datetime import datetime
from sqlalchemy import select
from packages.connectors.world_bank import indicator_registry
from packages.domain.models import IngestionRun, ResearchEvidence
from packages.scoring.discovery import evaluate, rules
from packages.scoring.economic_transform import configuration

PENDING = [
    {"id": "rbi_banking_liquidity", "source": "RBI", "reason": "Automatable official release format and historical publication evidence still required"},
    {"id": "rbi_bank_credit_growth", "source": "RBI", "reason": "Official fortnightly series access/definition not integrated"},
    {"id": "fpi_equity_net", "source": "NSDL", "reason": "Daily equity/debt flow access and usage terms not verified"},
    {"id": "dii_equity_net", "source": "NSE", "reason": "Official flow definitions and permitted automated access not verified"},
    {"id": "sip_contribution_inr", "source": "AMFI", "reason": "Historical release publication evidence and automated usage terms not verified"},
    {"id": "india_cpi_monthly", "source": "MoSPI", "reason": "Documented CPI API requires bearer authorization; no token supplied"},
    {"id": "india_iip_monthly", "source": "MoSPI", "reason": "Documented IIP API requires bearer authorization; no token supplied"},
]


def coverage(session, as_of: datetime):
    discovery = evaluate(session, as_of)
    source_registry = indicator_registry()
    registry = {**source_registry["indicators"], **source_registry["gem_indicators"]}
    transform = configuration()["series"]
    cadence = rules()["freshness_days"]
    items = []
    for key, spec in registry.items():
        rows = session.scalars(select(ResearchEvidence).where(ResearchEvidence.indicator_key == key, ResearchEvidence.retrieved_at <= as_of, ResearchEvidence.period_end <= as_of.date()).order_by(ResearchEvidence.period_end, ResearchEvidence.retrieved_at, ResearchEvidence.id)).all()
        by_period = {(row.period_end.year, row.period_end.month if spec["frequency"] == "monthly" else 12): row for row in rows}
        periods = sorted(by_period)
        latest = by_period[periods[-1]] if periods else None
        first_index = periods[0][0] * 12 + periods[0][1] - 1 if periods else None
        last_index = periods[-1][0] * 12 + periods[-1][1] - 1 if periods else None
        if spec["frequency"] == "annual":
            gaps = [str(year) for year in range(periods[0][0], periods[-1][0] + 1) if (year, 12) not in by_period] if periods else []
        else:
            gaps = [f"{index // 12:04d}-{index % 12 + 1:02d}" for index in range(first_index, last_index + 1) if (index // 12, index % 12 + 1) not in by_period] if periods else []
        assessment = discovery["series"].get(key)
        age = (as_of.date() - latest.period_end).days if latest else None
        stale = age is not None and age > cadence[spec["frequency"]]
        status = "DATA_UNAVAILABLE" if latest is None else "STALE" if stale else assessment["status"] if assessment else "TRANSFORM_UNAVAILABLE"
        items.append({"indicator_id": key, "name": spec["name"], "sector": spec["sector"], "source": latest.source_name if latest else "World Bank GEM" if spec["frequency"] == "monthly" else "World Bank WDI", "source_reference": latest.source_reference if latest else None, "frequency": spec["frequency"], "latest_period": latest.period_end.isoformat() if latest else None, "latest_value": float(latest.value_numeric) if latest else None, "unit": latest.unit if latest else spec["unit"], "published_at": latest.published_at.isoformat() if latest and latest.published_at else None, "retrieved_at": latest.retrieved_at.isoformat() if latest else None, "history_start": periods[0] if periods else None, "history_end": periods[-1] if periods else None, "observation_count": len(periods), "missing_periods": gaps, "freshness_age_days": age, "status": status, "transformation": transform[key]["primary"], "transformation_version": configuration()["version"], "transformed_latest": assessment["observations"][-1]["value"] if assessment and assessment["observations"] else None, "anomaly_evaluable": bool(assessment and assessment["status"] in {"PERSISTENT", "ISOLATED", "NO_PATTERN"}), "usage": "private exploratory research; third-party redistribution rights unverified"})
    runs = {}
    for provider in ("world_bank_wdi_research", "world_bank_gem_research"):
        last = session.scalar(select(IngestionRun).where(IngestionRun.provider == provider, IngestionRun.finished_at <= as_of).order_by(IngestionRun.finished_at.desc(), IngestionRun.id.desc()).limit(1))
        runs[provider] = {"last_run": last.started_at.isoformat() if last else None, "status": last.status if last else "never", "error_code": last.error_code if last else None}
    pair_status = []
    for pair in rules()["relationships"]:
        left, right = discovery["series"].get(pair["left"]), discovery["series"].get(pair["right"])
        ready = lambda item: item is not None and item["status"] in {"PERSISTENT", "ISOLATED", "NO_PATTERN"}
        state = "investigable" if ready(left) and ready(right) else "incomplete" if left or right else "unavailable"
        pair_status.append({"id": pair["id"], "question": pair["question"], "status": state, "candidate_present": any(x["relationship_id"] == pair["id"] for x in discovery["relationships"]), "missing_or_unusable": [key for key, item in ((pair["left"], left), (pair["right"], right)) if not ready(item)]})
    return {"as_of": as_of.isoformat(), "mode": "private_research", "source_status": runs, "indicators": items, "pending_sources": PENDING, "questions": pair_status, "summary": {"configured": len(items), "available": sum(x["status"] not in {"DATA_UNAVAILABLE", "STALE", "TRANSFORM_UNAVAILABLE"} for x in items), "stale": sum(x["status"] == "STALE" for x in items), "investigable_questions": sum(x["status"] == "investigable" for x in pair_status)}, "warning": "GEM monthly aggregates and WDI annual data are secondary research; they are not RBI weekly banking liquidity, tradeable spot FX, or licensed FPI/AMFI flows. Absent data is not evidence of stability."}
