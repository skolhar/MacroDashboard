from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from sqlalchemy import select
from packages.domain.models import Observation
from packages.domain.store import observations_at
from packages.scoring.engine import compute, change_bps, fpi_usd_return, oil_bill_sensitivity_usd_bn
from packages.scoring.alerts import fx_alert

AS_OF = datetime.fromisoformat("2026-10-31T00:00:00+05:30")

def test_t01_missing_fx_reduces_coverage_and_no_zero_imputation(db):
    before = compute(db, AS_OF)
    for row in db.scalars(select(Observation).where(Observation.indicator_id == "usd_inr_spot")).all():
        db.delete(row)
    db.flush()
    after = compute(db, AS_OF)
    assert after["overall"]["coverage"] < before["overall"]["coverage"]
    assert after["overall"]["score"] is None
    assert next(c for c in after["cycles"] if c["id"] == "fx")["score"] is None
    assert next(m for m in after["metrics"] if m["id"] == "usd_inr_spot")["value"] is None

def test_t02_no_look_ahead_quarterly_release(db):
    row = Observation(indicator_id="nifty_eps_revision_3m", period_start=date(2026, 1, 1), period_end=date(2026, 3, 31), value=Decimal("-4"), unit="pct", published_at=datetime(2026, 5, 30, tzinfo=timezone.utc), ingested_at=datetime(2026, 5, 31, tzinfo=timezone.utc), provider="synthetic_fixture", vintage_id="test-future", quality="demo", is_revision=False)
    db.add(row); db.flush()
    assert row not in observations_at(db, row.indicator_id, datetime(2026, 4, 30, tzinfo=timezone.utc))

def test_t03_revision_vintage_is_preserved(db):
    original = db.scalar(select(Observation).where(Observation.indicator_id == "usd_inr_spot").order_by(Observation.period_end.desc()))
    later = AS_OF + timedelta(days=1)
    revised = Observation(indicator_id=original.indicator_id, period_start=original.period_start, period_end=original.period_end, value=original.value + Decimal("1"), unit=original.unit, published_at=later, ingested_at=later, provider=original.provider, vintage_id="revision-test", quality="demo", is_revision=True)
    db.add(revised); db.flush()
    assert observations_at(db, original.indicator_id, AS_OF)[-1].id == original.id
    assert observations_at(db, original.indicator_id, later + timedelta(minutes=1))[-1].id == revised.id

def test_t04_inverse_fx_return():
    assert abs(fpi_usd_return(.05, 90, 99) - (-.04545454545)) < 1e-9

def test_t05_bond_units():
    assert abs(change_bps(7.4, 7.1) - 30) < 1e-9

def test_t06_oil_sensitivity():
    assert oil_bill_sensitivity_usd_bn(10, 5.5) == 20.075

def test_t10_demo_isolation(db):
    live = compute(db, AS_OF, demo=False)
    assert live["overall"]["score"] is None
    assert live["overall"]["coverage"] == 0
    assert all(m["value"] is None for m in live["metrics"])

def test_fx_alert_does_not_fire_without_evidence(db):
    alert = fx_alert(db, AS_OF)[0]
    assert alert["status"] not in ("WATCH", "CRITICAL")

def test_t20_api_health_and_dashboard(db, monkeypatch):
    import apps.api.main as api
    from fastapi.testclient import TestClient
    monkeypatch.setattr(api, "DB", db.bind)
    client = TestClient(api.app)
    assert client.get("/api/v1/health").json()["status"] == "ok"
    response = client.get("/api/v1/dashboard")
    assert response.status_code == 200
    assert response.json()["mode"] == "demo"
    assert len(response.json()["cycles"]) == 6
    assert len(response.json()["metrics"]) == 12
    assert client.get("/docs").status_code == 200
