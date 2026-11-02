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
from pydantic import BaseModel, Field, model_validator
from typing import Literal
from decimal import Decimal
from sqlalchemy import select
from sqlalchemy.orm import Session
from packages.domain.config import registry, rules
from packages.domain.models import Observation, AlertTransition, IngestionRun, AdminAudit, SourceReleaseReview, RBIReserveComponent, ResearchEvidence, ResearchInterpretation, CycleAssessmentSnapshot, CycleInvestigation, DiscoverySnapshot, DiscoveryHypothesis
from packages.domain.store import engine, observations_at
from packages.domain.settings import settings
from packages.domain.security import RateLimiter, DatabaseRateLimiter, RateLimitStoreUnavailable, require_scope, client_identity, authorize_token
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
from packages.scoring.cycle_intelligence import catalog as mechanism_catalog, evaluate as evaluate_cycles, persist_assessment, replay_snapshot
from packages.scoring.discovery import evaluate as evaluate_discovery, persist as persist_discovery, replay as replay_discovery
from packages.scoring.economic_coverage import coverage as economic_coverage

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


def private_research_operator(scope: str, x_admin_token: str | None):
    if DEMO or settings().environment not in {"development", "staging"}:
        raise HTTPException(403, "Private research is disabled in this environment")
    with Session(DB) as session:
        return authorize_token(session, x_admin_token, scope, legacy=False)


def research_reader(x_admin_token: str | None = Header(default=None)):
    return private_research_operator("research:read", x_admin_token)


def research_writer(x_admin_token: str | None = Header(default=None)):
    return private_research_operator("research:write", x_admin_token)


class ResearchEvidenceRequest(BaseModel):
    indicator_key: str | None = Field(default=None, min_length=3, max_length=100)
    indicator_or_claim: str = Field(min_length=3, max_length=160)
    frequency: Literal["business_daily", "daily", "weekly", "fortnightly", "monthly", "quarterly", "annual", "event"] = "event"
    value_text: str | None = Field(default=None, min_length=1, max_length=1000)
    value_numeric: Decimal | None = None
    unit: str | None = Field(default=None, max_length=40)
    period_start: date
    period_end: date
    source_name: str = Field(min_length=2, max_length=100)
    source_reference: str = Field(min_length=8, max_length=1000)
    published_at: datetime | None = None
    reliability_note: str = Field(min_length=10, max_length=2000)
    usage_basis: str = Field(min_length=10, max_length=1000)
    quality: Literal["preliminary", "estimated", "secondary", "revised", "verified"]
    revision_id: str = Field(default="legacy-unclassified", min_length=1, max_length=80)
    observation_key: str = Field(min_length=8, max_length=160)
    # Original PR #16 clients may still send these fields. They are never
    # stored as source facts or treated as a causal interpretation.
    cycle_id: str | None = None
    mechanism_id: str | None = None
    stance: Literal["supports", "contradicts", "neutral"] | None = None

    @model_validator(mode="after")
    def value_required(self):
        if self.value_text is None and self.value_numeric is None:
            raise ValueError("Numeric value or qualitative finding required")
        if self.value_numeric is not None and not self.value_numeric.is_finite():
            raise ValueError("Numeric research value must be finite")
        if self.indicator_key is None:
            self.indicator_key = "legacy_" + hashlib.sha256(self.observation_key.encode()).hexdigest()[:16]
        return self


@app.get("/api/v1/research/catalog")
def research_catalog():
    return mechanism_catalog()


@app.get("/api/v1/research/overview")
def research_overview(as_of: str | None = None, operator=Depends(research_reader)):
    timestamp = parsed_as_of(as_of)
    with Session(DB) as session:
        result = evaluate_cycles(session, timestamp)
        result["investigations"] = [{"id": row.id, "cycle_id": row.cycle_id, "candidate_key": row.candidate_key, "status": row.status, "opened_at": row.opened_at.isoformat()} for row in session.scalars(select(CycleInvestigation).where(CycleInvestigation.opened_at <= timestamp).order_by(CycleInvestigation.opened_at.desc()).limit(30)).all()]
        return result


@app.post("/api/v1/research/evidence")
def add_research_evidence(payload: ResearchEvidenceRequest, operator=Depends(research_writer)):
    now = datetime.now(timezone.utc)
    if payload.period_start > payload.period_end or payload.period_end > now.date() or (payload.published_at and (payload.published_at.tzinfo is None or payload.published_at > now)):
        raise HTTPException(422, "Invalid observation period or publication timestamp")
    if not payload.source_reference.startswith("https://") or not payload.usage_basis.strip():
        raise HTTPException(422, "Attributable HTTPS source and permitted-use basis required")
    with Session(DB) as session:
        raw_fields = payload.model_dump(exclude={"cycle_id", "mechanism_id", "stance"})
        legacy_fields = any(getattr(payload, field) is not None for field in ("cycle_id", "mechanism_id", "stance"))
        prior = session.scalar(select(ResearchEvidence).where(ResearchEvidence.observation_key == payload.observation_key))
        if prior:
            if any(getattr(prior, key) != value for key, value in raw_fields.items() if key != "observation_key"):
                raise HTTPException(409, "Observation key already names different evidence")
            return {"id": prior.id, "status": "duplicate", "legacy_causal_fields_ignored": legacy_fields}
        item = ResearchEvidence(**raw_fields, retrieved_at=now, entered_by=operator["operator_id"])
        session.add(item)
        session.flush()
        item_id = item.id
        audit_admin(session, operator["operator_id"], "research_evidence_add", "success", f"id={item_id};indicator={payload.indicator_key};source={payload.source_name};revision={payload.revision_id}")
        return {"id": item_id, "status": "recorded", "retrieved_at": now.isoformat(), "tier": "private_research", "legacy_causal_fields_ignored": legacy_fields}


class ResearchInterpretationRequest(BaseModel):
    observation_id: int = Field(gt=0)
    related_observation_id: int | None = Field(default=None, gt=0)
    cycle_id: str
    mechanism_id: str
    evidence_type: Literal["trend", "feedback_link", "corrective_response", "policy_response"]
    stance: Literal["supports", "contradicts", "neutral"]
    rationale: str = Field(min_length=30, max_length=3000)
    alternative_explanations: list[str] = Field(min_length=1, max_length=8)
    interpretation_key: str = Field(min_length=8, max_length=160)
    revision_id: str = Field(min_length=1, max_length=80)
    supersedes_id: int | None = Field(default=None, gt=0)

    @model_validator(mode="after")
    def explain_causal_claim(self):
        if any(len(item.strip()) < 5 for item in self.alternative_explanations):
            raise ValueError("Each alternative explanation needs meaningful text")
        return self


@app.post("/api/v1/research/interpretations")
def add_research_interpretation(payload: ResearchInterpretationRequest, operator=Depends(research_writer)):
    cfg = mechanism_catalog()["cycles"]
    mechanism = next((m for m in cfg.get(payload.cycle_id, {}).get("mechanisms", []) if m["id"] == payload.mechanism_id), None)
    if mechanism is None or (mechanism["role"] == "reinforcing") != (payload.evidence_type in {"trend", "feedback_link"}):
        raise HTTPException(422, "Evidence type does not match a known mechanism")
    with Session(DB) as session:
        prior = session.scalar(select(ResearchInterpretation).where(ResearchInterpretation.interpretation_key == payload.interpretation_key))
        if prior:
            if any(getattr(prior, key) != getattr(payload, key) for key in ("observation_id", "related_observation_id", "cycle_id", "mechanism_id", "evidence_type", "stance", "rationale", "revision_id", "supersedes_id")) or json.loads(prior.alternatives_json) != payload.alternative_explanations:
                raise HTTPException(409, "Interpretation key already names a different assessment")
            return {"id": prior.id, "status": "duplicate"}
        observed = session.get(ResearchEvidence, payload.observation_id)
        related = session.get(ResearchEvidence, payload.related_observation_id) if payload.related_observation_id else None
        if observed is None or (payload.related_observation_id and related is None):
            raise HTTPException(422, "Research observation not found")
        if payload.evidence_type == "feedback_link" and (related is None or related.indicator_key == observed.indicator_key or related.period_end > observed.period_end):
            raise HTTPException(422, "Feedback interpretation needs an earlier independent observed driver")
        if payload.evidence_type != "feedback_link" and related is not None:
            raise HTTPException(422, "Related observation applies only to a feedback link")
        if payload.supersedes_id:
            earlier = session.get(ResearchInterpretation, payload.supersedes_id)
            if earlier is None or (earlier.observation_id, earlier.cycle_id, earlier.mechanism_id, earlier.entered_by) != (payload.observation_id, payload.cycle_id, payload.mechanism_id, operator["operator_id"]):
                raise HTTPException(422, "Revision must supersede this operator's prior interpretation of the same observation and mechanism")
        now = datetime.now(timezone.utc)
        item = ResearchInterpretation(observation_id=payload.observation_id, related_observation_id=payload.related_observation_id, cycle_id=payload.cycle_id, mechanism_id=payload.mechanism_id, evidence_type=payload.evidence_type, stance=payload.stance, rationale=payload.rationale, alternatives_json=json.dumps(payload.alternative_explanations), interpretation_key=payload.interpretation_key, revision_id=payload.revision_id, supersedes_id=payload.supersedes_id, assessed_at=now, entered_by=operator["operator_id"])
        session.add(item)
        session.flush()
        item_id = item.id
        audit_admin(session, operator["operator_id"], "research_interpretation_add", "success", f"id={item_id};observation={observed.id};cycle={payload.cycle_id};mechanism={payload.mechanism_id};revision={payload.revision_id}")
        return {"id": item_id, "status": "recorded", "assessed_at": now.isoformat()}


class AssessmentRequest(BaseModel):
    assessment_key: str = Field(min_length=8, max_length=160)


@app.post("/api/v1/research/assessments")
def record_research_assessment(payload: AssessmentRequest, operator=Depends(research_writer)):
    now = datetime.now(timezone.utc)
    with Session(DB) as session:
        row = persist_assessment(session, now, payload.assessment_key, operator["operator_id"], now)
        audit_admin(session, operator["operator_id"], "research_assessment_record", "success", f"id={row.id};key={row.assessment_key};catalog={row.catalog_version};rules={row.rule_version}")
        return {"id": row.id, "assessment_key": row.assessment_key, "as_of": row.as_of.isoformat(), "catalog_version": row.catalog_version, "rule_version": row.rule_version}


@app.get("/api/v1/research/assessments/{assessment_id}")
def get_research_assessment(assessment_id: int, operator=Depends(research_reader)):
    with Session(DB) as session:
        row = session.get(CycleAssessmentSnapshot, assessment_id)
        if row is None:
            raise HTTPException(404, "Research assessment not found")
        return replay_snapshot(row)


class InvestigationRequest(BaseModel):
    candidate_key: str = Field(min_length=3, max_length=160)
    initial_observation: str = Field(min_length=10, max_length=2000)
    competing_hypotheses: list[str] = Field(min_length=1, max_length=8)
    questions: list[str] = Field(min_length=1, max_length=12)
    confirmation_criteria: str = Field(min_length=10, max_length=2000)
    falsification_criteria: str = Field(min_length=10, max_length=2000)


@app.post("/api/v1/research/investigations")
def start_investigation(payload: InvestigationRequest, operator=Depends(research_writer)):
    now = datetime.now(timezone.utc)
    with Session(DB) as session:
        assessment = evaluate_cycles(session, now)
        candidate = next((c for c in assessment["candidates"] if c["key"] == payload.candidate_key), None)
        if not candidate:
            raise HTTPException(422, "Candidate is unavailable; reassess current evidence")
        existing = session.scalar(select(CycleInvestigation).where(CycleInvestigation.candidate_key == payload.candidate_key).order_by(CycleInvestigation.id.desc()).limit(1))
        if existing and existing.status in {"open", "monitoring"}:
            return {"id": existing.id, "status": existing.status, "duplicate": True}
        item = CycleInvestigation(cycle_id=candidate["cycle_id"], candidate_key=payload.candidate_key, initial_observation=payload.initial_observation, evidence_snapshot_json=json.dumps(candidate), competing_hypotheses_json=json.dumps(payload.competing_hypotheses), questions_json=json.dumps(payload.questions), confirmation_criteria=payload.confirmation_criteria, falsification_criteria=payload.falsification_criteria, status="open", opened_by=operator["operator_id"], opened_at=now, updated_at=now)
        session.add(item)
        session.flush()
        item_id = item.id
        audit_admin(session, operator["operator_id"], "research_investigation_start", "success", f"id={item_id};cycle={candidate['cycle_id']}")
        return {"id": item_id, "status": "open", "duplicate": False}


@app.get("/api/v1/research/investigations/{investigation_id}")
def get_investigation(investigation_id: int, operator=Depends(research_reader)):
    with Session(DB) as session:
        item = session.get(CycleInvestigation, investigation_id)
        if not item:
            raise HTTPException(404, "Investigation not found")
        return {"id": item.id, "cycle_id": item.cycle_id, "candidate_key": item.candidate_key, "initial_observation": item.initial_observation, "evidence_snapshot": json.loads(item.evidence_snapshot_json), "competing_hypotheses": json.loads(item.competing_hypotheses_json), "questions": json.loads(item.questions_json), "confirmation_criteria": item.confirmation_criteria, "falsification_criteria": item.falsification_criteria, "status": item.status, "opened_by": item.opened_by, "opened_at": item.opened_at.isoformat(), "updated_at": item.updated_at.isoformat()}


class InvestigationStatusRequest(BaseModel):
    status: Literal["open", "monitoring", "rejected", "closed"]


@app.patch("/api/v1/research/investigations/{investigation_id}")
def update_investigation(investigation_id: int, payload: InvestigationStatusRequest, operator=Depends(research_writer)):
    with Session(DB) as session:
        item = session.get(CycleInvestigation, investigation_id)
        if not item:
            raise HTTPException(404, "Investigation not found")
        prior_status = item.status
        item.status = payload.status
        item.updated_at = datetime.now(timezone.utc)
        audit_admin(session, operator["operator_id"], "research_investigation_status", "success", f"id={item.id};from={prior_status};to={item.status}")
        return {"id": item.id, "status": item.status}


@app.get("/api/v1/research/discovery")
def discovery_overview(as_of: str | None = None, knowledge_mode: Literal["system_known", "source_known"] = "system_known", episode_end: date | None = None, operator=Depends(research_reader)):
    when = parsed_as_of(as_of)
    if when > datetime.now(timezone.utc) or (episode_end and episode_end > when.date()):
        raise HTTPException(422, "Future discovery evaluation is unavailable")
    with Session(DB) as session:
        result = evaluate_discovery(session, when, knowledge_mode, episode_end=episode_end)
        # Current status must not leak into a historical as-of view.
        result["investigations"] = [{"id": item.id, "candidate_key": item.candidate_key, "status": item.status, "snapshot_id": item.snapshot_id, "updated_at": item.updated_at.isoformat()} for item in session.scalars(select(DiscoveryHypothesis).where(DiscoveryHypothesis.opened_at <= when, DiscoveryHypothesis.updated_at <= when).order_by(DiscoveryHypothesis.id.desc()).limit(30))]
        return result


@app.get("/api/v1/research/coverage")
def indian_research_coverage(as_of: str | None = None, operator=Depends(research_reader)):
    when = parsed_as_of(as_of)
    if when > datetime.now(timezone.utc):
        raise HTTPException(422, "Future coverage is unavailable")
    with Session(DB) as session:
        return economic_coverage(session, when)


class DiscoverySnapshotRequest(BaseModel):
    snapshot_key: str = Field(min_length=8, max_length=160)
    as_of: datetime | None = None
    knowledge_mode: Literal["system_known", "source_known"] = "system_known"
    episode_end: date | None = None


@app.post("/api/v1/research/discovery/snapshots")
def record_discovery(payload: DiscoverySnapshotRequest, operator=Depends(research_writer)):
    now = datetime.now(timezone.utc)
    when = payload.as_of or now
    if when.tzinfo is None or when > now or (payload.episode_end and payload.episode_end > when.date()):
        raise HTTPException(422, "Snapshot time must be timezone-aware and not in the future")
    with Session(DB) as session:
        try:
            row = persist_discovery(session, when, payload.snapshot_key, operator["operator_id"], payload.knowledge_mode, now, payload.episode_end)
        except ValueError as exc:
            raise HTTPException(409, str(exc)) from exc
        audit_admin(session, operator["operator_id"], "discovery_snapshot_record", "success", f"id={row.id};mode={row.knowledge_mode};rules={row.rule_version}")
        return {"id": row.id, "snapshot_key": row.snapshot_key, "as_of": row.as_of.isoformat(), "knowledge_mode": row.knowledge_mode, "rule_version": row.rule_version}


@app.get("/api/v1/research/discovery/snapshots/{snapshot_id}")
def get_discovery_snapshot(snapshot_id: int, operator=Depends(research_reader)):
    with Session(DB) as session:
        row = session.get(DiscoverySnapshot, snapshot_id)
        if row is None:
            raise HTTPException(404, "Discovery snapshot not found")
        return replay_discovery(row)


class DiscoveryHypothesisRequest(BaseModel):
    snapshot_id: int = Field(gt=0)
    candidate_key: str = Field(min_length=8, max_length=160)
    investigation_question: str = Field(min_length=10, max_length=2000)


@app.post("/api/v1/research/discovery/hypotheses")
def open_discovery_hypothesis(payload: DiscoveryHypothesisRequest, operator=Depends(research_writer)):
    with Session(DB) as session:
        snapshot = session.get(DiscoverySnapshot, payload.snapshot_id)
        if snapshot is None:
            raise HTTPException(404, "Discovery snapshot not found")
        candidate = next((item for item in json.loads(snapshot.result_json)["candidate_hypotheses"] if item["key"] == payload.candidate_key), None)
        if candidate is None:
            raise HTTPException(422, "Candidate absent from the frozen discovery result")
        prior = session.scalar(select(DiscoveryHypothesis).where(DiscoveryHypothesis.candidate_key == payload.candidate_key, DiscoveryHypothesis.status.in_(["open", "investigating"])).order_by(DiscoveryHypothesis.id.desc()).limit(1))
        if prior:
            return {"id": prior.id, "status": prior.status, "duplicate": True}
        now = datetime.now(timezone.utc)
        item = DiscoveryHypothesis(candidate_key=payload.candidate_key, snapshot_id=snapshot.id, hypothesis_json=json.dumps({**candidate, "investigation_question": payload.investigation_question}), status="open", opened_by=operator["operator_id"], opened_at=now, updated_at=now)
        session.add(item)
        session.flush()
        audit_admin(session, operator["operator_id"], "discovery_hypothesis_open", "success", f"id={item.id};snapshot={snapshot.id};candidate={item.candidate_key}")
        return {"id": item.id, "status": item.status, "duplicate": False, "catalog_promoted": False}


@app.get("/api/v1/research/discovery/hypotheses/{hypothesis_id}")
def get_discovery_hypothesis(hypothesis_id: int, operator=Depends(research_reader)):
    with Session(DB) as session:
        item = session.get(DiscoveryHypothesis, hypothesis_id)
        if item is None:
            raise HTTPException(404, "Discovery hypothesis not found")
        return {"id": item.id, "snapshot_id": item.snapshot_id, "status": item.status, "opened_by": item.opened_by, "opened_at": item.opened_at.isoformat(), "hypothesis": json.loads(item.hypothesis_json), "catalog_promoted": False}


class DiscoveryStatusRequest(BaseModel):
    status: Literal["open", "investigating", "rejected", "archived"]


@app.patch("/api/v1/research/discovery/hypotheses/{hypothesis_id}")
def update_discovery_hypothesis(hypothesis_id: int, payload: DiscoveryStatusRequest, operator=Depends(research_writer)):
    with Session(DB) as session:
        item = session.get(DiscoveryHypothesis, hypothesis_id)
        if item is None:
            raise HTTPException(404, "Discovery hypothesis not found")
        prior = item.status
        item.status = payload.status
        item.updated_at = datetime.now(timezone.utc)
        audit_admin(session, operator["operator_id"], "discovery_hypothesis_status", "success", f"id={item.id};from={prior};to={item.status}")
        return {"id": item.id, "status": item.status, "catalog_promoted": False}


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


def _market_close_rows(session, when, mode):
    """Point-in-time Nifty closes from the existing market-bars store.

    Reads both providers (Yahoo primary, Tapetide EOD top-up) and keeps the
    latest retrieval per session; market prices stay in their own append-only
    table rather than being duplicated into observations.
    """
    from types import SimpleNamespace
    from packages.market.operations import history_at
    rows = []
    for provider in ("yahoo", "tapetide"):
        try:
            rows.extend(history_at(session, "nifty50", provider, when))
        except Exception:
            continue
    by_session = {}
    for bar in rows:
        current = by_session.get(bar.session_date)
        if current is None or bar.retrieved_at >= current.retrieved_at:
            by_session[bar.session_date] = bar
    return [SimpleNamespace(
        period_start=bar.session_date, period_end=bar.session_date, value=bar.close,
        published_at=bar.retrieved_at, ingested_at=bar.retrieved_at,
        provider=bar.provider, source_url=bar.source_url,
        vintage_id=f"{bar.provider}-{bar.content_hash[:12]}", quality="secondary_unverified",
    ) for bar in sorted(by_session.values(), key=lambda bar: bar.session_date)]


@app.get("/api/v1/capital-flows")
def capital_flows(as_of: str | None = None, vintage_mode: str = "system_known", operator=Depends(research_reader)):
    """Private capital-flow investigation snapshot with point-in-time selection.

    Observations are selected as of the evaluation timestamp: `system_known`
    mode excludes anything ingested after the cutoff, `source_known` mode uses
    publisher timestamps. Later revisions never leak backward into a
    historical assessment, and future-dated rows are excluded by the scoring
    engine. Returns an explicit unavailable state when no attributable
    observations are stored; never fabricates flows.
    """
    from packages.scoring.capital_flow_reflexivity import evaluate
    from packages.domain.store import observations_at
    from packages.connectors.india_capital_flows import CapitalFlowRecord, monthly_returns_from_closes

    when = parsed_as_of(as_of)
    if vintage_mode not in {"system_known", "source_known"}:
        raise HTTPException(422, "vintage_mode must be system_known or source_known")
    series_ids = {
        "india_fpi_equity_net_flow_inr_cr": "fpi",
        "india_dii_equity_net_flow_inr_cr": "dii",
        "india_mf_sip_contribution_inr_cr": "sip",
        "india_nifty50_close_level": "returns",
    }
    rows = {}
    try:
        with Session(DB) as session:
            for indicator_id, key in series_ids.items():
                rows[key] = observations_at(session, indicator_id, when, vintage_mode, DEMO)
                if key == "returns" and not rows[key]:
                    rows[key] = _market_close_rows(session, when, vintage_mode)
    except Exception:
        rows = {}
    has_flows = bool(rows.get("fpi")) and bool(rows.get("dii"))
    if not has_flows:
        return {
            "as_of": when.isoformat(),
            "state": "data_unavailable",
            "vintage_mode": vintage_mode,
            "reason": "No attributable FPI/DII flow observations known at the evaluation time; investigation requires actual observations from exchange or AMFI releases.",
            "required_series": sorted(series_ids),
            "limitation": "Descriptive co-occurrence only; flows data carries no actor motivation. No feedback loop or absorption capacity is established."
        }

    def to_record(obs, series):
        return CapitalFlowRecord(
            series=series, period_end=obs.period_end, value=obs.value,
            revision=obs.vintage_id or "v1", published_at=obs.published_at,
            retrieved_at=obs.ingested_at or obs.published_at or when,
            source_name=obs.provider or "unknown", source_reference=obs.source_url or "",
            quality=obs.quality or "secondary",
            flow_basis="gross" if series == "india_mf_sip_contribution_inr_cr" else "net",
            definition_note="stored observation",
        )

    # Stored index closes are levels, not returns: month-over-month percent
    # changes are derived explicitly so scoring never sums index points.
    close_records = [to_record(o, "india_nifty50_close_level") for o in rows["returns"]]
    return_records = monthly_returns_from_closes(close_records)
    result = evaluate(
        [to_record(o, "india_fpi_equity_net_flow_inr_cr") for o in rows["fpi"]],
        [to_record(o, "india_dii_equity_net_flow_inr_cr") for o in rows["dii"]],
        [to_record(o, "india_mf_sip_contribution_inr_cr") for o in rows["sip"]],
        return_records,
        when,
    )

    return {"as_of": when.isoformat(), "state": "investigation_available", "vintage_mode": vintage_mode, **result}


REFLEXIVITY_RANGES = {"1m": timedelta(days=31), "3m": timedelta(days=93), "since_april": date(2026, 4, 1)}


def _reflexivity_series(session, when, selected_range, vintage_mode):
    """Read-only historical series for the reflexivity charts, point-in-time.

    Every row preserves the stored date, unit basis and provider attribution.
    Missing observations are nulls, never interpolated or zero-filled.
    """
    from packages.connectors.india_capital_flows import FPI as FPI_ID, DII as DII_ID, SIP as SIP_ID
    fixed_start = REFLEXIVITY_RANGES.get(selected_range)
    start_day = fixed_start if isinstance(fixed_start, date) else when.date() - fixed_start
    by_day = {}
    for indicator_id, series_key in ((FPI_ID, "fpi"), (DII_ID, "dii")):
        for obs in observations_at(session, indicator_id, when, vintage_mode, DEMO):
            if obs.period_end < start_day:
                continue
            row = by_day.setdefault(obs.period_end, {})
            row[series_key] = float(obs.value)
            row[f"{series_key}_provider"] = obs.provider or "unknown"
    flows = []
    for day in sorted(by_day):
        row = by_day[day]
        entry = {"date": day.isoformat(), "fpi_net": row.get("fpi"), "dii_net": row.get("dii"),
                 "fpi_roll5": None, "dii_roll5": None,
                 "fpi_provider": row.get("fpi_provider"), "dii_provider": row.get("dii_provider")}
        for series_key, roll_key in (("fpi", "fpi_roll5"), ("dii", "dii_roll5")):
            session_values = [(d, by_day[d][series_key]) for d in sorted(by_day) if by_day[d].get(series_key) is not None]
            position = next((i for i, (d, _) in enumerate(session_values) if d == day), None)
            if position is not None and position >= 4:
                entry[roll_key] = round(sum(value for _, value in session_values[position - 4:position + 1]), 2)
        flows.append(entry)
    closes = observations_at(session, "india_nifty50_close_level", when, vintage_mode, DEMO)
    if closes:
        closes = [row for row in closes if row.period_end >= start_day]
    else:
        closes = [row for row in _market_close_rows(session, when, vintage_mode) if row.period_end >= start_day]
    nifty = []
    if closes:
        first = float(closes[0].value)
        for row in closes:
            nifty.append({"date": row.period_end.isoformat(), "close": float(row.value),
                          "normalized": round(float(row.value) / first * 100, 4), "provider": row.provider})
    sip = []
    sip_rows = [row for row in observations_at(session, SIP_ID, when, vintage_mode, DEMO) if row.period_end >= start_day]
    for position, row in enumerate(sip_rows):
        growth = None
        if position and sip_rows[position - 1].period_end.month != 12:
            prior = sip_rows[position - 1].period_end
            if prior.year == row.period_end.year and prior.month + 1 == row.period_end.month:
                previous = float(sip_rows[position - 1].value)
                if previous:
                    growth = round((float(row.value) / previous - 1) * 100, 2)
        sip.append({"period_end": row.period_end.isoformat(), "value": float(row.value),
                    "unit": "INR crore", "provider": row.provider or "unknown", "mom_growth_pct": growth})
    return {"range": selected_range, "start": start_day.isoformat(), "flows": flows, "nifty": nifty, "sip": sip}


@app.get("/api/v1/research/reflexivity-cycle")
def reflexivity_cycle(as_of: str | None = None, range: str = "since_april", vintage_mode: str = "system_known", operator=Depends(research_reader)):
    """Cycle-centric research view: domestic equity flows and market reflexivity.

    Composes the existing capital-flow investigation into five research
    sections: current observations, the proposed feedback hypothesis,
    supporting/contradictory/insufficient evidence, inflection conditions to
    monitor, and conditional 1-3 and 3-6 month implications. Descriptive
    only; never a price target, probability or buy/sell signal.
    """
    from packages.scoring.reflexivity_cycle import (
        DAILY_STALE_DAYS, MONTHLY_STALE_DAYS, reflexivity_cycle_view, unavailable_view,
    )
    from packages.connectors.india_capital_flows import CapitalFlowRecord, monthly_returns_from_closes
    from packages.domain.store import observations_at

    when = parsed_as_of(as_of)
    if vintage_mode not in {"system_known", "source_known"}:
        raise HTTPException(422, "vintage_mode must be system_known or source_known")
    if range not in REFLEXIVITY_RANGES:
        raise HTTPException(422, "range must be 1m, 3m or since_april")
    series_ids = {
        "india_fpi_equity_net_flow_inr_cr": "fpi",
        "india_dii_equity_net_flow_inr_cr": "dii",
        "india_mf_sip_contribution_inr_cr": "sip",
        "india_nifty50_close_level": "returns",
    }
    stale_after = {"fpi": DAILY_STALE_DAYS, "dii": DAILY_STALE_DAYS, "sip": MONTHLY_STALE_DAYS, "returns": DAILY_STALE_DAYS}
    labels = {"fpi": "FPI equity flows", "dii": "DII equity flows", "sip": "SIP contributions", "returns": "Nifty closes"}
    units = {"fpi": "INR crore", "dii": "INR crore", "sip": "INR crore", "returns": "index points"}
    summaries = {}
    series = {"range": range, "flows": [], "nifty": [], "sip": []}
    try:
        with Session(DB) as session:
            fixed_start = REFLEXIVITY_RANGES.get(range)
            start_day = fixed_start if isinstance(fixed_start, date) else when.date() - fixed_start
            series = _reflexivity_series(session, when, range, vintage_mode)
            for indicator_id, key in series_ids.items():
                obs = observations_at(session, indicator_id, when, vintage_mode, DEMO)
                if key == "returns" and not obs:
                    obs = _market_close_rows(session, when, vintage_mode)
                if not obs:
                    summaries[key] = {"indicator_id": indicator_id, "label": labels[key], "unit": units[key], "status": "missing"}
                    continue
                last = obs[-1]
                days_behind = (when.date() - last.period_end).days
                summaries[key] = {
                    "indicator_id": indicator_id, "label": labels[key], "unit": units[key],
                    "status": "stale" if days_behind > stale_after[key] else "current",
                    "latest_period_end": last.period_end.isoformat(),
                    "value": float(last.value),
                    "days_behind_as_of": days_behind,
                    "observation_count": len(obs),
                }
            closes = observations_at(session, "india_nifty50_close_level", when, vintage_mode, DEMO)
            if not closes:
                closes = _market_close_rows(session, when, vintage_mode)
            if len(closes) >= 2:
                close_records = [CapitalFlowRecord(
                    series="india_nifty50_close_level", period_end=o.period_end, value=o.value,
                    revision=o.vintage_id or "v1", published_at=o.published_at,
                    retrieved_at=o.ingested_at or when, source_name=o.provider or "unknown",
                    source_reference=o.source_url or "", quality=o.quality or "secondary",
                    flow_basis="net", definition_note="stored observation",
                ) for o in closes]
                derived = monthly_returns_from_closes(close_records)
                if derived:
                    summaries["returns"]["latest_monthly_return_pct"] = float(derived[-1].value)
                    summaries["returns"]["latest_monthly_return_period_end"] = derived[-1].period_end.isoformat()
    except Exception:
        summaries = {}
        series = {"range": range, "flows": [], "nifty": [], "sip": []}

    snapshot = capital_flows(as_of=as_of, vintage_mode=vintage_mode, operator=operator)
    if snapshot.get("state") != "investigation_available":
        view = unavailable_view(snapshot.get("reason"), summaries, when)
        view["series"] = series
        return view
    view = reflexivity_cycle_view(snapshot, summaries)
    view["vintage_mode"] = vintage_mode
    view["series"] = series
    return view
