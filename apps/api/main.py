from datetime import datetime, timezone
import os
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Query, Request
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session
from packages.domain.config import registry, rules
from packages.domain.models import Observation
from packages.domain.store import engine, observations_at
from packages.scoring.engine import compute
from packages.scoring.alerts import fx_alert

app = FastAPI(title="India Macro Reflexivity Dashboard", version="0.1.0")
DB = engine()
DEMO = os.getenv("DEMO_MODE", "true").lower() == "true"
DEFAULT_AS_OF = datetime.fromisoformat("2026-10-31T00:00:00+05:30")


@app.middleware("http")
async def request_id(request: Request, call_next):
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", str(uuid4()))
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.status_code, "message": exc.detail}})


def parsed_as_of(value):
    if value is None:
        return DEFAULT_AS_OF if DEMO else datetime.now(timezone.utc)
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            raise ValueError()
        return parsed
    except ValueError:
        raise HTTPException(422, "as_of must be an ISO 8601 timestamp with timezone")


def require_ruleset(version):
    try:
        return rules(version)
    except ValueError:
        raise HTTPException(404, "Unknown ruleset")


def dashboard(as_of, ruleset="v1", vintage_mode="system_known"):
    require_ruleset(ruleset)
    with Session(DB) as session:
        result = compute(session, parsed_as_of(as_of), DEMO, vintage_mode)
        result["alerts"] = fx_alert(session, parsed_as_of(as_of), DEMO, vintage_mode)
        return result


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "mode": "demo" if DEMO else "live", "ruleset_version": "v1"}


@app.get("/api/v1/sources/health")
def sources_health(as_of: str | None = None):
    data = dashboard(as_of)
    return {"mode": data["mode"], **data["source_health"], "sources": [{"indicator_id": m["id"], "status": m["status"], "provider": m["provider"], "last_successful_ingestion": m["ingested_at"], "publication_lag_days": registry()[m["id"]]["publication_lag_days"]} for m in data["metrics"]]}


@app.get("/api/v1/dashboard")
def get_dashboard(as_of: str | None = None, ruleset: str = "v1"):
    return dashboard(as_of, ruleset)


@app.get("/api/v1/indicators")
def indicators(cycle: str | None = None, status: str | None = None, as_of: str | None = None, limit: int = Query(50, ge=1, le=100), offset: int = Query(0, ge=0)):
    rows = dashboard(as_of)["metrics"]
    if cycle:
        rows = [m for m in rows if m["cycle"] == cycle]
    if status:
        rows = [m for m in rows if m["status"] == status]
    return {"items": rows[offset:offset + limit], "total": len(rows), "limit": limit, "offset": offset}


@app.get("/api/v1/indicators/{indicator_id}/series")
def indicator_series(indicator_id: str, as_of: str | None = None, from_date: str | None = Query(None, alias="from"), to_date: str | None = Query(None, alias="to"), vintage_mode: str = "system_known"):
    if indicator_id not in registry():
        raise HTTPException(404, "Unknown indicator")
    if vintage_mode not in ("system_known", "source_known"):
        raise HTTPException(422, "Unknown vintage mode")
    try:
        start = datetime.fromisoformat(from_date).date() if from_date else None
        end = datetime.fromisoformat(to_date).date() if to_date else None
    except ValueError:
        raise HTTPException(422, "Invalid date range")
    with Session(DB) as session:
        rows = observations_at(session, indicator_id, parsed_as_of(as_of), vintage_mode, DEMO)
        rows = [r for r in rows if (not start or r.period_end >= start) and (not end or r.period_end <= end)]
        return {"indicator_id": indicator_id, "mode": "demo" if DEMO else "live", "vintage_mode": vintage_mode, "items": [{"id": r.id, "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(), "value": float(r.value), "unit": r.unit, "published_at": r.published_at.isoformat(), "ingested_at": r.ingested_at.isoformat(), "provider": r.provider, "source_url": r.source_url, "vintage_id": r.vintage_id, "quality": r.quality, "is_revision": r.is_revision} for r in rows]}


@app.get("/api/v1/cycles/{cycle_id}")
def cycle(cycle_id: str, as_of: str | None = None, ruleset: str = "v1"):
    data = dashboard(as_of, ruleset)
    for item in data["cycles"]:
        if item["id"] == cycle_id:
            return item
    raise HTTPException(404, "Unknown cycle")


@app.get("/api/v1/alerts")
def alerts(as_of: str | None = None, status: str | None = None, severity: str | None = None):
    items = dashboard(as_of)["alerts"]
    if status == "active":
        items = [a for a in items if a["status"] in ("WATCH", "WARNING", "CRITICAL")]
    elif status:
        items = [a for a in items if a["status"].lower() == status.lower()]
    if severity:
        items = [a for a in items if (a["severity"] or "").lower() == severity.lower()]
    return {"items": items, "total": len(items)}


@app.get("/api/v1/alerts/{alert_id}")
def alert(alert_id: str, as_of: str | None = None):
    for item in dashboard(as_of)["alerts"]:
        if item["id"] == alert_id:
            return item
    raise HTTPException(404, "Unknown alert")


@app.get("/api/v1/config/rulesets")
def rulesets():
    return {"items": [{"version": "v1", "calibration": "provisional", "cycle_weights": rules()["cycle_weights"]}]}
