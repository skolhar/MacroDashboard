"""Private qualitative mechanism assessment with dated, reproducible snapshots."""
from datetime import datetime, timedelta, timezone
from pathlib import Path
import json
import yaml
from sqlalchemy import select
from packages.domain.models import ResearchEvidence, ResearchInterpretation, CycleAssessmentSnapshot
from packages.domain.store import observations_at
from packages.domain.settings import settings
from packages.market.operations import history_at, status_at
from packages.market.base import instruments

CATALOG_PATH = Path(__file__).resolve().parents[2] / "config/cycle_mechanisms.v1.yaml"
RULES_PATH = Path(__file__).resolve().parents[2] / "config/cycle_evaluation.v2.yaml"
MARKETS = {"nifty50": "Nifty 50", "wti_front_yahoo": "WTI global futures proxy", "brent_front_yahoo": "Brent global futures proxy", "usd_inr_yahoo": "Yahoo USD/INR", "gold_front_yahoo": "Gold global futures proxy"}
CHANNELS = {
    "fx": {"nifty50": "adverse", "usd_inr_yahoo": "upward", "gold_front_yahoo": "supportive in INR terms"},
    "energy": {"nifty50": "adverse", "brent_front_yahoo": "upward if supply-led", "wti_front_yahoo": "upward if supply-led", "usd_inr_yahoo": "upward"},
    "flows": {"nifty50": "supportive"},
    "earnings": {"nifty50": "supportive"},
    "it": {"nifty50": "adverse for IT exposure", "usd_inr_yahoo": "conditional upward"},
    "global": {"nifty50": "conditional supportive", "gold_front_yahoo": "conditional adverse", "usd_inr_yahoo": "conditional downward"},
}
HORIZON_NOTES = {
    "fx": ("Foreign-flow and dollar-demand response may appear within weeks.", "External financing and imported-cost effects need repeated releases."),
    "energy": ("Oil import costs can affect near-term sentiment and margins.", "Inflation and policy pass-through may dominate later; demand response can offset."),
    "flows": ("Incremental fund buying or redemption can affect liquidity quickly.", "A durable change in saving behavior needs multiple monthly releases."),
    "earnings": ("Analyst revisions can change valuation expectations quickly.", "Realized earnings and capital spending require subsequent quarters."),
    "it": ("Deal and pricing commentary is an early, uncertain sign.", "USD revenue, exports and employment need distinct quarterly releases."),
    "global": ("Cross-border risk appetite can respond quickly.", "Credit and capex transmission requires independent follow-up."),
}


def catalog():
    cfg = yaml.safe_load(CATALOG_PATH.read_text())
    if cfg.get("version") != "cycle-mechanisms-v1" or set(cfg.get("cycles", {})) != set(CHANNELS):
        raise ValueError("Unsupported cycle catalog")
    return cfg


def evaluation_rules():
    cfg = yaml.safe_load(RULES_PATH.read_text())
    if cfg.get("version") != "cycle-evaluation-v2":
        raise ValueError("Unsupported cycle evaluation rules")
    return cfg


def _known_inputs(session, as_of):
    raw = session.scalars(select(ResearchEvidence).where(ResearchEvidence.retrieved_at <= as_of, ResearchEvidence.period_end <= as_of.date())).all()
    raw = [o for o in raw if o.published_at is None or o.published_at <= as_of]
    latest = {}
    for o in sorted(raw, key=lambda x: (x.retrieved_at, x.id)):
        latest[(o.indicator_key, o.source_name, o.period_end)] = o
    observations = {o.id: o for o in latest.values()}
    conflicts = set()
    by_series = {}
    for o in observations.values():
        by_series.setdefault((o.indicator_key, o.period_end), []).append(o)
    for group in by_series.values():
        if len({(str(o.value_numeric), o.value_text, o.unit) for o in group}) > 1:
            conflicts.update(o.id for o in group)
    claims = session.scalars(select(ResearchInterpretation).where(ResearchInterpretation.assessed_at <= as_of)).all()
    claims = [i for i in claims if i.observation_id in observations and (i.related_observation_id is None or i.related_observation_id in observations)]
    superseded = {i.supersedes_id for i in claims if i.supersedes_id is not None}
    claims = [i for i in claims if i.id not in superseded]
    return observations, claims, conflicts


def _fresh(o, as_of, rules):
    return (as_of.date() - o.period_end).days <= rules["freshness_days"][o.frequency]


def _item(i, observations):
    o = observations[i.observation_id]
    related = observations.get(i.related_observation_id)
    return {"id": i.id, "observation_id": o.id, "related_observation_id": related.id if related else None, "observation_revision": o.revision_id, "interpretation_revision": i.revision_id, "mechanism_id": i.mechanism_id, "claim": o.indicator_or_claim, "indicator_key": o.indicator_key, "value": o.value_text, "value_numeric": float(o.value_numeric) if o.value_numeric is not None else None, "unit": o.unit, "period_end": o.period_end.isoformat(), "frequency": o.frequency, "source": o.source_name, "source_reference": o.source_reference, "retrieved_at": o.retrieved_at.isoformat(), "published_at": o.published_at.isoformat() if o.published_at else None, "reliability_note": o.reliability_note, "quality": o.quality, "stance": i.stance, "evidence_type": i.evidence_type, "rationale": i.rationale, "alternatives": json.loads(i.alternatives_json)}


def _mechanism_assessment(mechanism, claims, observations, raw_conflicts, as_of, rules):
    relevant = [i for i in claims if i.mechanism_id == mechanism["id"]]
    stale = [i for i in relevant if not _fresh(observations[i.observation_id], as_of, rules) or (i.related_observation_id is not None and not _fresh(observations[i.related_observation_id], as_of, rules))]
    fresh = [i for i in relevant if i not in stale]
    groups = {}
    for i in fresh:
        groups.setdefault((i.observation_id, i.evidence_type), []).append(i)
    conflicts = [i for group in groups.values() if len({x.stance for x in group}) > 1 for i in group]
    conflicts += [i for i in fresh if i.observation_id in raw_conflicts or i.related_observation_id in raw_conflicts]
    conflict_ids = {i.id for i in conflicts}
    selected = [max(group, key=lambda i: (i.assessed_at, i.id)) for group in groups.values() if not any(i.id in conflict_ids for i in group)]
    selected.sort(key=lambda i: (observations[i.observation_id].period_end, i.id))
    support = [i for i in selected if i.stance == "supports"]
    counter = [i for i in selected if i.stance == "contradicts"]
    if mechanism["role"] == "reinforcing":
        links = [i for i in support if i.evidence_type == "feedback_link"]
        trends = [i for i in support if i.evidence_type == "trend"]
        valid_links = [i for i in links if any(observations[t.observation_id].indicator_key not in {observations[i.observation_id].indicator_key, observations[i.related_observation_id].indicator_key} for t in trends)]
        broken = [i for i in counter if i.evidence_type == "feedback_link"]
        if conflicts:
            status = "conflicting"
        elif valid_links and broken and max(observations[i.observation_id].period_end for i in valid_links) == max(observations[i.observation_id].period_end for i in broken):
            status = "conflicting"
        elif valid_links and broken:
            status = "contradicted" if max(observations[i.observation_id].period_end for i in broken) > max(observations[i.observation_id].period_end for i in valid_links) else "supported"
        elif broken:
            status = "contradicted"
        elif valid_links:
            status = "supported"
        elif trends:
            status = "directional_only"
        elif stale:
            status = "stale"
        else:
            status = "missing"
        causal = valid_links
        reversal = broken
    else:
        causal = [i for i in support if i.evidence_type in {"corrective_response", "policy_response"}]
        reversal = [i for i in counter if i.evidence_type in {"corrective_response", "policy_response"}]
        same_period = causal and reversal and max(observations[i.observation_id].period_end for i in causal) == max(observations[i.observation_id].period_end for i in reversal)
        status = "conflicting" if conflicts or same_period else "supported" if causal and (not reversal or max(observations[i.observation_id].period_end for i in causal) > max(observations[i.observation_id].period_end for i in reversal)) else "contradicted" if reversal else "stale" if stale else "missing"
    return {"id": mechanism["id"], "role": mechanism["role"], "status": status, "supporting_evidence": [_item(i, observations) for i in support], "contradictory_evidence": [_item(i, observations) for i in counter], "conflicting_evidence": [_item(i, observations) for i in conflicts], "stale_evidence": [_item(i, observations) for i in stale], "_causal": causal, "_reversal": reversal}


def _prior_regime(session, cycle_id, as_of, catalog_version, rule_version, first_transition):
    if not first_transition:
        return None
    query = select(CycleAssessmentSnapshot).where(CycleAssessmentSnapshot.as_of < first_transition, CycleAssessmentSnapshot.recorded_at < first_transition, CycleAssessmentSnapshot.catalog_version == catalog_version, CycleAssessmentSnapshot.rule_version == rule_version).order_by(CycleAssessmentSnapshot.as_of.desc(), CycleAssessmentSnapshot.id.desc())
    for snap in session.scalars(query):
        previous = next((c for c in json.loads(snap.result_json)["cycles"] if c["id"] == cycle_id), None)
        if previous and previous["state"] in {"emerging", "strengthening", "mature / persistent"} and previous["reinforcing"]["status"] == "supported":
            return snap
    return None


def _cycle(session, cycle_id, definition, claims, observations, raw_conflicts, as_of, cfg, rules):
    assessments = [_mechanism_assessment(m, [i for i in claims if i.cycle_id == cycle_id], observations, raw_conflicts, as_of, rules) for m in definition["mechanisms"]]
    reinforcing = next(a for a in assessments if a["role"] == "reinforcing")
    balancing = next(a for a in assessments if a["role"] == "balancing")
    r_links = reinforcing["_causal"]
    r_broken = reinforcing["_reversal"]
    b_active = balancing["_causal"]
    periods = lambda items: len({observations[i.observation_id].period_end for i in items})
    ordered = lambda items: sorted(items, key=lambda i: (observations[i.observation_id].period_end, i.id))
    first_transition = min((observations[i.observation_id].retrieved_at for i in r_broken), default=None)
    prior = _prior_regime(session, cycle_id, as_of, cfg["version"], rules["version"], first_transition)
    first_new_support = max((observations[i.observation_id].retrieved_at for i in r_links), default=None)
    prior_support = _prior_regime(session, cycle_id, as_of, cfg["version"], rules["version"], first_new_support)
    later_broken = [i for i in r_broken if prior and observations[i.observation_id].retrieved_at > prior.recorded_at]
    later_balance = [i for i in b_active if prior and observations[i.observation_id].retrieved_at > prior.recorded_at]
    first_break_day = min((observations[i.observation_id].period_end for i in later_broken), default=None)
    sequenced_balance = [i for i in later_balance if first_break_day and observations[i.observation_id].period_end >= first_break_day]
    if "conflicting" in {reinforcing["status"], balancing["status"]}:
        state = "conflicting"
    elif prior and reinforcing["status"] == "contradicted" and balancing["status"] == "supported" and later_broken and sequenced_balance:
        state = "reversing" if periods(later_broken) >= rules["transition"]["reversing_feedback_periods"] and periods(sequenced_balance) >= rules["transition"]["reversing_balancing_periods"] else "weakening"
    elif reinforcing["status"] == "supported" and balancing["status"] != "supported":
        state = "strengthening" if prior_support and next(c for c in json.loads(prior_support.result_json)["cycles"] if c["id"] == cycle_id)["state"] == "emerging" else "mature / persistent" if periods(r_links) >= rules["transition"]["mature_feedback_periods"] else "emerging"
    else:
        state = "indeterminate"
    candidate = None
    if state in {"weakening", "reversing"} and periods(sequenced_balance) >= rules["transition"]["candidate_balancing_periods"]:
        kind = "balancing_force_dominance" if state == "reversing" else "reinforcing_force_losing_momentum"
        start = observations[ordered(sequenced_balance)[0].observation_id].period_end
        candidate = {"key": f"{cycle_id}:{kind}:{start.isoformat()}", "cycle_id": cycle_id, "type": kind, "status": "research_candidate", "supporting_observations": [_item(i, observations) for i in later_broken + sequenced_balance], "contradictory_evidence": reinforcing["supporting_evidence"] + balancing["contradictory_evidence"], "why_inflection": "A recorded reinforcing regime preceded a broken feedback link and later corrective responses across distinct reporting periods.", "confirmation_required": "Confirm the actor response with another release or independent mechanism; review alternative explanations.", "expected_consequences": definition["market_channels"], "invalidation": definition["invalidated_when"], "competing_explanations": definition["alternatives"], "prior_assessment_id": prior.id, "catalog_version": cfg["version"], "rule_version": rules["version"]}
    for assessment in assessments:
        assessment.pop("_causal")
        assessment.pop("_reversal")
    explanation = f"{definition['name']}: {state}. Reinforcing mechanism {reinforcing['status']}; balancing mechanism {balancing['status']}. Prior established assessment: {prior.id if prior else 'none'}. Trend evidence alone cannot prove a feedback loop."
    return {"id": cycle_id, "name": definition["name"], "state": state, "material": bool(candidate) or state == "conflicting", "explanation": explanation, "reinforcing": reinforcing, "balancing": balancing, "supporting_evidence": reinforcing["supporting_evidence"] + balancing["supporting_evidence"], "contradictory_evidence": reinforcing["contradictory_evidence"] + balancing["contradictory_evidence"], "conflicting_source_observations": reinforcing["conflicting_evidence"] + balancing["conflicting_evidence"], "missing_mechanisms": [a["id"] for a in assessments if a["status"] in {"missing", "stale", "directional_only"}], "competing_explanations": definition["alternatives"], "invalidation": definition["invalidated_when"], "candidate": candidate, "catalog_version": cfg["version"], "rule_version": rules["version"], "prior_assessment_id": prior.id if prior else None}


def _market_confirmation(session, as_of, provider):
    output = {}
    specs = instruments()
    for instrument_id, label in MARKETS.items():
        rows = [r for r in history_at(session, instrument_id, provider, as_of) if r.session_date >= (as_of - timedelta(days=95)).date()]
        health = status_at(session, specs[instrument_id], provider, as_of)
        if len(rows) < 2:
            status = health["status"] if not rows and health["status"] == "SOURCE_FAILED" else "DATA_UNAVAILABLE" if not rows else "INCOMPLETE_STALE" if health["status"] in {"STALE", "SOURCE_FAILED_USING_PRIOR_BAR"} else "INCOMPLETE"
            output[instrument_id] = {"label": label, "status": status, "last_session": health["last_session_date"], "age_calendar_days": health["age_calendar_days"], "interpretation": "Insufficient or stale dated bars; price cannot create a cycle thesis."}
            continue
        first, last = rows[0], rows[-1]
        status = health["status"]
        output[instrument_id] = {"label": label, "status": status, "first_session": first.session_date.isoformat(), "last_session": last.session_date.isoformat(), "age_calendar_days": health["age_calendar_days"], "change_pct": round(float((last.close / first.close - 1) * 100), 2) if first.close else None, "source": last.source_url, "retrieved_at": last.retrieved_at.isoformat(), "interpretation": "Stale or failed source is not current confirmation." if status in {"STALE", "SOURCE_FAILED_USING_PRIOR_BAR"} else "Vendor price response only; no causal attribution."}
    return output


def evaluate(session, as_of: datetime, demo=False):
    if as_of.tzinfo is None:
        raise ValueError("as_of requires timezone")
    cfg, rules = catalog(), evaluation_rules()
    observations, claims, raw_conflicts = ({}, [], set()) if demo else _known_inputs(session, as_of)
    verified = []
    if not demo:
        for indicator in ("us_10y_yield", "fx_gross_reserves_usd", "usd_inr_spot"):
            history = observations_at(session, indicator, as_of, "system_known", False)
            if history:
                row = history[-1]
                verified.append({"indicator_id": indicator, "value": float(row.value), "unit": row.unit, "period_end": row.period_end.isoformat(), "published_at": row.published_at.isoformat(), "source": row.source_reference or row.source_url, "quality": row.quality, "interpretation": "Observed fact only; no automatic causal stance"})
    cycles = [_cycle(session, cid, definition, claims, observations, raw_conflicts, as_of, cfg, rules) for cid, definition in cfg["cycles"].items()]
    market = {} if demo else _market_confirmation(session, as_of, settings().market_provider)
    outlooks = []
    for instrument_id, label in MARKETS.items():
        for horizon in ("1-3 months", "3-6 months"):
            active = [c for c in cycles if c["state"] in {"emerging", "strengthening", "mature / persistent", "weakening", "reversing"} and instrument_id in CHANNELS[c["id"]]]
            influences = [{"cycle_id": c["id"], "state": c["state"], "direction": CHANNELS[c["id"]][instrument_id] if c["state"] in {"emerging", "strengthening", "mature / persistent"} else "unresolved as the loop weakens", "influence": "material" if c["candidate"] else "secondary", "mechanism": cfg["cycles"][c["id"]]["thesis"], "horizon_reason": HORIZON_NOTES[c["id"]][0 if horizon == "1-3 months" else 1], "invalidation": c["invalidation"]} for c in active]
            outlooks.append({"instrument_id": instrument_id, "instrument": label, "horizon": horizon, "direction": "conditional / unresolved" if not influences or len({i["direction"] for i in influences}) > 1 else influences[0]["direction"], "influences": influences, "opposing_mechanisms": [c["name"] for c in cycles if c["balancing"]["status"] == "supported" and instrument_id in CHANNELS[c["id"]]], "priced_in": "unknown; secondary price history cannot establish expectations", "confirm_with": [cfg["cycles"][c["id"]]["strengthens_when"] for c in active], "invalidate_with": [c["invalidation"] for c in active], "uncertainty": "Research evidence incomplete; conditional scenario only" if not active else "Mechanism attribution and market expectations remain unverified", "market_confirmation": market.get(instrument_id, {"status": "DATA_UNAVAILABLE"}), "caveat": "WTI/Brent are global futures proxies, not MCX crude" if instrument_id in {"wti_front_yahoo", "brent_front_yahoo"} else "Yahoo FX quote is not an RBI/FBIL reference fixing" if instrument_id == "usd_inr_yahoo" else None})
    return {"as_of": as_of.isoformat(), "mode": "demo" if demo else "private_research", "analysis_basis": "recomputed_with_current_rules; use a stored assessment for historical rule-version replay", "catalog_version": cfg["version"], "rule_version": rules["version"], "cycles": cycles, "material_cycles": [c for c in cycles if c["material"]], "candidates": [c["candidate"] for c in cycles if c["candidate"]], "outlooks": outlooks, "market_confirmation": market, "verified_facts": verified, "evidence_count": len(observations), "interpretation_count": len(claims), "used_evidence_ids": sorted(observations), "used_interpretation_ids": sorted(i.id for i in claims), "warning": "Exploratory hypotheses, not forecasts, probabilities or recommendations; synthetic demo is never live evidence."}


def persist_assessment(session, as_of, assessment_key, recorded_by, recorded_at=None):
    recorded_at = recorded_at or datetime.now(timezone.utc)
    if as_of.tzinfo is None or recorded_at.tzinfo is None or as_of > recorded_at:
        raise ValueError("Assessment timestamps must be ordered and timezone-aware")
    existing = session.scalar(select(CycleAssessmentSnapshot).where(CycleAssessmentSnapshot.assessment_key == assessment_key))
    if existing:
        return existing
    result = evaluate(session, as_of)
    cfg, rules = catalog(), evaluation_rules()
    observations, claims, _ = _known_inputs(session, as_of)
    revisions = {"observations": {str(id): o.revision_id for id, o in observations.items()}, "interpretations": {str(i.id): i.revision_id for i in claims}}
    row = CycleAssessmentSnapshot(assessment_key=assessment_key, as_of=as_of, recorded_at=recorded_at, catalog_version=cfg["version"], catalog_json=json.dumps(cfg, sort_keys=True), rule_version=rules["version"], rules_json=json.dumps(rules, sort_keys=True), evidence_ids_json=json.dumps(result["used_evidence_ids"]), interpretation_ids_json=json.dumps(result["used_interpretation_ids"]), input_revisions_json=json.dumps(revisions, sort_keys=True), result_json=json.dumps(result, sort_keys=True), recorded_by=recorded_by)
    session.add(row)
    session.flush()
    return row


def replay_snapshot(row):
    return {"id": row.id, "assessment_key": row.assessment_key, "as_of": row.as_of.isoformat(), "recorded_at": row.recorded_at.isoformat(), "analysis_basis": "stored_point_in_time", "catalog_version": row.catalog_version, "rule_version": row.rule_version, "catalog": json.loads(row.catalog_json), "rules": json.loads(row.rules_json), "evidence_ids": json.loads(row.evidence_ids_json), "interpretation_ids": json.loads(row.interpretation_ids_json), "input_revisions": json.loads(row.input_revisions_json), "assessment": json.loads(row.result_json), "recorded_by": row.recorded_by}
