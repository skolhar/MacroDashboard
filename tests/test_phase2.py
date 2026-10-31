from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select
from packages.connectors.base import DataUnavailable, SourceObservation, UnavailableAdapter
from packages.connectors.manual import parse_manual_csv
from packages.connectors.treasury import parse_treasury_xml
from packages.domain.calendar import is_session, market_for, recent_sessions
from packages.domain.calendar import sessions_between
from packages.domain.config import registry, rules
from packages.domain.models import Observation
from packages.domain.settings import settings
from packages.domain.store import observations_at
from packages.jobs.ingest import ingest_records
from packages.jobs.sync_registry import sync_registry
from packages.scoring.engine_v2 import compute_v2
from packages.scoring.engine_v2 import _freshness, covered_weighted_score, composite_score
from packages.scoring.inflections import status_for_evaluations, persist_transitions


def record(value="7.4", quality="verified", vintage="a"):
    day = date(2026, 10, 29)
    return SourceObservation("us_10y_yield", Decimal(value), "pct", day, day, datetime(2026, 10, 30, tzinfo=timezone.utc), "us_treasury", "https://home.treasury.gov/example", vintage, quality)


def test_production_configuration_fails_closed(monkeypatch):
    monkeypatch.setenv("APP_ENV", "production")
    monkeypatch.setenv("DATABASE_URL", "sqlite:///./isolated.db")
    monkeypatch.setenv("DEMO_MODE", "true")
    try:
        settings()
        assert False, "production demo must fail"
    except ValueError:
        pass
    monkeypatch.setenv("DEMO_MODE", "false")
    monkeypatch.delenv("ADMIN_TOKEN_SHA256", raising=False)
    try:
        settings()
        assert False, "missing admin hash must fail"
    except ValueError:
        pass


def test_live_demo_isolation_and_vintage(db):
    sync_registry(db)
    raw = b"official test fixture"
    assert ingest_records(db, [record()], raw, "us_treasury")["inserted"] == 1
    assert ingest_records(db, [record()], raw, "us_treasury")["duplicate"] == 1
    as_of = datetime.now(timezone.utc)
    assert all(o.quality != "demo" for o in observations_at(db, "us_10y_yield", as_of, demo=False))
    assert all(o.quality == "demo" for o in observations_at(db, "us_10y_yield", as_of, demo=True))
    revised = replace(record(), value=Decimal("7.5"), vintage_id="b", published_at=datetime.now(timezone.utc) - timedelta(seconds=1))
    ingest_records(db, [revised], b"revised test fixture", "us_treasury")
    assert observations_at(db, "us_10y_yield", as_of, demo=False)[-1].value == Decimal("7.4")
    assert observations_at(db, "us_10y_yield", datetime.now(timezone.utc), demo=False)[-1].value == Decimal("7.5")


def test_ingestion_rejects_conflict_bad_units_and_missing_source(db):
    sync_registry(db)
    ingest_records(db, [record()], b"first", "us_treasury")
    for candidate in [replace(record(), value=Decimal("8")), replace(record(), unit="bps", vintage_id="b"), replace(record(), source_reference="", vintage_id="c")]:
        try:
            ingest_records(db, [candidate], b"different", "us_treasury")
            assert False, "invalid import must fail"
        except ValueError:
            db.rollback()


def test_outlier_remains_visible_but_unscored(db):
    sync_registry(db)
    ingest_records(db, [record()], b"normal series", "us_treasury")
    outlier = replace(record(), value=Decimal("30"), period_start=date(2026, 10, 30), period_end=date(2026, 10, 30), vintage_id="outlier")
    ingest_records(db, [outlier], b"outlier series", "us_treasury")
    result = compute_v2(db, datetime.now(timezone.utc), demo=False)
    metric = next(m for m in result["metrics"] if m["id"] == "us_10y_yield")
    assert metric["value"] == 30
    assert metric["status"] == "source_conflict"
    assert metric["scored_feature"] is None


def test_manual_csv_validation_and_unavailable_adapter():
    header = "indicator_id,value,unit,period_start,period_end,published_at,vintage_id,source_reference,quality\n"
    row = "us_10y_yield,7.4,pct,2026-10-29,2026-10-29,2026-10-30T00:00:00Z,v1,https://home.treasury.gov/example,verified\n"
    assert parse_manual_csv((header + row).encode(), "manual")[0].value == Decimal("7.4")
    try:
        parse_manual_csv((header + row.replace("v1", "=SUM(1,1)")).encode(), "manual")
        assert False
    except ValueError:
        pass
    try:
        UnavailableAdapter("licensed", ("brent_usd",), "license required").fetch(datetime.now(timezone.utc))
        assert False
    except DataUnavailable:
        pass


def test_treasury_parser_uses_conservative_publication_time():
    xml = b'<feed xmlns="http://www.w3.org/2005/Atom" xmlns:d="http://schemas.microsoft.com/ado/2007/08/dataservices"><entry><content><d:NEW_DATE>2026-10-29T00:00:00</d:NEW_DATE><d:BC_10YEAR>4.25</d:BC_10YEAR></content></entry></feed>'
    received = datetime(2026, 10, 30, tzinfo=timezone.utc)
    rows = parse_treasury_xml(xml, received, "https://home.treasury.gov/feed")
    assert len(rows) == 1
    assert rows[0].value == Decimal("4.25")
    assert rows[0].published_at == received


def test_treasury_timeout_has_no_fabricated_fallback():
    import httpx
    from packages.connectors.treasury import TreasuryAdapter
    class TimedOut:
        def get(self, url):
            raise httpx.ReadTimeout("source did not respond")
    try:
        TreasuryAdapter(TimedOut()).fetch(datetime.now(timezone.utc))
        assert False, "timeout must propagate"
    except httpx.ReadTimeout:
        pass


def test_v2_coverage_and_reproducibility(db):
    sync_registry(db)
    as_of = datetime(2026, 10, 30, 18, tzinfo=timezone.utc)
    first = compute_v2(db, as_of, demo=False)
    second = compute_v2(db, as_of, demo=False)
    assert first == second
    assert len(first["cycles"]) == 6
    assert first["overall"]["score"] is None
    assert first["overall"]["coverage"] == 0
    assert all(c["score"] is None for c in first["cycles"])
    demo_first = compute_v2(db, as_of, demo=True)
    demo_second = compute_v2(db, as_of, demo=True)
    assert demo_first == demo_second
    assert next(c for c in demo_first["cycles"] if c["id"] == "earnings")["score"] is not None


def test_partial_indicator_coverage_never_imputes_missing_risk_as_zero():
    score, coverage = covered_weighted_score([(80, 70), (None, 30)])
    assert (score, coverage) == (80, 0.7)
    cycles = [{"score": score, "weight": weight} for weight in (25, 20, 20, 20, 10, 5)]
    assert composite_score(cycles, 0.925) == 80
    cycles[4]["score"] = None
    assert composite_score(cycles, 0.825) is None
    assert covered_weighted_score([(80, 69), (None, 31)])[0] is None


def test_alert_persistence_and_hysteresis():
    rule = rules("v2")["alerts"][0]
    assert status_for_evaluations([(4, 2)], rule)[0] == "UNKNOWN"
    assert status_for_evaluations([(4, 2)] * 2, rule)[0] == "WATCH"
    assert status_for_evaluations([(4, 3)] * 3, rule)[0] == "TRIGGERED"
    assert status_for_evaluations([(4, 4)] * 5, rule)[0] == "CONFIRMED"
    assert status_for_evaluations([(4, 4)] * 5 + [(4, 0)] * 4, rule)[0] == "CONFIRMED"
    assert status_for_evaluations([(4, 4)] * 5 + [(4, 0)] * 5, rule)[0] == "RESOLVED"
    assert status_for_evaluations([(4, 3)] * 3 + [(0, 0)], rule)[0] == "TRIGGERED"


def test_long_alert_lifecycle_missing_publications_and_repeated_evaluation():
    rule = rules("v2")["alerts"][0]
    history = [(4, 4)] * 18 + [(4, 0)] * 4 + [(0, 0)] + [(4, 0)] * 4
    assert len(history) > 15
    assert status_for_evaluations(history, rule)[0] == "CONFIRMED"
    assert status_for_evaluations(history + [(4, 0)], rule)[0] == "RESOLVED"
    assert status_for_evaluations(history, rule) == status_for_evaluations(history, rule)


def test_alert_replay_uses_more_than_fifteen_sessions(monkeypatch):
    import packages.scoring.inflections as inflections
    from zoneinfo import ZoneInfo
    seen = []
    def sessions(as_of, market, count):
        seen.append(count)
        return [date(2026, 9, 1) + timedelta(days=n) for n in range(25)]
    monkeypatch.setattr(inflections, "recent_sessions", sessions)
    instants = inflections._times(None, rules("v2")["alerts"][0], datetime(2026, 10, 1, tzinfo=ZoneInfo("Asia/Kolkata")), False, "system_known")
    assert seen == [60]
    assert len(instants) == 25


def test_it_alert_requires_distinct_quarterly_releases():
    rule = rules("v2")["alerts"][-1]
    assert rule["cadence"] == "publication"
    assert "watch_days" not in rule
    assert status_for_evaluations([(4, 4)] * 2, rule)[0] == "WATCH"
    assert status_for_evaluations([(4, 4)] * 3, rule)[0] == "TRIGGERED"
    assert status_for_evaluations([(4, 4)] * 4, rule)[0] == "CONFIRMED"
    assert status_for_evaluations([(4, 4)] * 4 + [(4, 0)] * 2, rule)[0] == "RESOLVED"


def test_it_release_clock_ignores_revisions_and_daily_rechecks():
    import packages.scoring.inflections as inflections
    from types import SimpleNamespace
    rows = [SimpleNamespace(period_end=date(2026, 3, 31), published_at=datetime(2026, 5, 1, tzinfo=timezone.utc), ingested_at=datetime(2026, 5, 2, tzinfo=timezone.utc)),
            SimpleNamespace(period_end=date(2026, 3, 31), published_at=datetime(2026, 5, 5, tzinfo=timezone.utc), ingested_at=datetime(2026, 5, 6, tzinfo=timezone.utc)),
            SimpleNamespace(period_end=date(2026, 6, 30), published_at=datetime(2026, 8, 1, tzinfo=timezone.utc), ingested_at=datetime(2026, 8, 2, tzinfo=timezone.utc))]
    first = inflections.release_instants(rows, datetime(2026, 8, 3, tzinfo=timezone.utc), "system_known")
    later = inflections.release_instants(rows, datetime(2026, 8, 20, tzinfo=timezone.utc), "system_known")
    assert len(first) == len(later) == 2
    assert first == later
    assert first[0] == datetime(2026, 5, 2, 0, 1, tzinfo=timezone.utc)


def test_alert_history_deduplicates_and_records_version(db):
    now = datetime.now(timezone.utc)
    alert = {"rule_id": "RUPEE_STRESS", "ruleset_version": "v2", "demo": False, "status": "WATCH", "evidence": [{"indicator_id": "usd_inr_spot", "observed": 2.1}]}
    assert persist_transitions(db, [alert], now) == 1
    assert persist_transitions(db, [alert], now) == 0


def test_calendar_and_forward_sign_guard():
    assert is_session(date(2026, 10, 20), "india") is False
    assert is_session(date(2026, 2, 1), "india") is True
    assert is_session(date(2026, 11, 26), "us") is False
    assert is_session(date(2027, 1, 4), "india") is None
    assert is_session(date(2027, 3, 26), "us") is False
    assert is_session(date(2027, 10, 11), "us") is True
    assert is_session(date(2027, 10, 11), "us_treasury") is False
    assert is_session(date(2027, 12, 24), "us") is False
    assert market_for("us_10y_yield") == "us_treasury"
    assert recent_sessions(datetime(2027, 1, 4, tzinfo=timezone.utc), "india", 5) == []
    assert sessions_between(date(2026, 10, 19), date(2026, 10, 20), "india") == 0
    assert "rbi_net_forward_usd" not in rules("v2")["cycle_signals"]["fx"]
    assert registry(True)["rbi_net_forward_usd"]["direction_of_stress"] == "contextual"


def test_source_known_vs_system_known_and_stale_monthly(db):
    sync_registry(db)
    ingest_records(db, [record()], b"source-known test", "us_treasury")
    historical = datetime(2026, 10, 30, 1, tzinfo=timezone.utc)
    assert observations_at(db, "us_10y_yield", historical, demo=False) == []
    assert len(observations_at(db, "us_10y_yield", historical, mode="source_known", demo=False)) == 1
    monthly = db.scalar(select(Observation).where(Observation.indicator_id == "sip_contribution_inr").order_by(Observation.period_end.desc()))
    assert _freshness(monthly, registry(True)["sip_contribution_inr"], datetime(2027, 1, 31, tzinfo=timezone.utc), "sip_contribution_inr") == "stale"


def test_api_auth_and_live_mode_never_falls_back_to_demo(db, monkeypatch):
    import apps.api.main as api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setattr(api, "DEFAULT_RULESET", "v2")
    client = TestClient(api.app)
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert response.json()["mode"] == "live"
    assert response.json()["overall"]["coverage"] == 0
    assert client.post("/api/v1/admin/imports/csv").status_code == 401


def test_shared_admin_token_and_local_rate_limiter_limits(monkeypatch):
    from fastapi import HTTPException
    from packages.domain.security import RateLimiter, require_admin
    from packages.domain.settings import token_digest
    monkeypatch.setenv("ADMIN_TOKEN_SHA256", token_digest("test-operator-secret"))
    assert require_admin("test-operator-secret") == {"role": "admin"}
    for token in (None, "wrong-token"):
        try:
            require_admin(token)
            assert False, "invalid token accepted"
        except HTTPException as exc:
            assert exc.status_code == 401
    one, two = RateLimiter(), RateLimiter()
    assert one.allow("operator:write", 1)
    assert not one.allow("operator:write", 1)
    assert two.allow("operator:write", 1) # documents independent process state


def test_authenticated_manual_import_requires_license_attestation(db, monkeypatch):
    import apps.api.main as api
    from fastapi.testclient import TestClient
    from packages.domain.settings import token_digest
    sync_registry(db)
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setenv("ADMIN_TOKEN_SHA256", token_digest("test-admin-only"))
    client = TestClient(api.app)
    csv_data = ("indicator_id,value,unit,period_start,period_end,published_at,vintage_id,source_reference,quality\n"
                "us_10y_yield,7.4,pct,2026-10-29,2026-10-29,2026-10-30T00:00:00Z,manual-1,https://home.treasury.gov/example,verified\n")
    headers = {"X-Admin-Token": "test-admin-only", "X-Source-Provider": "manual_review", "Content-Type": "text/csv"}
    assert client.post("/api/v1/admin/imports/csv", content=csv_data, headers=headers).status_code == 422
    headers["X-License-Attestation"] = "public-redistributable"
    response = client.post("/api/v1/admin/imports/csv", content=csv_data, headers=headers)
    assert response.status_code == 200
    assert response.json()["inserted"] == 1


def test_fresh_migration_schema(tmp_path):
    from alembic import command
    from alembic.config import Config
    from sqlalchemy import create_engine, inspect
    import os
    from pathlib import Path
    cfg = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
    url = f"sqlite:///{tmp_path / 'migration.db'}"
    cfg.set_main_option("sqlalchemy.url", url)
    previous = os.environ.pop("DATABASE_URL", None)
    try:
        command.upgrade(cfg, "head")
    finally:
        if previous is not None:
            os.environ["DATABASE_URL"] = previous
    columns = {c["name"] for c in inspect(create_engine(url)).get_columns("observations")}
    assert {"is_demo", "source_identifier", "content_hash"} <= columns


def test_v2_replay_excludes_future_quarterly_publication(db, monkeypatch):
    import apps.api.main as api
    from fastapi.testclient import TestClient
    sync_registry(db)
    db.add(Observation(indicator_id="it_major_usd_revenue_growth", period_start=date(2026, 1, 1), period_end=date(2026, 3, 31), value=Decimal("-2"), unit="pct", published_at=datetime(2026, 5, 30, tzinfo=timezone.utc), ingested_at=datetime(2026, 5, 31, tzinfo=timezone.utc), provider="manual_review", source_url="https://example.org/filing", vintage_id="quarterly-late", quality="verified", is_revision=False, is_demo=False))
    db.commit()
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    client = TestClient(api.app)
    response = client.get("/api/v1/replay", params={"as_of": "2026-04-30T23:59:00+05:30", "ruleset": "v2"})
    assert response.status_code == 200
    metric = next(m for m in response.json()["metrics"] if m["id"] == "it_major_usd_revenue_growth")
    assert metric["value"] is None
