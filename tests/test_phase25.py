from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
import time
import httpx
import pytest
import yaml
from sqlalchemy import create_engine, select
from packages.domain.models import AdminAudit, AlertEvaluation, AlertTransition, IngestionRun, Observation, OperatorCredential, RateLimitCounter
from packages.domain.security import DatabaseRateLimiter, RateLimitStoreUnavailable, authorize_token, client_identity
from packages.domain.settings import token_digest
from packages.jobs.operators import issue, revoke
from packages.scoring.engine_v2 import data_confidence, history_contiguous
from packages.scoring.inflections import evaluate_v2, persist_transitions


def test_scoped_operator_expiry_and_revocation(db, monkeypatch):
    monkeypatch.setenv("APP_ENV", "development")
    token = issue(db, "analyst-a", {"imports:write"}, 30, "unit-test-operator-token")
    assert authorize_token(db, token, "imports:write")["operator_id"] == "analyst-a"
    with pytest.raises(Exception):
        authorize_token(db, token, "ingestion:run")
    assert revoke(db, token_digest(token)) is True
    with pytest.raises(Exception):
        authorize_token(db, token, "imports:write")
    assert revoke(db, token_digest(token)) is False
    assert db.scalar(select(OperatorCredential).where(OperatorCredential.operator_id == "analyst-a")).revoked_at is not None


def test_staging_rejects_legacy_shared_token_and_health_excludes_secrets(db, monkeypatch):
    from packages.domain.settings import settings
    from fastapi.testclient import TestClient
    import apps.api.main as api
    monkeypatch.setenv("APP_ENV", "staging")
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///isolated-staging-test.db")
    monkeypatch.setenv("ADMIN_TOKEN_SHA256", token_digest("legacy-test-token"))
    monkeypatch.delenv("OPERATOR_AUTH_MODE", raising=False)
    with pytest.raises(ValueError):
        settings()
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "db")
    assert settings().environment == "staging"
    with pytest.raises(Exception):
        authorize_token(db, "legacy-test-token", "imports:write", legacy=True)
    client = TestClient(api.app)
    response = client.get("/api/v1/health")
    assert response.status_code == 200
    assert "token" not in str(response.json()).lower()
    assert "database" not in str(response.json()).lower()


def test_trusted_proxy_does_not_accept_spoofed_headers():
    cidrs = ("172.30.51.10/32",)
    assert client_identity("203.0.113.5", "192.0.2.10", cidrs) == "203.0.113.5"
    assert client_identity("172.30.51.10", "192.0.2.10", cidrs) == "192.0.2.10"
    assert client_identity("172.30.51.11", "192.0.2.10", cidrs) == "172.30.51.11"
    assert client_identity("172.30.51.10", "not-an-ip", cidrs) == "172.30.51.10"
    assert client_identity("127.0.0.1", "192.0.2.10", cidrs) == "127.0.0.1"
    assert client_identity("172.30.51.10", "192.0.2.10, 203.0.113.9", cidrs) == "172.30.51.10"


def test_database_rate_limit_is_shared_across_instances(db):
    first, second = DatabaseRateLimiter(db.bind), DatabaseRateLimiter(db.bind)
    assert first.allow("same-client", 2)
    assert second.allow("same-client", 2)
    assert not first.allow("same-client", 2)
    assert second.allow("different-client", 2)


def test_database_rate_limit_concurrency_cleanup_and_fail_closed(tmp_path):
    engine = create_engine(f"sqlite:///{tmp_path / 'rate-test.db'}", connect_args={"timeout": 30})
    RateLimitCounter.__table__.create(engine)
    limiter = DatabaseRateLimiter(engine)
    with ThreadPoolExecutor(max_workers=8) as pool:
        allowed = list(pool.map(lambda _: limiter.allow("concurrent-client", 20), range(60)))
    assert sum(allowed) == 20
    assert not limiter.allow("concurrent-client", 20)
    old = int(time.time()) - 7200
    with engine.begin() as connection:
        connection.execute(RateLimitCounter.__table__.insert().values(key="old", window_start=old, count=1))
    assert limiter.prune(retention_seconds=3600) == 1
    assert not limiter.allow("concurrent-client", 20)
    engine.dispose()

    unavailable = DatabaseRateLimiter(create_engine("sqlite://"))
    with pytest.raises(RateLimitStoreUnavailable):
        unavailable.allow("test", 1)
    with pytest.raises(RateLimitStoreUnavailable):
        unavailable.prune()


def test_rate_load_script_cannot_target_production():
    from scripts.staging_rate_load import run
    with pytest.raises(ValueError):
        run("https://smarthedge.in")


def test_rate_store_failure_rejects_http_before_handler(monkeypatch):
    from fastapi.testclient import TestClient
    import apps.api.main as api
    class FailedStore:
        def allow(self, *args):
            raise RateLimitStoreUnavailable("internal database detail")
    monkeypatch.setattr(api, "LIMITER", FailedStore())
    response = TestClient(api.app).get("/api/v1/health")
    assert response.status_code == 503
    assert response.json()["error"]["message"] == "Request admission unavailable"
    assert "internal database detail" not in response.text


def test_data_confidence_is_distinct_and_demo_unscored():
    metrics = [{"status": "verified", "scored_feature": 4.0, "provider": "official", "ingested_at": "2026-10-30T00:00:00+00:00"},
               {"status": "stale", "scored_feature": None, "provider": "official", "ingested_at": "2026-09-01T00:00:00+00:00"},
               {"status": "DATA_UNAVAILABLE", "scored_feature": None, "provider": None, "ingested_at": None}]
    score = data_confidence(metrics, 0.25, False)
    assert 0 < score["score"] < 50
    assert "Operational coverage/quality index" in score["reason"]
    assert "not statistical certainty" in score["reason"]
    assert score["source_backed_count"] == 1
    assert data_confidence(metrics, 0.25, True)["score"] is None
    assert data_confidence(metrics[1:], 0, False)["score"] == 0


def test_cycle_history_is_point_in_time_and_nullable(db):
    from packages.scoring.engine_v2 import compute_v2
    as_of = datetime(2026, 10, 30, tzinfo=timezone.utc)
    result = compute_v2(db, as_of, demo=False)
    for cycle in result["cycles"]:
        assert [point["score"] for point in cycle["history"]] == [None, None, None]
        assert [datetime.fromisoformat(point["as_of"]) for point in cycle["history"]] == [as_of - timedelta(days=56), as_of - timedelta(days=28), as_of]


def test_discontinuous_monthly_history_cannot_form_change_signal():
    from types import SimpleNamespace
    rows = [SimpleNamespace(period_end=date(2026, month, 28)) for month in (1, 2, 4)]
    assert history_contiguous(rows, {"frequency": "monthly"}, "change_pct_2", "sip_contribution_inr") is False
    rows[2].period_end = date(2026, 3, 28)
    assert history_contiguous(rows, {"frequency": "monthly"}, "change_pct_2", "sip_contribution_inr") is True


def test_treasury_retries_transient_timeout(monkeypatch):
    from packages.connectors import treasury
    monkeypatch.setattr(treasury.clock, "sleep", lambda _: None)
    xml = b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"><entry><content><d:NEW_DATE>2026-10-29T00:00:00</d:NEW_DATE><d:BC_10YEAR>4.25</d:BC_10YEAR></content></entry></feed>'
    class Client:
        calls = 0
        def get(self, url):
            self.calls += 1
            if self.calls == 1:
                raise httpx.ReadTimeout("transient")
            return httpx.Response(200, content=xml, request=httpx.Request("GET", url))
    client = Client()
    raw, rows = treasury.TreasuryAdapter(client).fetch(datetime(2026, 10, 31, tzinfo=timezone.utc))
    assert client.calls == 2 and raw == xml and len(rows) == 1
    assert rows[0].published_at.date() >= rows[0].period_end


def test_unentitled_source_adapters_fail_closed():
    from packages.connectors.catalog import adapter_for
    from packages.connectors.base import DataUnavailable
    for provider in ("rbi", "nsdl", "amfi", "mospi", "licensed_market"):
        with pytest.raises(DataUnavailable):
            adapter_for(provider).fetch(datetime.now(timezone.utc))


def test_scheduler_idempotence_and_failure_audit(db, monkeypatch):
    from packages.jobs import scheduler
    from decimal import Decimal
    from packages.connectors.base import SourceObservation
    monkeypatch.setattr(scheduler, "evaluate_v2", lambda *args: [])
    row = SourceObservation("us_10y_yield", Decimal("4.25"), "pct", date(2026, 10, 29), date(2026, 10, 29), datetime(2026, 10, 30, tzinfo=timezone.utc), "us_treasury", "https://home.treasury.gov/example", "fixture-20261029")
    class Good:
        provider = "us_treasury"
        def fetch(self, as_of):
            return b"official-test-snapshot", [row]
    now = datetime.now(timezone.utc)
    assert scheduler.run_once(db, Good(), now)["inserted"] == 1
    assert scheduler.run_once(db, Good(), now)["duplicate"] == 1
    class Bad:
        provider = "us_treasury"
        def fetch(self, as_of):
            raise httpx.ReadTimeout("source unavailable")
    with pytest.raises(httpx.ReadTimeout):
        scheduler.run_once(db, Bad(), now)
    assert db.scalar(select(IngestionRun).where(IngestionRun.status == "failed")) is not None
    assert db.scalar(select(AdminAudit).where(AdminAudit.result == "failed")) is not None


def test_alert_evaluation_checkpoint_extends_across_years(db, monkeypatch):
    import packages.scoring.inflections as inflections
    rule = inflections.rules("v2")["alerts"][0]
    monkeypatch.setattr(inflections, "rules", lambda version: {"alerts": [rule]})
    start = datetime(2024, 1, 1, tzinfo=timezone.utc)
    as_of = start + timedelta(days=600)
    for n in range(530):
        db.add(AlertEvaluation(rule_id=rule["id"], ruleset_version="v2", mode="live", event_at=start + timedelta(days=n), recorded_at=start + timedelta(days=n, hours=1), known=4, triggered=4, evidence_json="[]"))
    db.commit()
    monkeypatch.setattr(inflections, "_times", lambda *args: [start + timedelta(days=n) for n in range(530, 535)])
    monkeypatch.setattr(inflections, "_core", lambda *args: {"metrics": [{"id": id, "scored_feature": None, "published_at": None, "period_end": None, "provider": None, "quality": None, "status": "DATA_UNAVAILABLE"} for id in rule["conditions"]]})
    alerts = evaluate_v2(db, as_of, demo=False)
    assert alerts[0]["status"] == "CONFIRMED"
    assert persist_transitions(db, alerts, as_of) == 1
    assert persist_transitions(db, alerts, as_of) == 0
    assert db.query(AlertEvaluation).count() == 535
    assert evaluate_v2(db, as_of, demo=False)[0]["status"] == "CONFIRMED"


def test_checkpoint_replay_excludes_future_recorded_events(db, monkeypatch):
    import packages.scoring.inflections as inflections
    rule = inflections.rules("v2")["alerts"][0]
    monkeypatch.setattr(inflections, "rules", lambda version: {"alerts": [rule]})
    start = datetime(2026, 1, 1, tzinfo=timezone.utc)
    as_of = start + timedelta(days=20)
    for n in range(5):
        db.add(AlertEvaluation(rule_id=rule["id"], ruleset_version="v2", mode="live", event_at=start + timedelta(days=n), recorded_at=as_of + timedelta(days=1), known=4, triggered=4, evidence_json="[]"))
    db.commit()
    monkeypatch.setattr(inflections, "_times", lambda *args: [start + timedelta(days=10)])
    monkeypatch.setattr(inflections, "_core", lambda *args: {"metrics": [{"id": id, "scored_feature": None, "published_at": None, "period_end": None, "provider": None, "quality": None, "status": "DATA_UNAVAILABLE"} for id in rule["conditions"]]})
    assert evaluate_v2(db, as_of, demo=False)[0]["status"] == "UNKNOWN"


def test_multi_year_checkpoint_late_ingestion_and_revision_are_point_in_time(db, monkeypatch):
    import packages.scoring.inflections as inflections
    from packages.domain.store import observations_at
    from packages.jobs.sync_registry import sync_registry
    sync_registry(db)
    rule = {"id": "UNIT_FX", "label": "Unit test FX", "min_known": 1, "watch_count": 1, "trigger_count": 1, "confirm_count": 1,
            "watch_days": 2, "trigger_days": 2, "confirm_days": 2, "recovery_days": 2,
            "conditions": {"usd_inr_spot": {"op": "gte", "value": 80}}}
    monkeypatch.setattr(inflections, "rules", lambda version: {"alerts": [rule]})
    old = datetime(2024, 1, 1, tzinfo=timezone.utc)
    for n in range(5):
        db.add(AlertEvaluation(rule_id=rule["id"], ruleset_version="v2", mode="live", event_at=old + timedelta(days=n), recorded_at=old + timedelta(days=n, hours=1), known=1, triggered=1, evidence_json="[]"))
    t_late = datetime(2026, 10, 28, 12, tzinfo=timezone.utc)
    t_original = datetime(2026, 10, 30, 12, tzinfo=timezone.utc)
    t_revision = datetime(2026, 11, 2, 12, tzinfo=timezone.utc)
    db.add(Observation(indicator_id="usd_inr_spot", period_start=date(2026, 10, 27), period_end=date(2026, 10, 27), value=Decimal("81"), unit="INR_per_USD", published_at=t_late - timedelta(hours=1), ingested_at=t_original, provider="unit_fixture", source_url="https://example.org/late", vintage_id="late-v1", quality="verified", is_revision=False, is_demo=False))
    db.add(Observation(indicator_id="usd_inr_spot", period_start=date(2026, 10, 30), period_end=date(2026, 10, 30), value=Decimal("82"), unit="INR_per_USD", published_at=t_original - timedelta(hours=1), ingested_at=t_original, provider="unit_fixture", source_url="https://example.org/original", vintage_id="v1", quality="verified", is_revision=False, is_demo=False))
    db.add(Observation(indicator_id="usd_inr_spot", period_start=date(2026, 10, 30), period_end=date(2026, 10, 30), value=Decimal("79"), unit="INR_per_USD", published_at=t_revision - timedelta(hours=1), ingested_at=t_revision, provider="unit_fixture", source_url="https://example.org/revision", vintage_id="v2", quality="revised", is_revision=True, is_demo=False))
    db.commit()

    monkeypatch.setattr(inflections, "_times", lambda session, rule, as_of, demo, mode: [t for t in (t_late, t_original, t_revision) if t <= as_of])
    def metrics(session, instant, demo, mode):
        rows = observations_at(session, "usd_inr_spot", instant, mode, demo)
        row = rows[-1] if rows else None
        return {"metrics": [{"id": "usd_inr_spot", "scored_feature": float(row.value) if row else None,
                             "published_at": row.published_at.isoformat() if row else None,
                             "period_end": row.period_end.isoformat() if row else None,
                             "provider": row.provider if row else None,
                             "quality": row.quality if row else None,
                             "status": row.quality if row else "DATA_UNAVAILABLE"}]}
    monkeypatch.setattr(inflections, "_core", metrics)
    before = evaluate_v2(db, t_original, demo=False)[0]
    assert before["status"] == "CONFIRMED"
    assert before["_evaluations"][0]["known"] == 0  # late arrival was not known on 28 October
    assert before["evidence"][0]["observed"] == 82
    assert persist_transitions(db, [before], t_original) == 1
    original_event = db.get(AlertEvaluation, (rule["id"], "v2", "live", t_original))
    original_evidence = original_event.evidence_json

    after = evaluate_v2(db, t_revision, demo=False)[0]
    assert after["status"] == "CONFIRMED"
    assert after["recovery_count"] == 1
    assert after["evidence"][0]["observed"] == 79
    assert persist_transitions(db, [after], t_revision) == 0
    db.expire_all()
    assert db.get(AlertEvaluation, (rule["id"], "v2", "live", t_original)).evidence_json == original_evidence
    assert db.query(AlertTransition).filter(AlertTransition.rule_id == rule["id"]).count() == 1
    assert evaluate_v2(db, t_original, demo=False)[0]["evidence"][0]["observed"] == 82


def test_staging_compose_is_isolated_and_admin_not_public():
    root = Path(__file__).resolve().parents[1]
    compose = yaml.safe_load((root / "docker-compose.staging.yml").read_text())
    assert compose["name"] == "smarthedge-staging"
    assert "staging_pgdata" in compose["volumes"]
    assert compose["services"]["api"]["environment"]["TRUSTED_PROXY_CIDRS"] == "172.30.51.10/32"
    assert compose["services"]["caddy"]["networks"]["staging"]["ipv4_address"] == "172.30.51.10"
    assert all(port.startswith("127.0.0.1:") for service in compose["services"].values() for port in service.get("ports", []))
    caddy = (root / "Caddyfile.staging").read_text()
    assert "handle @admin" in caddy and "respond 403" in caddy
