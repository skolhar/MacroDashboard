from datetime import date, datetime, timedelta, timezone
import json
import os
import base64
import binascii
import hashlib
from uuid import uuid4
from fastapi import FastAPI, HTTPException, Query, Request, Depends, Header
from fastapi.responses import JSONResponse, Response
from fastapi.exceptions import RequestValidationError
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session
from packages.domain.config import registry, rules
from packages.domain.models import Observation, AlertTransition, IngestionRun, AdminAudit, SourceReleaseReview, RBIReserveComponent
from packages.domain.store import engine, observations_at
from packages.domain.settings import settings
from packages.domain.security import RateLimiter, DatabaseRateLimiter, RateLimitStoreUnavailable, require_scope, client_identity
from packages.connectors.manual import parse_manual_csv
from packages.connectors.india_release import ReleaseManifest, parse_release_package, validate_manifest, INDICATORS
from packages.connectors.treasury import TreasuryAdapter
from packages.jobs.ingest import ingest_records
from packages.jobs.source_archive import max_bytes as source_archive_max_bytes, archive_original, read_original
from packages.connectors.rbi_wss import parse_rbi_wss_reserves
from packages.scoring.engine import compute
from packages.scoring.alerts import fx_alert
from packages.scoring.engine_v2 import compute_v2
from packages.scoring.inflections import evaluate_v2, persist_transitions
from packages.scoring.external_liquidity import external_liquidity_view
from packages.market.base import instruments as market_instruments_registry
from packages.market.yahoo import MarketSourceUnavailable
from packages.market.providers import provider_for
from packages.market.operations import history_at as market_history_at, status_at as market_status_at, refresh as refresh_market

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
    max_body = source_archive_max_bytes() * 2 + 2_000_000 if request.url.path == "/api/v1/admin/imports/release" else source_archive_max_bytes() if request.url.path == "/api/v1/admin/releases/archive" else 1_000_000
    if request.method != "GET" and body_length > max_body:
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
    result = external_liquidity_view(dashboard(as_of, "v2"))
    with Session(DB) as session:
        rows = observations_at(session, "fx_gross_reserves_usd", parsed_as_of(as_of), "system_known", DEMO)
        latest = rows[-1] if rows else None
        previous = rows[-2] if len(rows) > 1 else None
        components = session.get(RBIReserveComponent, latest.id) if latest else None
        review = session.get(SourceReleaseReview, latest.release_review_id) if latest and latest.release_review_id else None
        first_friday = date(2018, 1, 5)
        known_weeks = {row.period_end for row in rows}
        cutoff = min(parsed_as_of(as_of).date(), latest.period_end if latest else parsed_as_of(as_of).date())
        missing_fridays = 0
        day = first_friday
        while day <= cutoff:
            missing_fridays += day not in known_weeks
            day += timedelta(days=7)
        result["rbi_reserves"] = {"reference_week": latest.period_end.isoformat(), "published_at": latest.published_at.isoformat(), "gross_usd_mn": float(components.total_usd_mn), "change_usd_mn": float((latest.value - previous.value) * 1000) if previous else None, "quality": latest.quality, "source_url": latest.source_reference, "vintage_id": latest.vintage_id, "release_review_id": review.id if review else None, "reviewed_by": review.approved_by if review else None, "missing_expected_fridays_since_2018": missing_fridays, "components_usd_mn": {key: float(getattr(components, key)) for key in ("foreign_currency_assets_usd_mn", "gold_usd_mn", "sdr_usd_mn", "imf_reserve_tranche_usd_mn")}} if components else None
    return result


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
        return {"indicator_id": indicator_id, "mode": "demo" if DEMO else "live", "vintage_mode": vintage_mode, "items": [{"id": r.id, "period_start": r.period_start.isoformat(), "period_end": r.period_end.isoformat(), "value": float(r.value), "unit": r.unit, "published_at": r.published_at.isoformat(), "ingested_at": r.ingested_at.isoformat(), "provider": r.provider, "rate_kind": r.rate_kind or ("published_reference_rate" if indicator_id == "usd_inr_spot" and r.provider in {"rbi", "fbil"} else None), "source_url": r.source_url, "vintage_id": r.vintage_id, "release_review_id": r.release_review_id, "quality": r.quality, "is_revision": r.is_revision} for r in rows]}


def market_research_available() -> bool:
    return settings().market_research_enabled


@app.get("/api/v1/market/instruments")
def market_instruments(as_of: str | None = None):
    specs = market_instruments_registry()
    enabled = market_research_available()
    provider = settings().market_provider
    ready = enabled and provider == "yahoo"
    timestamp = parsed_as_of(as_of) if as_of else datetime.now(timezone.utc)
    with Session(DB) as session:
        return {"mode": "isolated_research" if ready else "unavailable", "provider": provider, "as_of": timestamp.isoformat(), "items": [{"id": item.id, "name": item.name, "kind": item.kind, "market": item.market, "currency": item.currency, "timezone": item.timezone, "provider": provider, "provider_symbol": item.symbol(provider), "future_upstox_mapping": "UNAVAILABLE" if item.upstox is None else "CONFIGURED", "status": market_status_at(session, item, provider, timestamp) if ready else {"status": "DATA_UNAVAILABLE", "reason": "Market research feed or provider adapter is unavailable; no synthetic fallback"}} for item in specs.values()]}


@app.get("/api/v1/market/instruments/{instrument_id}/history")
def market_history(instrument_id: str, as_of: str | None = None, from_date: date | None = Query(None, alias="from"), to_date: date | None = Query(None, alias="to"), basis: str = "raw", limit: int = Query(1000, ge=1, le=3000)):
    spec = market_instruments_registry().get(instrument_id)
    if spec is None:
        raise HTTPException(404, "Unknown market instrument")
    if basis not in {"raw", "adjusted_close"} or (from_date and to_date and from_date > to_date):
        raise HTTPException(422, "Invalid market history query")
    enabled = market_research_available()
    provider = settings().market_provider
    ready = enabled and provider == "yahoo"
    timestamp = parsed_as_of(as_of) if as_of else datetime.now(timezone.utc)
    with Session(DB) as session:
        rows = market_history_at(session, instrument_id, provider, timestamp, from_date, to_date)[-limit:] if ready else []
        return {"instrument_id": instrument_id, "provider": provider, "provider_symbol": spec.symbol(provider), "as_of": timestamp.isoformat(), "basis": basis, "adjusted_ohlc_available": False, "status": market_status_at(session, spec, provider, timestamp) if ready else {"status": "DATA_UNAVAILABLE", "reason": "Market research feed or provider adapter is unavailable"}, "items": [{"session_date": row.session_date.isoformat(), "open": float(row.open) if basis == "raw" else None, "high": float(row.high) if basis == "raw" else None, "low": float(row.low) if basis == "raw" else None, "close": float(row.close) if basis == "raw" else float(row.adjusted_close) if row.adjusted_close is not None else None, "raw_open": float(row.open), "raw_high": float(row.high), "raw_low": float(row.low), "raw_close": float(row.close), "adjusted_close": float(row.adjusted_close) if row.adjusted_close is not None else None, "volume": row.volume, "currency": row.currency, "market": row.market, "exchange_timezone": row.exchange_timezone, "provider_exchange": row.provider_exchange, "retrieved_at": row.retrieved_at.isoformat(), "source_url": row.source_url, "quality": row.quality, "price_basis": row.price_basis, "content_hash": row.content_hash, "contract_identity": row.contract_identity, "roll_policy": row.roll_policy} for row in rows]}


class MarketRefreshRequest(BaseModel):
    instrument_id: str
    provider: str | None = None
    start: date | None = None
    end_exclusive: date | None = None


@app.post("/api/v1/admin/market/refresh")
def market_refresh(payload: MarketRefreshRequest, operator=Depends(require_scope("ingestion:run"))):
    if not market_research_available():
        raise HTTPException(403, "Market research ingestion is disabled")
    spec = market_instruments_registry().get(payload.instrument_id)
    provider_name = payload.provider or settings().market_provider
    if spec is None or provider_name not in {"yahoo", "upstox"} or provider_name != settings().market_provider or spec.symbol(provider_name) is None:
        raise HTTPException(422, "Unknown instrument or provider")
    with Session(DB) as session:
        try:
            result = refresh_market(session, provider_for(provider_name), spec, payload.start, payload.end_exclusive)
            audit_admin(session, operator["operator_id"], "market_refresh", result["status"], f"instrument={spec.id};provider={provider_name};inserted={result['inserted']}")
            return result
        except ValueError as exc:
            audit_admin(session, operator["operator_id"], "market_refresh", "rejected", type(exc).__name__)
            raise HTTPException(422, str(exc))
        except MarketSourceUnavailable as exc:
            audit_admin(session, operator["operator_id"], "market_refresh", "failed", type(exc).__name__)
            raise HTTPException(503, "Yahoo source unavailable")


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
        if any(record.indicator_id in {id for allowed in INDICATORS.values() for id in allowed} for record in records):
            raise ValueError("Indicator requires an independently approved source-release review")
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
    review_id: int
    provider: str
    source_reference: str
    publication_evidence_url: str
    published_at: datetime
    source_sha256: str
    redistribution_basis: str
    definition_version: str
    original_source_base64: str
    extract_csv_base64: str


class ReleaseReviewRequest(BaseModel):
    provider: str
    source_reference: str
    original_archive_reference: str
    publication_evidence_url: str
    publication_evidence_note: str
    published_at: datetime
    source_sha256: str
    extract_sha256: str
    redistribution_basis: str
    entitlement_reference: str
    definition_version: str


class ReleaseApprovalRequest(BaseModel):
    publication_evidence_verified: bool
    entitlement_verified: bool
    review_note: str


@app.post("/api/v1/admin/releases/archive")
async def upload_release_original(request: Request, x_source_provider: str = Header(), operator=Depends(require_scope("imports:write"))):
    if DEMO:
        raise HTTPException(403, "Live source archive is disabled in demo mode")
    if x_source_provider not in INDICATORS:
        raise HTTPException(422, "Unknown source provider")
    if request.headers.get("content-type", "").split(";", 1)[0].strip().lower() != "application/octet-stream":
        raise HTTPException(415, "Original publisher file content type required")
    raw = bytearray()
    async for chunk in request.stream():
        if len(raw) + len(chunk) > source_archive_max_bytes():
            raise HTTPException(413, "Original publisher file exceeds archive limit")
        raw.extend(chunk)
    try:
        result = archive_original(bytes(raw))
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    with Session(DB) as session:
        audit_admin(session, operator["operator_id"], "release_archive_upload", "success", f"provider={x_source_provider};sha256={result['sha256']};size={result['size_bytes']}")
    return result


@app.post("/api/v1/admin/releases/reviews")
def submit_release_review(payload: ReleaseReviewRequest, operator=Depends(require_scope("imports:write"))):
    if DEMO:
        raise HTTPException(403, "Live release review is disabled in demo mode")
    try:
        manifest = ReleaseManifest(provider=payload.provider, source_reference=payload.source_reference, publication_evidence_url=payload.publication_evidence_url, published_at=payload.published_at, source_sha256=payload.source_sha256, redistribution_basis=payload.redistribution_basis, definition_version=payload.definition_version)
        validate_manifest(manifest)
        if len(payload.extract_sha256) != 64 or any(c not in "0123456789abcdef" for c in payload.extract_sha256):
            raise ValueError("Extract SHA-256 required")
        if not 20 <= len(payload.publication_evidence_note) <= 2000:
            raise ValueError("Independent publication evidence note required")
        if not payload.entitlement_reference.startswith(("https://", "archive://")):
            raise ValueError("Original archive and entitlement references required")
        if max(len(payload.original_archive_reference), len(payload.entitlement_reference)) > 1000:
            raise ValueError("Review reference too long")
        read_original(payload.original_archive_reference, payload.source_sha256)
    except ValueError as exc:
        raise HTTPException(422, str(exc))
    with Session(DB) as session:
        review = SourceReleaseReview(provider=payload.provider, source_reference=payload.source_reference, original_archive_reference=payload.original_archive_reference, source_sha256=payload.source_sha256, extract_sha256=payload.extract_sha256, published_at=payload.published_at, publication_evidence_url=payload.publication_evidence_url, publication_evidence_note=payload.publication_evidence_note, entitlement_basis=payload.redistribution_basis, entitlement_reference=payload.entitlement_reference, definition_version=payload.definition_version, submitted_by=operator["operator_id"], submitted_at=datetime.now(timezone.utc), status="pending")
        session.add(review)
        session.flush()
        review_id = review.id
        audit_admin(session, operator["operator_id"], "release_review_submit", "pending", f"review_id={review_id};provider={payload.provider}")
        return {"review_id": review_id, "status": "pending"}


@app.get("/api/v1/admin/releases/reviews/{review_id}")
def get_release_review(review_id: int, operator=Depends(require_scope("releases:approve"))):
    with Session(DB) as session:
        item = session.get(SourceReleaseReview, review_id)
        if item is None:
            raise HTTPException(404, "Release review not found")
        return {key: getattr(item, key).isoformat() if isinstance(getattr(item, key), datetime) else getattr(item, key) for key in ("id", "provider", "source_reference", "original_archive_reference", "source_sha256", "extract_sha256", "published_at", "publication_evidence_url", "publication_evidence_note", "entitlement_basis", "entitlement_reference", "definition_version", "submitted_by", "submitted_at", "status", "approved_by", "approved_at", "review_note")}


@app.get("/api/v1/admin/releases/reviews/{review_id}/original")
def download_release_original(review_id: int, operator=Depends(require_scope("releases:approve"))):
    with Session(DB) as session:
        item = session.get(SourceReleaseReview, review_id)
        if item is None:
            raise HTTPException(404, "Release review not found")
        try:
            raw = read_original(item.original_archive_reference, item.source_sha256)
        except ValueError:
            raise HTTPException(409, "Archived original unavailable or failed integrity check")
        audit_admin(session, operator["operator_id"], "release_archive_read", "success", f"review_id={review_id}")
        return Response(content=raw, media_type="application/octet-stream", headers={"Cache-Control": "no-store", "Content-Disposition": "attachment; filename=source-release.bin"})


@app.post("/api/v1/admin/releases/reviews/{review_id}/approve")
def approve_release_review(review_id: int, payload: ReleaseApprovalRequest, operator=Depends(require_scope("releases:approve"))):
    if DEMO:
        raise HTTPException(403, "Live release review is disabled in demo mode")
    if not payload.publication_evidence_verified or not payload.entitlement_verified or not 20 <= len(payload.review_note) <= 2000:
        raise HTTPException(422, "Independent evidence, entitlement and review note required")
    with Session(DB) as session:
        item = session.get(SourceReleaseReview, review_id)
        if item is None:
            raise HTTPException(404, "Release review not found")
        if item.status != "pending" or item.submitted_by == operator["operator_id"]:
            raise HTTPException(409, "Independent pending review required")
        try:
            read_original(item.original_archive_reference, item.source_sha256)
        except ValueError:
            raise HTTPException(409, "Archived original unavailable or failed integrity check")
        item.status = "approved"
        item.approved_by = operator["operator_id"]
        item.approved_at = datetime.now(timezone.utc)
        item.review_note = payload.review_note
        audit_admin(session, operator["operator_id"], "release_review_approve", "approved", f"review_id={review_id}")
        return {"review_id": review_id, "status": "approved", "approved_by": item.approved_by}


@app.post("/api/v1/admin/imports/release")
def import_release(payload: ReleasePackageRequest, operator=Depends(require_scope("imports:write"))):
    if DEMO:
        raise HTTPException(403, "Live imports are disabled in demo mode")
    try:
        original = base64.b64decode(payload.original_source_base64, validate=True)
        extract = base64.b64decode(payload.extract_csv_base64, validate=True)
        if not original or len(original) > source_archive_max_bytes() or not extract or len(extract) > 1_000_000:
            raise ValueError("Source or extract exceeds configured limit")
        if hashlib.sha256(original).hexdigest() != payload.source_sha256:
            raise ValueError("Original source hash mismatch")
        manifest = ReleaseManifest(**payload.model_dump(exclude={"review_id", "original_source_base64", "extract_csv_base64"}))
        records = parse_release_package(extract, manifest)
        reserve_release = None
        if any(record.indicator_id == "fx_gross_reserves_usd" for record in records):
            reserve_release = parse_rbi_wss_reserves(original, manifest)
            if len(records) != 1 or records[0].period_start != reserve_release.reference_week or records[0].period_end != reserve_release.reference_week or records[0].value != reserve_release.total_usd_bn:
                raise ValueError("Reviewed extract does not match original WSS reference week or gross USD-million total")
        with Session(DB) as session:
            review = session.get(SourceReleaseReview, payload.review_id)
            if review is None or review.status != "approved":
                raise ValueError("Approved release review required")
            if read_original(review.original_archive_reference, review.source_sha256) != original:
                raise ValueError("Original package differs from controlled source archive")
            if (review.provider, review.source_reference, review.publication_evidence_url, review.published_at, review.source_sha256, review.extract_sha256, review.entitlement_basis, review.definition_version) != (payload.provider, payload.source_reference, payload.publication_evidence_url, payload.published_at, payload.source_sha256, hashlib.sha256(extract).hexdigest(), payload.redistribution_basis, payload.definition_version):
                raise ValueError("Package does not match approved release review")
            outcome = ingest_records(session, records, extract, payload.provider, original_raw=original, release_review_id=review.id, reserve_release=reserve_release)
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
