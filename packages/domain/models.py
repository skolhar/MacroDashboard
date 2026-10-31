from datetime import date, datetime, timezone
from decimal import Decimal
from sqlalchemy import Boolean, Date, DateTime, ForeignKey, Integer, Numeric, String, Text, UniqueConstraint
from sqlalchemy.types import TypeDecorator
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class UTCDateTime(TypeDecorator):
    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value, dialect):
        if value is None:
            return None
        if value.tzinfo is None:
            raise ValueError("Timestamp requires timezone")
        return value.astimezone(timezone.utc)

    def process_result_value(self, value, dialect):
        if value is None:
            return None
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


class IndicatorDefinition(Base):
    __tablename__ = "indicator_definitions"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    display_name: Mapped[str] = mapped_column(String(150))
    cycle: Mapped[str] = mapped_column(String(30))
    unit: Mapped[str] = mapped_column(String(40))
    frequency: Mapped[str] = mapped_column(String(40))
    direction_of_stress: Mapped[str] = mapped_column(String(30))
    max_age_hours: Mapped[int] = mapped_column(Integer)
    publication_lag_days: Mapped[int] = mapped_column(Integer)
    transform: Mapped[str] = mapped_column(String(50))
    required_for_score: Mapped[bool] = mapped_column(Boolean)
    source_priority: Mapped[str] = mapped_column(Text)


class Observation(Base):
    __tablename__ = "observations"
    __table_args__ = (UniqueConstraint("indicator_id", "period_start", "period_end", "provider", "vintage_id"),)
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    indicator_id: Mapped[str] = mapped_column(ForeignKey("indicator_definitions.id"), index=True)
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    value: Mapped[Decimal] = mapped_column(Numeric(24, 8))
    unit: Mapped[str] = mapped_column(String(40))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime, index=True)
    ingested_at: Mapped[datetime] = mapped_column(UTCDateTime)
    provider: Mapped[str] = mapped_column(String(100))
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    vintage_id: Mapped[str] = mapped_column(String(100))
    quality: Mapped[str] = mapped_column(String(30))
    is_revision: Mapped[bool] = mapped_column(Boolean, default=False)
    is_demo: Mapped[bool] = mapped_column(Boolean, default=False, server_default="false")
    source_identifier: Mapped[str | None] = mapped_column(String(100), nullable=True)
    source_reference: Mapped[str | None] = mapped_column(Text, nullable=True)
    content_hash: Mapped[str | None] = mapped_column(String(64), nullable=True)
    release_review_id: Mapped[int | None] = mapped_column(ForeignKey("source_release_reviews.id"), nullable=True, index=True)
    rate_kind: Mapped[str | None] = mapped_column(String(60), nullable=True)


class RawSnapshot(Base):
    __tablename__ = "raw_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(100))
    content_hash: Mapped[str] = mapped_column(String(64), unique=True)
    received_at: Mapped[datetime] = mapped_column(UTCDateTime)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)


class SourceReleaseReview(Base):
    """Durable human review of one original publisher release and normalized extract."""
    __tablename__ = "source_release_reviews"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    provider: Mapped[str] = mapped_column(String(100))
    source_reference: Mapped[str] = mapped_column(Text)
    original_archive_reference: Mapped[str] = mapped_column(Text)
    source_sha256: Mapped[str] = mapped_column(String(64))
    extract_sha256: Mapped[str] = mapped_column(String(64))
    published_at: Mapped[datetime] = mapped_column(UTCDateTime)
    publication_evidence_url: Mapped[str] = mapped_column(Text)
    publication_evidence_note: Mapped[str] = mapped_column(Text)
    entitlement_basis: Mapped[str] = mapped_column(String(40))
    entitlement_reference: Mapped[str] = mapped_column(Text)
    definition_version: Mapped[str] = mapped_column(String(80))
    submitted_by: Mapped[str] = mapped_column(String(100))
    submitted_at: Mapped[datetime] = mapped_column(UTCDateTime)
    status: Mapped[str] = mapped_column(String(20))
    approved_by: Mapped[str | None] = mapped_column(String(100), nullable=True)
    approved_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    review_note: Mapped[str | None] = mapped_column(Text, nullable=True)


class ScoreSnapshot(Base):
    __tablename__ = "score_snapshots"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    as_of: Mapped[datetime] = mapped_column(UTCDateTime)
    ruleset_version: Mapped[str] = mapped_column(String(40))
    total_score: Mapped[Decimal | None] = mapped_column(Numeric(6, 2), nullable=True)
    coverage: Mapped[Decimal] = mapped_column(Numeric(5, 4))
    payload_json: Mapped[str] = mapped_column(Text)


class AlertEvent(Base):
    __tablename__ = "alert_events"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(100))
    ruleset_version: Mapped[str] = mapped_column(String(40))
    status: Mapped[str] = mapped_column(String(30))
    severity: Mapped[str | None] = mapped_column(String(30), nullable=True)
    start_at: Mapped[datetime] = mapped_column(UTCDateTime)
    end_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    fired_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    confirmed_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    evidence_json: Mapped[str] = mapped_column(Text)
    deduplication_key: Mapped[str] = mapped_column(String(200), unique=True)
    acknowledged_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class PolicyEvent(Base):
    __tablename__ = "policy_events"
    id: Mapped[str] = mapped_column(String(100), primary_key=True)
    event_at: Mapped[datetime] = mapped_column(UTCDateTime)
    type: Mapped[str] = mapped_column(String(60))
    description: Mapped[str] = mapped_column(Text)
    source_url: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(20))
    affected_indicators_json: Mapped[str] = mapped_column(Text)


class IngestionRun(Base):
    __tablename__ = "ingestion_runs"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    provider: Mapped[str] = mapped_column(String(100))
    started_at: Mapped[datetime] = mapped_column(UTCDateTime)
    finished_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)
    status: Mapped[str] = mapped_column(String(30))
    item_count: Mapped[int] = mapped_column(Integer, default=0)
    error_code: Mapped[str | None] = mapped_column(String(100), nullable=True)


class AlertTransition(Base):
    __tablename__ = "alert_transitions"
    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    rule_id: Mapped[str] = mapped_column(String(100), index=True)
    ruleset_version: Mapped[str] = mapped_column(String(40))
    market: Mapped[str] = mapped_column(String(20))
    mode: Mapped[str] = mapped_column(String(20))
    status: Mapped[str] = mapped_column(String(30))
    evaluated_at: Mapped[datetime] = mapped_column(UTCDateTime)
    evidence_json: Mapped[str] = mapped_column(Text)
    deduplication_key: Mapped[str] = mapped_column(String(200), unique=True)


class OperatorCredential(Base):
    __tablename__ = "operator_credentials"
    token_hash: Mapped[str] = mapped_column(String(64), primary_key=True)
    operator_id: Mapped[str] = mapped_column(String(100), index=True)
    scopes: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(UTCDateTime)
    expires_at: Mapped[datetime] = mapped_column(UTCDateTime)
    revoked_at: Mapped[datetime | None] = mapped_column(UTCDateTime, nullable=True)


class AdminAudit(Base):
    __tablename__ = "admin_audit"
    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    operator_id: Mapped[str] = mapped_column(String(100), index=True)
    action: Mapped[str] = mapped_column(String(80))
    result: Mapped[str] = mapped_column(String(30))
    at: Mapped[datetime] = mapped_column(UTCDateTime)
    details: Mapped[str] = mapped_column(Text)


class RateLimitCounter(Base):
    __tablename__ = "rate_limit_counters"
    key: Mapped[str] = mapped_column(String(160), primary_key=True)
    window_start: Mapped[int] = mapped_column(Integer, primary_key=True)
    count: Mapped[int] = mapped_column(Integer)


class AlertEvaluation(Base):
    """Immutable point-in-time alert input, keyed by session or release event."""
    __tablename__ = "alert_evaluations"
    rule_id: Mapped[str] = mapped_column(String(100), primary_key=True)
    ruleset_version: Mapped[str] = mapped_column(String(40), primary_key=True)
    mode: Mapped[str] = mapped_column(String(20), primary_key=True)
    event_at: Mapped[datetime] = mapped_column(UTCDateTime, primary_key=True)
    recorded_at: Mapped[datetime] = mapped_column(UTCDateTime)
    known: Mapped[int] = mapped_column(Integer)
    triggered: Mapped[int] = mapped_column(Integer)
    evidence_json: Mapped[str] = mapped_column(Text)
