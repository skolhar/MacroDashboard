"""Private, source-aware anomaly research. Statistical patterns are not causal claims."""
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from statistics import median
import json
import yaml
from sqlalchemy import select
from packages.domain.models import DiscoverySnapshot, IndicatorDefinition, MarketBar, Observation, ResearchEvidence

RULES_PATH = Path(__file__).resolve().parents[2] / "config/discovery.v1.yaml"


def rules():
    config = yaml.safe_load(RULES_PATH.read_text())
    if config.get("version") != "discovery-v1" or config["minimum_baseline_periods"] < 4 or config["persistent_periods"] < 2:
        raise ValueError("Unsupported discovery rules")
    return config


def _known(published, retrieved, as_of, mode):
    # An unknown publication date cannot establish historical source availability.
    known_at = published if mode == "source_known" and published is not None else retrieved
    return known_at <= as_of


def _inputs(session, as_of, mode, include_test_fixtures=False):
    rows = []
    frequencies = {item.id: item.frequency for item in session.scalars(select(IndicatorDefinition))}
    for item in session.scalars(select(ResearchEvidence).where(ResearchEvidence.period_end <= as_of.date(), ResearchEvidence.value_numeric.is_not(None))):
        if not include_test_fixtures and "synthetic test fixture" in item.usage_basis.lower():
            continue
        if _known(item.published_at, item.retrieved_at, as_of, mode):
            rows.append({"kind": "private_research", "id": item.id, "series": item.indicator_key, "date": item.period_end, "value": item.value_numeric, "frequency": item.frequency, "source": item.source_name, "reference": item.source_reference, "revision": item.revision_id, "published_at": item.published_at, "retrieved_at": item.retrieved_at, "quality": item.quality})
    for item in session.scalars(select(Observation).where(Observation.period_end <= as_of.date(), Observation.is_demo.is_(False))):
        if _known(item.published_at, item.ingested_at, as_of, mode):
            rows.append({"kind": "governed_macro", "id": item.id, "series": item.indicator_id, "date": item.period_end, "value": item.value, "frequency": frequencies.get(item.indicator_id, "event"), "source": item.provider, "reference": item.source_reference or item.source_url, "revision": item.vintage_id, "published_at": item.published_at, "retrieved_at": item.ingested_at, "quality": item.quality})
    for item in session.scalars(select(MarketBar).where(MarketBar.session_date <= as_of.date())):
        if item.retrieved_at <= as_of:
            rows.append({"kind": "secondary_market", "id": item.id, "series": item.instrument_id, "date": item.session_date, "value": item.close, "frequency": "business_daily", "source": item.provider, "reference": item.source_url, "revision": item.content_hash, "published_at": None, "retrieved_at": item.retrieved_at, "quality": item.quality})
    # Newest known vintage for a given publisher/date; independent publishers remain distinct.
    latest = {}
    for row in sorted(rows, key=lambda x: (x["retrieved_at"], x["id"])):
        latest[(row["series"], row["date"], row["source"], row["kind"])] = row
    return list(latest.values())


def _public(row):
    return {"kind": row["kind"], "id": row["id"], "series": row["series"], "period_end": row["date"].isoformat(), "value": float(row["value"]), "frequency": row["frequency"], "source": row["source"], "source_reference": row["reference"], "revision": row["revision"], "published_at": row["published_at"].isoformat() if row["published_at"] else None, "retrieved_at": row["retrieved_at"].isoformat(), "quality": row["quality"]}


def _series(series, rows, as_of, config):
    by_period = defaultdict(list)
    for row in rows:
        by_period[row["date"]].append(row)
    baseline_n = config["minimum_baseline_periods"]
    persistent_n = config["persistent_periods"]
    # An old disputed vintage cannot invalidate an otherwise clean current window.
    by_period = {day: by_period[day] for day in sorted(by_period)[-(baseline_n + persistent_n + 3):]}
    conflicts = [day.isoformat() for day, group in by_period.items() if len({(str(row["value"]), row["kind"]) for row in group}) > 1]
    usable = [max(group, key=lambda x: (x["retrieved_at"], x["id"])) for day, group in sorted(by_period.items()) if day.isoformat() not in conflicts]
    latest = usable[-1] if usable else None
    stale = bool(latest and (as_of.date() - latest["date"]).days > config["freshness_days"].get(latest["frequency"], 90))
    result = {"series": series, "status": "CONFLICTING" if conflicts else "DATA_UNAVAILABLE" if not latest else "STALE" if stale else "INSUFFICIENT_HISTORY", "frequency": latest["frequency"] if latest else None, "latest_period": latest["date"].isoformat() if latest else None, "conflicting_periods": conflicts, "conflicting_observations": [_public(row) for day, group in by_period.items() if day.isoformat() in conflicts for row in group], "observations": [_public(r) for r in usable], "anomalies": [], "persistent": False, "direction": None, "momentum": None, "acceleration": None, "limitations": []}
    if conflicts:
        result["limitations"].append("Conflicting source values were excluded; investigate source definitions and revisions.")
        return result
    if stale:
        result["limitations"].append("Latest value exceeds its reporting-cadence freshness window.")
    if len(usable) < baseline_n + persistent_n:
        result["limitations"].append(f"At least {baseline_n} baseline and {persistent_n} follow-up periods required; {len(usable)} available.")
        return result
    recent = usable[-(baseline_n + persistent_n):]
    max_gap = {"business_daily": 6, "daily": 5, "weekly": 11, "monthly": 45, "quarterly": 110, "annual": 400, "event": 365}
    if any((later["date"] - earlier["date"]).days > max_gap.get(later["frequency"], 90) for earlier, later in zip(recent, recent[1:])):
        result["status"] = "INCOMPLETE_HISTORY"
        result["limitations"].append("A reporting-period gap interrupts the baseline or persistence window; no consecutive-period claim is made.")
        return result
    values = [float(r["value"]) for r in usable]
    baseline = values[-(baseline_n + persistent_n):-persistent_n]
    follow = values[-persistent_n:]
    center = median(baseline)
    mad = median(abs(value - center) for value in baseline)
    scale = max(1.4826 * mad, abs(center) * 0.005, 0.0001)
    deviations = [(value - center) / scale for value in follow]
    signs = {1 if value > 0 else -1 for value in deviations}
    persistent = len(signs) == 1 and all(abs(value) >= config["robust_deviation"] for value in deviations)
    isolated = abs(deviations[-1]) >= config["robust_deviation"] and not persistent
    shift = abs(median(follow) - center) / scale
    differences = [values[i] - values[i - 1] for i in range(len(values) - persistent_n, len(values))]
    result.update({"status": "PERSISTENT" if persistent and not stale and not conflicts else "ISOLATED" if isolated and not stale and not conflicts else "CONFLICTING" if conflicts else "STALE" if stale else "NO_PATTERN", "persistent": persistent and not stale and not conflicts, "direction": "rising" if follow[-1] > baseline[-1] else "falling" if follow[-1] < baseline[-1] else "flat", "momentum": "rising" if median(differences) > 0 else "falling" if median(differences) < 0 else "flat", "acceleration": "rising" if len(differences) >= 2 and differences[-1] > differences[-2] else "falling" if len(differences) >= 2 and differences[-1] < differences[-2] else "flat"})
    if persistent:
        result["anomalies"].append({"type": "sustained_deviation", "direction": "above_baseline" if deviations[-1] > 0 else "below_baseline", "periods": [r["date"].isoformat() for r in usable[-persistent_n:]], "supporting_observations": [_public(r) for r in usable[-persistent_n:]], "baseline_periods": [_public(r) for r in usable[-(baseline_n + persistent_n):-persistent_n]], "why": "Each of several independent reporting periods departed from the earlier baseline in the same direction; no economic cause is inferred."})
        earlier_slope = baseline[-1] - baseline[0]
        recent_slope = follow[-1] - follow[0]
        if earlier_slope * recent_slope < 0:
            result["anomalies"].append({"type": "direction_change", "periods": [r["date"].isoformat() for r in usable[-persistent_n:]], "supporting_observations": [_public(r) for r in usable[-persistent_n:]], "why": "The recent direction differs from the baseline direction; this is not evidence of a causal regime change."})
        earlier_steps = [b - a for a, b in zip(baseline, baseline[1:])]
        recent_steps = [b - a for a, b in zip(follow, follow[1:])]
        if abs(median(recent_steps) - median(earlier_steps)) >= config["momentum_change_scale"] * scale:
            result["anomalies"].append({"type": "momentum_change", "periods": [r["date"].isoformat() for r in usable[-persistent_n:]], "supporting_observations": [_public(r) for r in usable[-persistent_n:]], "why": "The recent period-to-period change differs from the prior median change; persistence and economics need separate review."})
        if len(recent_steps) >= 2 and abs(recent_steps[-1] - recent_steps[-2]) >= config["acceleration_change_scale"] * scale:
            result["anomalies"].append({"type": "acceleration_change", "periods": [r["date"].isoformat() for r in usable[-persistent_n:]], "supporting_observations": [_public(r) for r in usable[-persistent_n:]], "why": "The most recent change in slope exceeds the baseline scale; this is descriptive, not predictive."})
        if shift >= config["break_deviation"]:
            result["anomalies"].append({"type": "provisional_structural_break", "direction": "up" if deviations[-1] > 0 else "down", "periods": [r["date"].isoformat() for r in usable[-persistent_n:]], "supporting_observations": [_public(r) for r in usable[-persistent_n:]], "why": "The follow-up median differs from the prior baseline; definition changes and reporting gaps remain alternatives."})
    elif isolated:
        result["anomalies"].append({"type": "isolated_deviation", "periods": [usable[-1]["date"].isoformat()], "supporting_observations": [_public(usable[-1])], "why": "Only the latest observation departed; persistence is unconfirmed."})
    return result


def _relationships(series, config):
    found = []
    for pair in config["relationships"]:
        left, right = series.get(pair["left"]), series.get(pair["right"])
        if not left or not right or not left["persistent"] or not right["persistent"]:
            continue
        if abs((datetime.fromisoformat(left["latest_period"]) - datetime.fromisoformat(right["latest_period"])).days) > pair["max_lag_days"]:
            continue
        lsign = next(a for a in left["anomalies"] if a["type"] == "sustained_deviation")["direction"]
        rsign = next(a for a in right["anomalies"] if a["type"] == "sustained_deviation")["direction"]
        if lsign != pair["left_direction"] or rsign != pair["right_direction"]:
            continue
        if (pair["pattern"] == "same_direction" and lsign != rsign) or (pair["pattern"] == "opposing_persistence" and lsign == rsign):
            continue
        evidence = left["anomalies"][0]["supporting_observations"] + right["anomalies"][0]["supporting_observations"]
        key = f"{config['version']}:{pair['id']}:{left['latest_period']}:{right['latest_period']}"
        found.append({"key": key, "relationship_id": pair["id"], "status": "provisional_unexplained", "question": pair["question"], "observations": evidence, "competing_explanations": pair["competing"], "limitations": "Temporal co-occurrence and configured economic relevance do not establish causation; independent actor-response evidence is required.", "hypothesis": {"initial_disturbance": f"Persistent {pair['left']} {lsign.replace('_baseline', '')} baseline and {pair['right']} {rsign.replace('_baseline', '')} baseline.", "actors": pair["actors"], "incentives": pair["incentives"], "proposed_reinforcing_mechanism": pair["proposed_reinforcement"], "potential_balancing_mechanism": pair["balancing"], "transmission_channels": pair["channels"], "leading_indicators": [pair["left"]], "lagging_indicators": [pair["right"]], "competing_explanations": pair["competing"], "confirmation_needed": pair["confirm"], "falsification_conditions": pair["falsify"], "implications_1_3_months": "Conditional: monitor whether actor responses reinforce the observed disturbance; direction unresolved.", "implications_3_6_months": "Conditional: repeated independent releases and balancing forces determine durability; direction unresolved.", "causal_status": "unverified_proposal"}})
    return found


def evaluate(session, as_of: datetime, knowledge_mode="system_known", include_test_fixtures=False):
    if as_of.tzinfo is None or knowledge_mode not in {"system_known", "source_known"}:
        raise ValueError("Timezone-aware as_of and explicit knowledge mode required")
    config = rules()
    rows = _inputs(session, as_of, knowledge_mode, include_test_fixtures)
    grouped = defaultdict(list)
    for row in rows:
        grouped[row["series"]].append(row)
    series = {key: _series(key, group, as_of, config) for key, group in sorted(grouped.items())}
    relationships = _relationships(series, config)
    vintages = [{"kind": row["kind"], "id": row["id"], "revision": row["revision"]} for row in sorted(rows, key=lambda x: (x["kind"], x["id"]))]
    return {"as_of": as_of.isoformat(), "knowledge_mode": knowledge_mode, "analysis_basis": "retrospective_source_reconstruction" if knowledge_mode == "source_known" else "system_known_research", "rule_version": config["version"], "series": series, "persistent_anomalies": [item for item in series.values() if item["persistent"]], "relationships": relationships, "candidate_hypotheses": relationships, "input_vintages": vintages, "limitations": "Statistical anomalies and co-occurrence are research leads, never established feedback loops or investment forecasts. Source-known history may include data ingested later; system-known history does not.", "source_coverage": {"numeric_series": len(series), "unavailable_relationships": [pair["id"] for pair in config["relationships"] if pair["id"] not in {r["relationship_id"] for r in relationships}]}}


def persist(session, as_of, key, operator, knowledge_mode="system_known", recorded_at=None):
    recorded_at = recorded_at or datetime.now(timezone.utc)
    if as_of > recorded_at or recorded_at.tzinfo is None:
        raise ValueError("Invalid discovery snapshot time")
    prior = session.scalar(select(DiscoverySnapshot).where(DiscoverySnapshot.snapshot_key == key))
    if prior:
        if prior.as_of != as_of or prior.knowledge_mode != knowledge_mode:
            raise ValueError("Snapshot key already names a different evaluation")
        return prior
    result = evaluate(session, as_of, knowledge_mode)
    config = rules()
    row = DiscoverySnapshot(snapshot_key=key, as_of=as_of, recorded_at=recorded_at, knowledge_mode=knowledge_mode, rule_version=config["version"], rules_json=json.dumps(config, sort_keys=True), input_vintages_json=json.dumps(result["input_vintages"], sort_keys=True), result_json=json.dumps(result, sort_keys=True), recorded_by=operator)
    session.add(row)
    session.flush()
    return row


def replay(row):
    return {"id": row.id, "snapshot_key": row.snapshot_key, "recorded_at": row.recorded_at.isoformat(), "rule_version": row.rule_version, "rules": json.loads(row.rules_json), "input_vintages": json.loads(row.input_vintages_json), "result": json.loads(row.result_json), "analysis_basis": "stored_discovery_snapshot"}
