from datetime import datetime, timezone
import json
import os
import base64
import binascii
import hashlib
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Query, Request, Depends, Header
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from packages.domain.config import registry, rules
from packages.domain.models import Observation, AlertTransition, IngestionRun, AdminAudit
from packages.domain.store import engine, observations_at
from packages.domain.settings import settings
from packages.domain.security import RateLimiter, DatabaseRateLimiter, RateLimitStoreUnavailable, require_scope, client_identity
from packages.connectors.manual import parse_manual_csv
from packages.connectors.india_release import ReleaseManifest, parse_release_package
from packages.connectors.treasury import TreasuryAdapter
from packages.jobs.ingest import ingest_records
from packages.scoring.engine import compute
from packages.scoring.alerts import fx_alert
from packages.scoring.engine_v2 import compute_v2
from packages.scoring.inflections import evaluate_v2, persist_transitions
from packages.scoring.external_liquidity import external_liquidity_view

app = FastAPI(title="India Macro Reflexivity Dashboard", version="0.2.0")
DB = engine()
DEMO = settings().demo_mode
DEFAULT_RULESET = "v1" if DEMO else "v2"
DEFAULT_AS_OF = datetime.fromisoformat("2026-10-31T00:00:00+05:30")
LIMITER = DatabaseRateLimiter(DB) if settings().environment in {"staging", "production"} else RateLimiter()


@app.middleware("http")
async def request_id(request: Request, call_next):
    peer = request.client.host if request.client else "unknown"
    client = client_identity(peer, request.headers.get("x-smarthedge-client-ip"), settings().trusted_proxy_cidrs)
    key = f"{client}:{'write' if request.method != 'GET' else 'read'}"
    try:
        allowed = LIMITER.allow(key, 10 if request.method != "GET" else 240)
    except RateLimitStoreUnavailable:
        return JSONResponse(status_code=503, content={"error": {"code": 503, "message": "Request admission unavailable"}})
    if not allowed:
        return JSONResponse(status_code=429, content={"error": {"code": 429, "message": "Rate limit exceeded"}})
    try:
        body_length = int(request.headers.get("content-length", "0") or 0)
    except ValueError:
        return JSONResponse(status_code=400, content={"error": {"code": 400, "message": "Invalid Content-Length"}})
    if request.method != "GET" and body_length > 1_000_000:
        return JSONResponse(status_code=413, content={"error": {"code": 413, "message": "Request too large"}})
    response = await call_next(request)
    response.headers["X-Request-ID"] = request.headers.get("X-Request-ID", str(uuid4()))
    return response


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse(status_code=exc.status_code, content={"error": {"code": exc.status_code, "message": exc.detail}})


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    return JSONResponse(status_code=422, content={"error": {"code": 422, "message": "Invalid request", "details": exc.errors()}})


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


def dashboard(as_of, ruleset=None, vintage_mode="system_known"):
    version = ruleset or DEFAULT_RULESET
    require_ruleset(version)
    timestamp = parsed_as_of(as_of)
    with Session(DB) as session:
        if version == "v1":
            result = compute(session, timestamp, DEMO, vintage_mode)
            result["alerts"] = fx_alert(session, timestamp, DEMO, vintage_mode)
        else:
            result = compute_v2(session, timestamp, DEMO, vintage_mode)
            result["alerts"] = evaluate_v2(session, timestamp, DEMO, vintage_mode)
            for alert in result["alerts"]:
                alert.pop("_evaluations", None)
        result["environment"] = settings().environment
        return result


@app.get("/api/v1/health")
def health():
    return {"status": "ok", "mode": "demo" if DEMO else "live", "environment": settings().environment, "ruleset_version": DEFAULT_RULESET}


@app.get("/api/v1/sources/health")
def sources_health(as_of: str | None = None):
    data = dashboard(as_of)
    definitions = registry(phase2=not DEMO)
    with Session(DB) as session:
        failures = session.scalars(select(IngestionRun).where(IngestionRun.status == "failed").order_by(IngestionRun.started_at.desc()).limit(10)).all()
        return {"mode": data["mode"], **data["source_health"], "failed_jobs": [{"provider": j.provider, "at": j.started_at.isoformat(), "error_code": j.error_code} for j in failures], "sources": [{"indicator_id": m["id"], "status": m["status"], "provider": m["provider"], "last_successful_ingestion": m["ingested_at"], "publication_lag_days": definitions[m["id"]]["publication_lag_days"]} for m in data["metrics"]]}


@app.get("/api/v1/dashboard")
def get_dashboard(as_of: str | None = None, ruleset: str | None = None):
    return dashboard(as_of, ruleset)


@app.get("/api/v1/external-liquidity")
def external_liquidity(as_of: str | None = None):
    return external_liquidity_view(dashboard(as_of, "v2"))


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
    if indicator_id not in registry(phase2=True):
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
def cycle(cycle_id: str, as_of: str | None = None, ruleset: str | None = None):
    data = dashboard(as_of, ruleset)
    for item in data["cycles"]:
        if item["id"] == cycle_id:
            return item
    raise HTTPException(404, "Unknown cycle")


@app.get("/api/v1/alerts")
def alerts(as_of: str | None = None, status: str | None = None, severity: str | None = None):
    items = dashboard(as_of)["alerts"]
    if status == "active":
        items = [a for a in items if a["status"] in ("WATCH", "WARNING", "CRITICAL", "TRIGGERED", "CONFIRMED")]
    elif status:
        items = [a for a in items if a["status"].lower() == status.lower()]
    if severity:
        items = [a for a in items if (a["severity"] or "").lower() == severity.lower()]
    return {"items": items, "total": len(items)}


@app.get("/api/v1/alerts/history")
def alert_history(rule_id: str | None = None, limit: int = Query(50, ge=1, le=200), offset: int = Query(0, ge=0)):
    with Session(DB) as session:
        query = select(AlertTransition).where(AlertTransition.mode == ("demo" if DEMO else "live"))
        if rule_id:
            query = query.where(AlertTransition.rule_id == rule_id)
        items = session.scalars(query.order_by(AlertTransition.evaluated_at.desc()).offset(offset).limit(limit)).all()
        return {"items": [{"id": r.id, "rule_id": r.rule_id, "ruleset_version": r.ruleset_version, "status": r.status, "evaluated_at": r.evaluated_at.isoformat(), "evidence": json.loads(r.evidence_json)} for r in items], "limit": limit, "offset": offset}


@app.get("/api/v1/alerts/{alert_id}")
def alert(alert_id: str, as_of: str | None = None):
    for item in dashboard(as_of)["alerts"]:
        if item["id"] == alert_id:
            return item
    raise HTTPException(404, "Unknown alert")


@app.get("/api/v1/config/rulesets")
def rulesets():
    return {"items": [{"version": version, "calibration": "provisional", "cycle_weights": rules(version)["cycle_weights"]} for version in ("v1", "v2")]}


@app.get("/api/v1/replay")
def replay(as_of: str, vintage_mode: str = "system_known", ruleset: str = "v1"):
    if vintage_mode not in {"system_known", "source_known"}:
        raise HTTPException(422, "Unknown vintage mode")
    result = dashboard(as_of, ruleset, vintage_mode)
    result["replay_mode"] = vintage_mode
    result["historical_rules_warning"] = "v2 is experimental and not a ruleset known at this historical date" if ruleset == "v2" else None
    return result


def audit_admin(session, operator_id, action, result, details=""):
    session.add(AdminAudit(operator_id=operator_id, action=action, result=result, at=datetime.now(timezone.utc), details=details))
    session.commit()


@app.post("/api/v1/admin/imports/csv")
async def import_csv(request: Request, x_source_provider: str = Header(), x_license_attestation: str = Header(), operator=Depends(require_scope("imports:write"))):
    if DEMO:
        raise HTTPException(403, "Live imports are disabled in demo mode")
    if x_license_attestation != "public-redistributable":
        raise HTTPException(422, "Public redistribution attestation required")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() not in {"text/csv", "application/csv"}:
        raise HTTPException(415, "CSV content type required")
    if not x_source_provider or len(x_source_provider) > 100:
        raise HTTPException(422, "Invalid source provider")
    raw = await request.body()
    try:
        records = parse_manual_csv(raw, x_source_provider)
        with Session(DB) as session:
            outcome = ingest_records(session, records, raw, x_source_provider)
            if outcome["inserted"]:
                persist_transitions(session, evaluate_v2(session, datetime.now(timezone.utc)), datetime.now(timezone.utc))
            audit_admin(session, operator["operator_id"], "csv_import", "success", f"provider={x_source_provider};run_id={outcome['run_id']};inserted={outcome['inserted']}")
            if outcome["revisions"]:
                audit_admin(session, operator["operator_id"], "observation_revision", "recorded", f"run_id={outcome['run_id']};count={outcome['revisions']}")
            return outcome
    except ValueError as exc:
        with Session(DB) as session:
            audit_admin(session, operator["operator_id"], "csv_import", "rejected", type(exc).__name__)
        raise HTTPException(422, str(exc))


class IngestionRequest(BaseModel):
    adapter: str


class ReleasePackageRequest(BaseModel):
    provider: str
    source_reference: str
    publication_evidence_url: str
    published_at: datetime
    source_sha256: str
    redistribution_basis: str
    definition_version: str
    original_source_base64: str
    extract_csv_base64: str


@app.post("/api/v1/admin/imports/release")
def import_release(payload: ReleasePackageRequest, operator=Depends(require_scope("imports:write"))):
    if DEMO:
        raise HTTPException(403, "Live imports are disabled in demo mode")
    try:
        original = base64.b64decode(payload.original_source_base64, validate=True)
        extract = base64.b64decode(payload.extract_csv_base64, validate=True)
        if not original or len(original) > 750_000 or len(extract) > 750_000:
            raise ValueError("Source and extract must be nonempty and at most 750 KB each")
        if hashlib.sha256(original).hexdigest() != payload.source_sha256:
            raise ValueError("Original source hash mismatch")
        manifest = ReleaseManifest(**payload.model_dump(exclude={"original_source_base64", "extract_csv_base64"}))
        records = parse_release_package(extract, manifest)
        with Session(DB) as session:
            outcome = ingest_records(session, records, extract, payload.provider, original_raw=original)
            if outcome["inserted"]:
                persist_transitions(session, evaluate_v2(session, datetime.now(timezone.utc)), datetime.now(timezone.utc))
            audit_admin(session, operator["operator_id"], "release_import", "success", f"provider={payload.provider};run_id={outcome['run_id']};inserted={outcome['inserted']};source_sha256={outcome['snapshot_sha256']};definition={payload.definition_version};publication_evidence={payload.publication_evidence_url};rights={payload.redistribution_basis}")
            return outcome
    except (ValueError, binascii.Error) as exc:
        with Session(DB) as session:
            audit_admin(session, operator["operator_id"], "release_import", "rejected", type(exc).__name__)
        raise HTTPException(422, str(exc))


@app.post("/api/v1/admin/ingestion/run")
def run_ingestion(payload: IngestionRequest, operator=Depends(require_scope("ingestion:run"))):
    if DEMO:
        raise HTTPException(403, "Live ingestion is disabled in demo mode")
    if payload.adapter != "us_treasury":
        raise HTTPException(422, "Adapter unavailable or requires a licensed feed")
    try:
        raw, records = TreasuryAdapter().fetch(datetime.now(timezone.utc))
        with Session(DB) as session:
            outcome = ingest_records(session, records, raw, "us_treasury")
            if outcome["inserted"]:
                persist_transitions(session, evaluate_v2(session, datetime.now(timezone.utc)), datetime.now(timezone.utc))
            audit_admin(session, operator["operator_id"], "treasury_ingestion", "success", f"run_id={outcome['run_id']};inserted={outcome['inserted']}")
            if outcome["revisions"]:
                audit_admin(session, operator["operator_id"], "observation_revision", "recorded", f"run_id={outcome['run_id']};count={outcome['revisions']}")
            return outcome
    except Exception as exc:
        # Do not return upstream response content or credentials to clients.
        with Session(DB) as session:
            job = IngestionRun(provider="us_treasury", started_at=datetime.now(timezone.utc), finished_at=datetime.now(timezone.utc), status="failed", error_code=type(exc).__name__)
            session.add(job)
            audit_admin(session, operator["operator_id"], "treasury_ingestion", "failed", type(exc).__name__)
        raise HTTPException(502, "Source ingestion failed; last known data retained")
