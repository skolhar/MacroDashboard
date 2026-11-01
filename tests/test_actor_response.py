"""Synthetic actor-response fixtures; no values here are Indian observations."""
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from types import SimpleNamespace
import httpx
import pytest
from sqlalchemy import select
from packages.connectors.rbi_research_mirror import MirrorRecord, RBIResearchMirrorAdapter, parse_table
from packages.domain.models import IngestionRun, ResearchEvidence
from packages.jobs.rbi_mirror_research import ingest
from packages.scoring.actor_response import CREDIT, DEPOSITS, LIQUIDITY, evaluate as actor_evaluate
from packages.scoring.discovery import evaluate as discovery_evaluate, persist as persist_discovery, replay as replay_discovery
from packages.scoring.economic_transform import transform_series

UTC = timezone.utc


def fact(key, day, value, ident, frequency):
    return {"kind": "private_research", "id": ident, "series": key, "date": day, "value": Decimal(str(value)), "source_value_text": str(value), "frequency": frequency, "source": "Synthetic test fixture", "reference": "https://example.org/synthetic", "revision": "v1", "published_at": None, "retrieved_at": datetime(2025, 2, 15, tzinfo=UTC), "quality": "estimated"}


def sequence(response=100, follow=1.20, include_liquidity=True, initial_year=2023):
    bank = []
    for i in range(56):
        day = date(initial_year, 1, 6) + timedelta(days=14 * i)
        deposits = Decimal("1000") + Decimal(i * 10)
        multiplier = Decimal("1.0") if i < 52 else Decimal("1.1") if i < 54 else Decimal(str(follow))
        bank.extend([fact(CREDIT, day, deposits * multiplier, i * 2 + 1, "fortnightly"), fact(DEPOSITS, day, deposits, i * 2 + 2, "fortnightly")])
    second = bank[106]["date"]
    liquidity = [fact(LIQUIDITY, second + timedelta(days=i), response, 200 + i, "daily") for i in range(1, 6)] if include_liquidity else []
    last = bank[-1]["date"]
    if include_liquidity:
        liquidity.append(fact(LIQUIDITY, last, response, 300, "daily"))
    return bank + liquidity, last + timedelta(days=1)


def test_actor_sequence_requires_prior_regime_and_temporal_response():
    rows, last = sequence()
    result = actor_evaluate(rows, datetime.combine(last, datetime.min.time(), UTC))
    assert result["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    assert result["state_class"] == "descriptive_observation"
    assert result["causal_status"] == "unverified_interpretation"
    assert result["operation_status"] == "publisher_defined_only"
    assert result["disturbance_periods"][-1] < result["response_periods"][0] < result["followup_periods"][0]
    assert len({(x["kind"], x["id"]) for x in result["observations"]}) == len(result["observations"])
    assert result["confirmation_needed"] and result["alternatives"]
    no_response = [r for r in rows if r["series"] != LIQUIDITY]
    assert actor_evaluate(no_response, datetime.combine(last, datetime.min.time(), UTC))["status"] == "INSUFFICIENT_EVIDENCE"
    prior = fact(LIQUIDITY, date(2024, 1, 1), 100, 999, "daily")
    stale_feed = actor_evaluate(no_response + [prior], datetime.combine(last, datetime.min.time(), UTC))
    assert stale_feed["status"] == "STALE_EVIDENCE"
    assert "older than its configured reporting-cadence window" in stale_feed["explanation"]


def test_actor_counterforce_weakening_definition_and_frequency():
    rows, last = sequence(response=-100)
    result = actor_evaluate(rows, datetime.combine(last, datetime.min.time(), UTC))
    assert result["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    assert result["state_class"] == "descriptive_observation"
    assert "absorption" in result["explanation"]
    weaker, last = sequence(follow=1.05)
    assert actor_evaluate(weaker, datetime.combine(last, datetime.min.time(), UTC))["status"] == "OBSERVED_FUNDING_GAP_NARROWING"
    closed, last = sequence(follow=0.95)
    assert actor_evaluate(closed, datetime.combine(last, datetime.min.time(), UTC))["status"] == "OBSERVED_FUNDING_GAP_CLOSED"
    wrong_frequency = [dict(row, frequency="monthly") if row["series"] == CREDIT else row for row in weaker]
    assert actor_evaluate(wrong_frequency, datetime.combine(last, datetime.min.time(), UTC))["status"] == "CONFLICTING_EVIDENCE"
    changed, last = sequence(initial_year=2024)
    assert actor_evaluate(changed, datetime.combine(last, datetime.min.time(), UTC))["status"] == "DEFINITION_REVIEW"


def test_actor_stale_and_historical_only():
    rows, last = sequence()
    assert actor_evaluate(rows, datetime.combine(last + timedelta(days=90), datetime.min.time(), UTC))["status"] == "STALE_EVIDENCE"
    assert actor_evaluate(rows, datetime.combine(last + timedelta(days=300), datetime.min.time(), UTC))["status"] == "HISTORICAL_ONLY"


def test_mirror_parser_rejects_changed_units_and_headers():
    meta = {"data": {"title": "Scheduled Commercial Banks - Select Aggregates", "frequency": "Fortnightly", "source": "statistics", "layout": "columns", "key": "financial_sector.r901_scheduled_commercial_banks_select_aggregates", "row_count": 8, "loaded_at": "2026-10-31T00:00:00Z", "dbie_path": "RBI DBIE"}, "provenance": {"report_name": "Scheduled Commercial Banks - Select Aggregates", "exported_at": "2026-10-31", "period_to": "31-AUG-2026"}}
    columns = ["row_no"] + [f"c{i}" for i in range(1, 20)]
    rows = [[i] + [""] * 19 for i in range(1, 9)]
    rows[3][1] = "(₹ Crores)"
    rows[5][4] = "Aggregate deposits (2+3)"
    rows[5][15] = "Bank Credit (11+12)"
    rows[7][1], rows[7][4], rows[7][15] = "Oct 15, 2026", "2,000", "1,500"
    payload = {"columns": columns, "rows": rows}
    parsed = parse_table(meta, payload, "bank", date(2025, 1, 1))
    assert len(parsed) == 2 and all("period_to predates" in item.definition_note for item in parsed)
    rows[3][1] = "USD millions"
    with pytest.raises(ValueError, match="unit"):
        parse_table(meta, payload, "bank")
    rows[3][1] = "(₹ Crores)"
    rows[5][15] = "Adjusted bank credit"
    with pytest.raises(ValueError, match="definition"):
        parse_table(meta, payload, "bank")
    rows[5][15] = "Bank Credit (11+12)"
    rows[7][1] = "unparseable date"
    with pytest.raises(ValueError, match="date"):
        parse_table(meta, payload, "bank")


def test_mirror_idempotency_revision_and_fail_closed(db, monkeypatch):
    reference = "https://data-api.dbie.rbihub.in/api/tables/financial_sector/r901_scheduled_commercial_banks_select_aggregates#row-8"
    record = MirrorRecord(CREDIT, date(2025, 1, 10), Decimal("100"), "inr_crore", "fortnightly", reference, "2026-10-31", "RBI DBIE", "Synthetic fixture")
    adapter = SimpleNamespace(provider="rbi_innovation_hub_dbie_mirror_research", fetch=lambda *_: [record])
    assert ingest(db, "bank", adapter)["inserted"] == 1
    assert ingest(db, "bank", adapter)["duplicates"] == 1
    adapter.fetch = lambda *_: [MirrorRecord(CREDIT, record.period_end, Decimal("101"), record.unit, record.frequency, reference, "2026-11-01", "RBI DBIE", "Synthetic fixture")]
    assert ingest(db, "bank", adapter)["inserted"] == 1
    facts = db.scalars(select(ResearchEvidence).where(ResearchEvidence.indicator_key == CREDIT)).all()
    assert len(facts) == 2 and all(row.published_at is None for row in facts)
    assert {row.value_text for row in facts} == {"100", "101"}
    monkeypatch.setattr("packages.connectors.rbi_research_mirror.time.sleep", lambda *_: None)
    with httpx.Client(transport=httpx.MockTransport(lambda request: httpx.Response(503, request=request))) as client:
        with pytest.raises(httpx.HTTPStatusError):
            ingest(db, "liquidity", RBIResearchMirrorAdapter(client))
    run = db.scalar(select(IngestionRun).where(IngestionRun.provider.endswith(":liquidity")))
    assert run.status == "failed" and run.error_code == "HTTPStatusError"


def test_fortnightly_yoy_does_not_bridge_definition_break():
    rows, _ = sequence()
    credit = [row for row in rows if row["series"] == CREDIT]
    transformed = transform_series(credit, {"primary": "yoy_pct", "definition_breaks": ["2025-01-01"]})
    assert all(not (row["date"].year == 2025 and row["date"].month == 1) for row in transformed)


def test_historical_vintages_snapshot_and_candidate_persistence(db, monkeypatch):
    rows, last = sequence()
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    for row in rows:
        db.add(ResearchEvidence(indicator_key=row["series"], indicator_or_claim="Synthetic test fixture", frequency=row["frequency"], value_numeric=row["value"], value_text=str(row["value"]), unit="inr_crore", period_start=row["date"], period_end=row["date"], source_name="Synthetic test fixture", source_reference=row["reference"], retrieved_at=as_of - timedelta(days=1), published_at=None, reliability_note="Synthetic test value", usage_basis="Synthetic test fixture for regression only", quality="estimated", revision_id="v1", observation_key=f"synthetic-actor-{row['id']}", entered_by="test"))
    db.flush()
    before = discovery_evaluate(db, as_of, include_test_fixtures=True)
    actor = before["actor_responses"][0]
    assert actor["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    assert actor["state_class"] == "descriptive_observation"
    assert actor["key"] in {candidate["key"] for candidate in before["candidate_hypotheses"]}
    snapshot = persist_discovery(db, as_of, "synthetic-actor-snapshot", "test", recorded_at=as_of + timedelta(days=2), include_test_fixtures=True)
    frozen = replay_discovery(snapshot)
    assert frozen["result"]["actor_responses"][0]["status"] == actor["status"]
    assert frozen["rules"]["actor_responses"]["version"] == "actor-research-v1"
    assert persist_discovery(db, as_of, "synthetic-actor-snapshot", "test", recorded_at=as_of + timedelta(days=2), include_test_fixtures=True).id == snapshot.id
    from fastapi.testclient import TestClient
    from packages.jobs.operators import issue
    import apps.api.main as api
    db.commit()
    monkeypatch.setattr(api, "DB", db.bind)
    monkeypatch.setattr(api, "DEMO", False)
    monkeypatch.setattr(api, "LIMITER", SimpleNamespace(allow=lambda *args, **kwargs: True))
    monkeypatch.setenv("APP_ENV", "development")
    monkeypatch.setenv("OPERATOR_AUTH_MODE", "db")
    writer = issue(db, "actor-investigator", {"research:write"}, 1)
    reader = issue(db, "actor-reader", {"research:read"}, 1)
    client = TestClient(api.app)
    path = "/api/v1/research/discovery/hypotheses"
    payload = {"snapshot_id": snapshot.id, "candidate_key": actor["key"], "investigation_question": "What motivated the observed RBI operation after the bank funding gap?"}
    assert client.post(path, json=payload, headers={"X-Admin-Token": reader}).status_code == 403
    opened = client.post(path, json=payload, headers={"X-Admin-Token": writer})
    assert opened.status_code == 200 and opened.json()["duplicate"] is False
    repeated = client.post(path, json=payload, headers={"X-Admin-Token": writer})
    assert repeated.status_code == 200 and repeated.json()["id"] == opened.json()["id"] and repeated.json()["duplicate"] is True
    later_snapshot = persist_discovery(db, as_of + timedelta(days=1), "synthetic-actor-snapshot-later", "test", recorded_at=as_of + timedelta(days=3), include_test_fixtures=True)
    db.commit()
    repeated_later = client.post(path, json={**payload, "snapshot_id": later_snapshot.id}, headers={"X-Admin-Token": writer})
    assert repeated_later.status_code == 200 and repeated_later.json()["id"] == opened.json()["id"]
    revised = next(row for row in rows if row["series"] == CREDIT and row["date"] == last - timedelta(days=1))
    db.add(ResearchEvidence(indicator_key=CREDIT, indicator_or_claim="Synthetic revised test fixture", frequency="fortnightly", value_numeric=Decimal("100"), value_text="100", unit="inr_crore", period_start=revised["date"], period_end=revised["date"], source_name="Synthetic test fixture", source_reference=revised["reference"], retrieved_at=as_of + timedelta(days=5), published_at=None, reliability_note="Synthetic late revision", usage_basis="Synthetic test fixture for regression only", quality="estimated", revision_id="v2", observation_key="synthetic-actor-late-revision", entered_by="test"))
    db.flush()
    assert discovery_evaluate(db, as_of, include_test_fixtures=True)["actor_responses"][0]["status"] == actor["status"]
    after = discovery_evaluate(db, as_of + timedelta(days=10), include_test_fixtures=True)
    assert any(item["revision"] == "v2" for item in after["actor_responses"][0]["observations"])
    assert replay_discovery(snapshot)["result"] == frozen["result"]


def test_mixed_operation_types_sum_and_unresolved_interpretation():
    rows, last = sequence()
    mixed = {201: 400, 202: -150, 203: 200, 204: -100, 205: 300}
    for row in rows:
        if row["id"] in mixed:
            row["value"] = Decimal(mixed[row["id"]])
            row["source_value_text"] = str(mixed[row["id"]])
    result = actor_evaluate(rows, datetime.combine(last, datetime.min.time(), UTC))
    assert result["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    assert result["liquidity_interpretation"]["classification"] == "unresolved_definition"
    assert result["liquidity_interpretation"]["independently_validated"] is False
    assert "mixed operation types" in result["liquidity_interpretation"]["aggregation"]
    assert "not a liquidity stock" in result["liquidity_interpretation"]["measure"]
    operations = result["response_operations"]
    assert [op["net_cr"] for op in operations] == [400.0, -150.0, 200.0, -100.0, 300.0]
    assert result["observed_response_net_cr"] == sum(op["net_cr"] for op in operations) == 650.0
    assert result["evidence_layers"]["subsequent_operations"]["observed"] is True
    assert result["evidence_layers"]["observed_divergence"]["observed"] is True
    assert result["evidence_layers"]["documented_motivation"]["observed"] is False
    assert "motive is unknown" in result["explanation"]


def test_sign_convention_injection_absorption_and_zero_are_publisher_labeled_only():
    injection, last = sequence(response=250)
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    positive = actor_evaluate(injection, as_of)
    assert positive["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    assert positive["observed_response_net_cr"] == 1250.0
    assert "net injection" in positive["explanation"]
    assert all(op["reported_label"].startswith("publisher") for op in positive["response_operations"])
    absorption, last = sequence(response=-250)
    negative = actor_evaluate(absorption, as_of)
    assert negative["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    assert negative["observed_response_net_cr"] == -1250.0
    assert "net absorption" in negative["explanation"]
    assert negative["liquidity_interpretation"]["sign_convention"].startswith("Publisher label: positive means net injection")
    zero, last = sequence(response=0)
    zero_result = actor_evaluate(zero, as_of)
    assert zero_result["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    assert zero_result["observed_response_net_cr"] == 0.0


def test_missing_daily_liquidity_observations_stay_insufficient():
    rows, last = sequence()
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    three_days = [row for row in rows if row["series"] != LIQUIDITY or row["id"] in {201, 202, 203, 300}]
    result = actor_evaluate(three_days, as_of)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["evidence_layers"]["subsequent_operations"]["observed"] is False
    assert any("five separately dated RBI liquidity-operation observations" in item for item in result["missing_confirmation"])
    assert result["response_periods"] == [] and result["response_operations"] == []
    assert result.get("observed_response_net_cr") is None
    no_liquidity = [row for row in rows if row["series"] != LIQUIDITY]
    absent = actor_evaluate(no_liquidity, as_of)
    assert absent["status"] == "INSUFFICIENT_EVIDENCE"
    assert "no independently observed RBI liquidity-operation response" in absent["explanation"]


def test_liquidity_table_rejects_reporting_definition_changes():
    title = "Liquidity Operations by RBI"
    meta = {"data": {"title": title, "frequency": "Daily", "source": "statistics", "layout": "columns", "key": "financial_markets.r702_liquidity_operations_by_rbi", "row_count": 9, "loaded_at": "2026-10-31T00:00:00Z", "dbie_path": "RBI DBIE"}, "provenance": {"report_name": title, "exported_at": "2026-10-31", "period_to": "31-AUG-2026"}}
    columns = ["row_no"] + [f"c{i}" for i in range(1, 19)]
    rows = [[i] + [""] * 18 for i in range(1, 10)]
    rows[3][1] = "(Rupees Crores)"
    rows[6][18] = "Net Injection (+)/ Absorption (-) (1+3+5+7+10-2-4-6-9)"
    rows[7][1], rows[7][18] = "Oct 1, 2026", "120"
    rows[8][1], rows[8][18] = "Oct 2, 2026", "-80"
    parsed = parse_table(meta, {"columns": columns, "rows": rows}, "liquidity")
    assert [record.value for record in parsed] == [Decimal("120"), Decimal("-80")]
    assert parsed[0].indicator_key == "rbi_mirror_net_injection_cr" and parsed[0].frequency == "daily"
    assert "net injection" in parsed[0].definition_note and "motive is not identified" in parsed[0].definition_note
    rows[3][1] = "US Dollar Millions"
    with pytest.raises(ValueError, match="unit"):
        parse_table(meta, {"columns": columns, "rows": rows}, "liquidity")
    rows[3][1] = "(Rupees Crores)"
    rows[6][18] = "Net Liquidity (crores)"
    with pytest.raises(ValueError, match="definition"):
        parse_table(meta, {"columns": columns, "rows": rows}, "liquidity")
    rows[6][18] = "Net Injection (+)/ Absorption (-) (1+3+5+7+10-2-4-6-9)"
    changed = dict(meta, data=dict(meta["data"], title="Renamed Liquidity Report"))
    with pytest.raises(ValueError, match="definition changed"):
        parse_table(changed, {"columns": columns, "rows": rows}, "liquidity")


def test_retrospective_reconstruction_is_labelled_with_provenance_intact():
    rows, last = sequence()
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    assert actor_evaluate(rows, as_of)["analysis_basis"] == "system_known_research"
    retrospective = actor_evaluate(rows, as_of + timedelta(days=400), episode_end=last)
    assert retrospective["analysis_basis"] == "retrospective_current_vintage"
    for item in retrospective["observations"]:
        assert item["published_at"] is None
        assert item["retrieved_at"] == "2025-02-15T00:00:00+00:00"
        assert item["revision"] == "v1" and item["quality"] == "estimated"
        assert item["source"] == "Synthetic test fixture" and item["source_reference"].startswith("https://")
    assert actor_evaluate(rows, as_of, knowledge_mode="source_known")["analysis_basis"] == "retrospective_source_reconstruction"


def test_false_actor_response_associations_are_not_attributed_to_the_gap():
    rows, last = sequence()
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    onset_rows = rows + [fact(LIQUIDITY, date(2025, 1, 3), 500, 401, "daily")]
    between_rows = rows + [fact(LIQUIDITY, date(2025, 1, 10), 500, 402, "daily")]
    for extra in (onset_rows, between_rows):
        result = actor_evaluate(extra, as_of)
        assert result["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
        assert result["observed_response_net_cr"] == 500.0
        assert all(op["period_end"] not in {"2025-01-03", "2025-01-10"} for op in result["response_operations"])
    absorption, last = sequence(response=-250)
    padded = absorption + [fact(LIQUIDITY, date(2025, 1, 3), 5000, 403, "daily")]
    padded_result = actor_evaluate(padded, datetime.combine(last, datetime.min.time(), UTC))
    assert padded_result["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    assert padded_result["observed_response_net_cr"] == -1250.0


def test_widely_separated_operation_dates_are_not_consecutive_sessions():
    """Five sparse reports inside the window must not read as five sessions."""
    rows, last = sequence()
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    # The response window opens after the SECOND positive gap period (i=53);
    # index 52 is the onset itself. The reference horizon (last bank report)
    # sits 29 days after the second period, so all sparse offsets stay inside it.
    second = [r for r in rows if r["series"] == CREDIT and r["date"].isoformat() in {
        d.isoformat() for d in [date(2023, 1, 6) + timedelta(days=14 * i) for i in range(56)]}][53]["date"]
    sparse = [r for r in rows if r["series"] != LIQUIDITY]
    sparse += [fact(LIQUIDITY, second + timedelta(days=offset), 100, 400 + k, "daily") for k, offset in enumerate([1, 2, 3, 4, 19])]
    result = actor_evaluate(sparse, as_of)
    assert result["status"] == "COVERAGE_INCOMPLETE"
    assert result["coverage"]["operation_dates_are_consecutive_sessions"] is False
    assert result["coverage"]["max_gap_between_operation_reports_days"] > 14
    assert "widely spaced" in result["explanation"] or "not interpreted as consecutive operation sessions" in result["explanation"]


def test_unverified_definition_cannot_create_confirmed_inflection():
    """With liquidity_definition_validated false, no causal state may appear."""
    rows, last = sequence(follow=0.95)
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    closed = actor_evaluate(rows, as_of)
    assert closed["status"] == "OBSERVED_FUNDING_GAP_CLOSED"
    assert closed["state_class"] == "descriptive_observation"
    assert closed["status"] not in {"EMERGING_INFLECTION", "POTENTIAL_REINFORCEMENT", "WEAKENING_REINFORCEMENT"}
    assert any("definition" in item.lower() for item in closed["missing_confirmation"])
    widening, last = sequence(follow=1.20)
    widened = actor_evaluate(widening, as_of)
    assert widened["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    assert widened["state_class"] == "descriptive_observation"


def test_persistent_divergence_alone_does_not_establish_reinforcement():
    """A widening credit/deposit gap without observed operations stays insufficient."""
    rows, last = sequence(follow=1.20, include_liquidity=False)
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    result = actor_evaluate(rows, as_of)
    assert result["status"] == "INSUFFICIENT_EVIDENCE"
    assert result["state_class"] == "descriptive_observation"
    assert result["status"] not in {"POTENTIAL_REINFORCEMENT", "EMERGING_INFLECTION"}
    assert "no independently observed RBI liquidity-operation response" in result["explanation"]


def test_conflicting_source_observations_produce_unresolved_state():
    """Two different values for the same date must stop the evaluation."""
    rows, last = sequence()
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    second = rows[106]["date"]
    conflict = rows + [fact(LIQUIDITY, second + timedelta(days=1), 999, 501, "daily")]
    result = actor_evaluate(conflict, as_of)
    assert result["status"] == "CONFLICTING_EVIDENCE"
    assert "Conflicting independent observations" in result["explanation"]


def test_historical_revisions_do_not_leak_into_earlier_assessments(db):
    """A later revision must not alter an earlier system-known evaluation."""
    rows, last = sequence()
    as_of = datetime.combine(last, datetime.min.time(), UTC)
    for row in rows:
        db.add(ResearchEvidence(indicator_key=row["series"], indicator_or_claim="Synthetic revision fixture", frequency=row["frequency"], value_numeric=row["value"], value_text=str(row["value"]), unit="inr_crore", period_start=row["date"], period_end=row["date"], source_name="Synthetic test fixture", source_reference=row["reference"], retrieved_at=as_of - timedelta(days=1), published_at=None, reliability_note="Synthetic test value", usage_basis="Private exploratory research from a secondary mirror; source-data rights unverified", quality="estimated", revision_id="v1", observation_key=f"revision-{row['id']}", entered_by="test"))
    db.flush()
    before = discovery_evaluate(db, as_of, include_test_fixtures=True)
    assert before["actor_responses"][0]["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    revised_day = as_of.date() - timedelta(days=1)
    db.add(ResearchEvidence(indicator_key=CREDIT, indicator_or_claim="Synthetic revision fixture", frequency="fortnightly", value_numeric=Decimal("1"), value_text="1", unit="inr_crore", period_start=revised_day, period_end=revised_day, source_name="Synthetic test fixture", source_reference="https://example.org/revised", retrieved_at=as_of + timedelta(days=10), published_at=None, reliability_note="Later revision", usage_basis="Private exploratory research from a secondary mirror; source-data rights unverified", quality="secondary", revision_id="v2", observation_key="revision-late", entered_by="test"))
    db.flush()
    after = discovery_evaluate(db, as_of, include_test_fixtures=True)
    assert after["actor_responses"][0]["status"] == "OBSERVED_FUNDING_GAP_WIDENING"
    later_as_of = as_of + timedelta(days=10)
    later = discovery_evaluate(db, later_as_of, include_test_fixtures=True)
    # The revision is now known and legitimately changes the later assessment;
    # the earlier `before` and `after` results above are untouched by it.
    assert later["actor_responses"][0]["status"] != "OBSERVED_FUNDING_GAP_WIDENING"
    assert "MIXED_DIVERGENCE_EVIDENCE" == later["actor_responses"][0]["status"]
