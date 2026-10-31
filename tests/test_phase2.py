from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select
from packages.connectors.base import DataUnavailable, SourceObservation, UnavailableAdapter
from packages.connectors.manual import parse_manual_csv
from packages.connectors.treasury import parse_treasury_xml
from packages.domain.calendar import is_session
from packages.domain.config import registry, rules
from packages.domain.models import Observation
from packages.domain.settings import settings
from packages.domain.store import observations_at
from packages.jobs.ingest import ingest_records
from packages.jobs.sync_registry import sync_registry
from packages.scoring.engine_v2 import compute_v2
from packages.scoring.inflections import status_for_evaluations


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


def test_alert_persistence_and_hysteresis():
    rule = rules("v2")["alerts"][0]
    assert status_for_evaluations([(4, 2)], rule)[0] == "UNKNOWN"
    assert status_for_evaluations([(4, 2)] * 2, rule)[0] == "WATCH"
    assert status_for_evaluations([(4, 3)] * 3, rule)[0] == "TRIGGERED"
    assert status_for_evaluations([(4, 4)] * 5, rule)[0] == "CONFIRMED"
    assert status_for_evaluations([(4, 4)] * 5 + [(4, 0)] * 4, rule)[0] == "CONFIRMED"
    assert status_for_evaluations([(4, 4)] * 5 + [(4, 0)] * 5, rule)[0] == "RESOLVED"
    assert status_for_evaluations([(4, 3)] * 3 + [(0, 0)], rule)[0] == "TRIGGERED"


def test_calendar_and_forward_sign_guard():
    assert is_session(date(2026, 10, 20), "india") is False
    assert is_session(date(2026, 2, 1), "india") is True
    assert is_session(date(2026, 11, 26), "us") is False
    assert is_session(date(2027, 1, 4), "india") is None
    assert "rbi_net_forward_usd" not in rules("v2")["cycle_signals"]["fx"]
    assert registry(True)["rbi_net_forward_usd"]["direction_of_stress"] == "contextual"
