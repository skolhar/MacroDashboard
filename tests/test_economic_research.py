"""Synthetic economic values only; network is mocked in automated tests."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select
from packages.connectors.world_bank import WDIRecord, WorldBankGEMAdapter, parse_gem, parse_wdi
from packages.domain.models import IngestionRun, ResearchEvidence
from packages.jobs.wdi_research import ingest
from packages.scoring.economic_transform import transform_series, spread_series
from packages.scoring.discovery import evaluate
from packages.scoring.discovery import _series, rules
from packages.scoring.economic_coverage import coverage

UTC = timezone.utc


def row(day, value, key="series", frequency="monthly", ident=1):
    return {"kind": "private_research", "id": ident, "series": key, "date": day, "value": Decimal(str(value)), "frequency": frequency, "source": "synthetic", "reference": "https://example.org/synthetic", "revision": "v1", "published_at": None, "retrieved_at": datetime(2026, 10, 1, tzinfo=UTC), "quality": "estimated"}


def test_growth_negative_zero_and_seasonality():
    annual = [row(date(2023, 12, 31), -10, frequency="annual"), row(date(2024, 12, 31), 0, frequency="annual", ident=2), row(date(2025, 12, 31), 20, frequency="annual", ident=3)]
    assert transform_series(annual, {"primary": "yoy_pct"}) == []
    changes = transform_series(annual, {"primary": "first_difference"})
    assert [x["value"] for x in changes] == [10, 20]
    monthly = [row(date(2024 + (i // 12), i % 12 + 1, 28), 100 + i % 12 + (20 if i >= 12 else 0), ident=i + 1) for i in range(24)]
    yoy = transform_series(monthly, {"primary": "yoy_pct"})
    assert len(yoy) == 12 and yoy[0]["value"] == 20
    assert len(transform_series(monthly, {"primary": "seasonally_comparable"})) == 12
    monthly.pop(7)
    assert len(transform_series(monthly, {"primary": "yoy_pct"})) == 11


def test_rolling_momentum_acceleration_spread_and_gaps():
    days = [date(2026, m, 28) for m in range(1, 7)]
    rows = [row(day, value, ident=i + 1) for i, (day, value) in enumerate(zip(days, [10, 12, 14, 18, 20, 22]))]
    assert transform_series(rows, {"primary": "rolling_sum", "window": 3})[-1]["value"] == 60
    assert transform_series(rows, {"primary": "rolling_growth", "window": 3})[-1]["value"] == Decimal(100) * (Decimal(22) / Decimal(14) - 1)
    assert transform_series(rows, {"primary": "acceleration"})[2]["value"] == -2
    assert transform_series(rows, {"primary": "rolling_volatility", "window": 3})
    assert transform_series(rows, {"primary": "rolling_deviation", "window": 3})[-1]["value"] == 4
    other = [row(day, 1, key="other", ident=10 + i) for i, day in enumerate(days)]
    assert spread_series(transform_series(rows, {"primary": "raw"}), transform_series(other, {"primary": "raw"}), "spread")[-1]["value"] == 21
    rows.pop(3)
    assert transform_series(rows, {"primary": "rolling_sum", "window": 3})[-1]["date"] == date(2026, 3, 28)


def test_parser_rejects_wrong_source_and_preserves_month():
    payload = [{"pages": 1, "sourceid": "15", "lastupdated": "2026-09-08"}, [{"indicator": {"id": "CPTOTNSXN"}, "country": {"id": "IND"}, "countryiso3code": "", "date": "2024M02", "value": 120.5}]]
    records = parse_gem(payload, {"gem_cpi_index"}, "https://api.worldbank.org/test")
    assert records[0].period_end == date(2024, 2, 29)
    assert records[0].frequency == "monthly"
    payload[1][0]["country"]["id"] = "USA"
    with pytest.raises(ValueError):
        parse_gem(payload, {"gem_cpi_index"}, "https://api.worldbank.org/test")
    wdi = [{"pages": 1, "sourceid": "2", "lastupdated": "2026-10-08"}, [{"indicator": {"id": "FS.AST.PRVT.GD.ZS"}, "countryiso3code": "IND", "date": "2025", "value": 44.0}]]
    assert parse_wdi(wdi, {"wdi_private_credit_gdp"}, "https://api.worldbank.org/test")[0].period_end == date(2025, 12, 31)


def test_adapter_failure_fails_closed_and_logs(db, monkeypatch):
    monkeypatch.setattr("packages.connectors.world_bank.time.sleep", lambda *_: None)
    transport = httpx.MockTransport(lambda request: httpx.Response(503, request=request))
    with httpx.Client(transport=transport) as client:
        adapter = WorldBankGEMAdapter(client)
        with pytest.raises(httpx.HTTPStatusError):
            ingest(db, adapter, 2024, 2025)
    assert db.scalar(select(IngestionRun).where(IngestionRun.provider == "world_bank_gem_research")).status == "failed"
    assert db.scalar(select(ResearchEvidence).where(ResearchEvidence.indicator_key == "gem_cpi_index")) is None


def test_idempotent_research_import_and_revisions(db):
    source_url = "https://api.worldbank.org/v2/country/IND/indicator/CPTOTNSXN?source=15"
    first = WDIRecord("gem_cpi_index", date(2025, 1, 31), Decimal("100"), "index_provider_basis", source_url, "2026-09-08", "monthly")
    adapter = SimpleNamespace(provider="world_bank_gem_research", fetch=lambda *args: [first])
    assert ingest(db, adapter)["inserted"] == 1
    assert ingest(db, adapter)["duplicates"] == 1
    revised = WDIRecord("gem_cpi_index", first.period_end, Decimal("100.2"), first.unit, source_url, "2026-10-09", "monthly")
    adapter.fetch = lambda *args: [revised]
    assert ingest(db, adapter)["inserted"] == 1
    facts = db.scalars(select(ResearchEvidence).where(ResearchEvidence.indicator_key == "gem_cpi_index")).all()
    assert len(facts) == 2 and all(f.published_at is None for f in facts)
    assert {f.value_text for f in facts} == {"100", "100.2"}
    assert len({f.revision_id for f in facts}) == 2


def test_actual_retrieval_clock_prevents_historical_lookahead(db):
    when = datetime(2025, 12, 31, 23, tzinfo=UTC)
    fact = ResearchEvidence(indicator_key="wdi_private_credit_gdp", indicator_or_claim="synthetic credit ratio", frequency="annual", value_numeric=Decimal("44"), value_text=None, unit="pct_gdp", period_start=date(2025, 1, 1), period_end=date(2025, 12, 31), source_name="synthetic", source_reference="https://example.org/synthetic", retrieved_at=when + timedelta(days=5), published_at=None, reliability_note="Synthetic test value; no actual observation", usage_basis="Synthetic test fixture for regression only", quality="estimated", revision_id="v1", observation_key="synthetic-credit-later", entered_by="test")
    db.add(fact)
    db.flush()
    assert "wdi_private_credit_gdp" not in evaluate(db, when, include_test_fixtures=True)["series"]


def test_base_effect_and_mixed_frequency_do_not_become_persistent_candidates():
    rows = []
    for i in range(39):
        year, month = 2018 + i // 12, i % 12 + 1
        day = date(year, month, 28)
        value = 50 if year == 2020 else 100
        rows.append(row(day, value, key="gem_exports", ident=i + 1))
    transformed = transform_series(rows, {"primary": "yoy_pct", "base_effect_drop_pct": 10})
    assert transformed[-1]["base_effect_possible"]
    assessed = _series("gem_exports", transformed, datetime(2021, 3, 31, tzinfo=UTC), rules(), {"primary": "yoy_pct", "baseline_periods": 24, "persistent_periods": 3, "robust_deviation": 2.5})
    assert assessed["status"] == "BASE_EFFECT_REVIEW"
    assert not assessed["persistent"]
    mixed = [row(date(2025, 12, 31), 1, frequency="annual"), row(date(2026, 1, 31), 2, ident=2)]
    assert _series("mixed", mixed, datetime(2026, 2, 1, tzinfo=UTC), rules())["status"] == "INCOMPATIBLE_FREQUENCY"


def test_coverage_reports_missing_sources_and_read_scope(db, monkeypatch):
    from fastapi.testclient import TestClient
    from packages.jobs.operators import issue
    import apps.api.main as api
    summary = coverage(db, datetime.now(UTC))
    assert summary["summary"]["configured"] == 15
    assert summary["summary"]["available"] == 0
    assert any(x["id"] == "india_cpi_monthly" for x in summary["pending_sources"])
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setattr(api, "LIMITER", SimpleNamespace(allow=lambda *args, **kwargs: True))
    monkeypatch.setenv("APP_ENV", "development")
    read = issue(db, "reader", {"research:read"}, 1)
    write = issue(db, "writer", {"research:write"}, 1)
    client = TestClient(api.app)
    assert client.get("/api/v1/research/coverage").status_code == 401
    assert client.get("/api/v1/research/coverage", headers={"X-Admin-Token": write}).status_code == 403
    assert client.get("/api/v1/research/coverage", headers={"X-Admin-Token": read}).status_code == 200


def test_historical_coverage_excludes_unfinished_later_run(db):
    start = datetime(2026, 1, 1, tzinfo=UTC)
    db.add(IngestionRun(provider="world_bank_gem_research", started_at=start, finished_at=start + timedelta(hours=2), status="success", item_count=1))
    db.flush()
    before = coverage(db, start + timedelta(hours=1))
    after = coverage(db, start + timedelta(hours=3))
    assert before["source_status"]["world_bank_gem_research"]["status"] == "never"
    assert after["source_status"]["world_bank_gem_research"]["status"] == "success"


def test_transformed_cross_indicator_hypothesis_stays_provisional(db):
    from calendar import monthrange
    for index in range(39):
        year, month = 2018 + index // 12, index % 12 + 1
        day = date(year, month, monthrange(year, month)[1])
        later = max(0, index - 35)
        for key, base, factor in (("gem_fx_rate", Decimal("70"), Decimal("1.03")), ("gem_total_reserves", Decimal("500"), Decimal("0.97"))):
            value = base * factor ** later
            db.add(ResearchEvidence(indicator_key=key, indicator_or_claim=f"synthetic {key}", frequency="monthly", value_numeric=value, value_text=str(value), unit="synthetic units", period_start=day.replace(day=1), period_end=day, source_name="Synthetic test source", source_reference="https://example.org/synthetic", retrieved_at=datetime.combine(day + timedelta(days=1), datetime.min.time(), UTC), published_at=None, reliability_note="Synthetic regression scenario; not actual macro data", usage_basis="Synthetic test fixture for regression only", quality="estimated", revision_id="v1", observation_key=f"synthetic:{key}:{day}", entered_by="test"))
    db.flush()
    assessed = evaluate(db, datetime(2021, 4, 15, tzinfo=UTC), include_test_fixtures=True)
    candidate = next(item for item in assessed["relationships"] if item["relationship_id"] == "monthly_fx_reserve_question")
    assert candidate["hypothesis"]["causal_status"] == "unverified_proposal"
    assert candidate["hypothesis"]["competing_explanations"]
    assert {item["transform"] for item in candidate["observations"]} == {"mom_pct"}
