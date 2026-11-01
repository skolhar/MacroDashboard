"""Qualitative, falsifiable cycle research. Prices are confirmation only."""
from datetime import datetime, timedelta
from pathlib import Path
import yaml
from sqlalchemy import select
from packages.domain.models import ResearchEvidence
from packages.domain.store import observations_at
from packages.domain.settings import settings
from packages.market.operations import history_at

CATALOG_PATH = Path(__file__).resolve().parents[2] / "config/cycle_mechanisms.v1.yaml"
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
    result = yaml.safe_load(CATALOG_PATH.read_text())
    assert len(result["cycles"]) == 6
    return result


def _item(row):
    return {"id": row.id, "mechanism_id": row.mechanism_id, "claim": row.indicator_or_claim, "value": row.value_text, "value_numeric": float(row.value_numeric) if row.value_numeric is not None else None, "unit": row.unit, "period_end": row.period_end.isoformat(), "source": row.source_name, "source_reference": row.source_reference, "retrieved_at": row.retrieved_at.isoformat(), "published_at": row.published_at.isoformat() if row.published_at else None, "reliability_note": row.reliability_note, "usage_basis": row.usage_basis, "quality": row.quality, "stance": row.stance}


def _select(rows, as_of):
    """Latest claim per identity; old evidence is retained for persistence only."""
    eligible = [r for r in rows if r.retrieved_at <= as_of and (r.published_at is None or r.published_at <= as_of) and r.period_end <= as_of.date()]
    latest = {}
    for row in sorted(eligible, key=lambda r: (r.period_end, r.retrieved_at, r.id)):
        latest[(row.mechanism_id, row.indicator_or_claim, row.period_end, row.source_name)] = row
    return list(latest.values())


def _evaluate_cycle(cycle_id, definition, rows, as_of):
    window = 400 if cycle_id == "it" else 180
    eligible = [r for r in _select(rows, as_of) if r.period_end >= (as_of - timedelta(days=window)).date()]
    groups = {}
    for row in eligible:
        groups.setdefault((row.mechanism_id, row.indicator_or_claim, row.period_end), []).append(row)
    conflicts = [r for group in groups.values() if len({item.stance for item in group}) > 1 for r in group]
    recent = [max(group, key=lambda r: (r.retrieved_at, r.id)) for group in groups.values() if len({item.stance for item in group}) == 1]
    recent.sort(key=lambda r: (r.period_end, r.retrieved_at, r.id))
    mechanisms = {m["id"]: m for m in definition["mechanisms"]}
    reinforcing = [r for r in recent if mechanisms[r.mechanism_id]["role"] == "reinforcing"]
    balancing = [r for r in recent if mechanisms[r.mechanism_id]["role"] == "balancing"]
    r_support = [r for r in reinforcing if r.stance == "supports"]
    r_counter = [r for r in reinforcing if r.stance == "contradicts"]
    b_support = [r for r in balancing if r.stance == "supports"]
    b_counter = [r for r in balancing if r.stance == "contradicts"]
    periods = lambda items: len({r.period_end for r in items})
    prior_support = any(r.period_end < max((x.period_end for x in recent), default=as_of.date()) for r in r_support)
    if periods(r_counter) >= 2 and periods(b_support) >= 2 and prior_support:
        state = "reversing"
    elif r_counter and b_support and prior_support:
        state = "weakening"
    elif periods(r_support) >= 2 and not b_support:
        state = "mature / persistent"
    elif r_support and r_counter and r_support[-1].period_end > r_counter[-1].period_end:
        state = "strengthening"
    elif r_support and not b_support:
        state = "emerging"
    else:
        state = "indeterminate"
    current = [r for r in recent if r.period_end == max((x.period_end for x in recent), default=as_of.date())]
    supports = [_item(r) for r in current if r.stance == "supports"]
    contradictions = [_item(r) for r in current if r.stance == "contradicts"]
    missing = [m["id"] for m in definition["mechanisms"] if not any(r.mechanism_id == m["id"] for r in recent)]
    explanation = (f"{definition['name']}: {state}. Reinforcing evidence: {len(r_support)} support, {len(r_counter)} counter; balancing evidence: {len(b_support)} support, {len(b_counter)} counter across distinct observed periods. This is an interpretation, not proven causation.")
    candidate = None
    if state in {"weakening", "reversing"} and periods(b_support) >= 2:
        kind = "balancing_force_dominance" if state == "reversing" else "reinforcing_force_losing_momentum"
        candidate = {"key": f"{cycle_id}:{kind}:{min(r.period_end for r in b_support).isoformat()}", "cycle_id": cycle_id, "type": kind, "status": "research_candidate", "supporting_observations": [_item(r) for r in (r_counter + b_support)], "contradictory_evidence": [_item(r) for r in (r_support + b_counter)], "why_inflection": "Distinct observed periods show a balancing force alongside weakening reinforcement; ordinary one-off fluctuations do not meet this rule.", "confirmation_required": "Another independent period and source should corroborate the mechanism; compare policy and flows before upgrading the interpretation.", "expected_consequences": definition["market_channels"], "invalidation": definition["invalidated_when"], "competing_explanations": definition["alternatives"]}
    return {"id": cycle_id, "name": definition["name"], "state": state, "material": candidate is not None or state in {"strengthening", "reversing"} or bool(conflicts), "explanation": explanation, "reinforcing": {"supports": len(r_support), "contradicts": len(r_counter), "distinct_periods": periods(reinforcing)}, "balancing": {"supports": len(b_support), "contradicts": len(b_counter), "distinct_periods": periods(balancing)}, "supporting_evidence": supports, "contradictory_evidence": contradictions, "conflicting_source_observations": [_item(r) for r in conflicts], "missing_mechanisms": missing, "competing_explanations": definition["alternatives"], "invalidation": definition["invalidated_when"], "candidate": candidate, "catalog_version": "cycle-mechanisms-v1"}


def _market_confirmation(session, as_of, provider):
    output = {}
    for instrument_id, label in MARKETS.items():
        rows = history_at(session, instrument_id, provider, as_of)
        rows = [r for r in rows if r.session_date >= (as_of - timedelta(days=95)).date()]
        if len(rows) < 2:
            output[instrument_id] = {"label": label, "status": "DATA_UNAVAILABLE", "interpretation": "No market confirmation; price is never used to create a cycle thesis."}
            continue
        first, last = rows[0], rows[-1]
        output[instrument_id] = {"label": label, "status": "secondary_research", "first_session": first.session_date.isoformat(), "last_session": last.session_date.isoformat(), "change_pct": round(float((last.close / first.close - 1) * 100), 2) if first.close else None, "source": last.source_url, "retrieved_at": last.retrieved_at.isoformat(), "interpretation": "Observed vendor price response only; no causal attribution or price-only macro conclusion."}
    return output


def evaluate(session, as_of: datetime, demo=False):
    if as_of.tzinfo is None:
        raise ValueError("as_of requires timezone")
    cfg = catalog()
    rows = [] if demo else session.scalars(select(ResearchEvidence).where(ResearchEvidence.retrieved_at <= as_of)).all()
    # Governed source observations may be displayed as facts, but they do not
    # acquire a causal stance without a separately attributed research claim.
    verified = []
    if not demo:
        for indicator in ("us_10y_yield", "fx_gross_reserves_usd", "usd_inr_spot"):
            history = observations_at(session, indicator, as_of, "system_known", False)
            if history:
                row = history[-1]
                verified.append({"indicator_id": indicator, "value": float(row.value), "unit": row.unit, "period_end": row.period_end.isoformat(), "published_at": row.published_at.isoformat(), "source": row.source_reference or row.source_url, "quality": row.quality, "interpretation": "Observed fact only; no automatic causal stance"})
    cycles = [_evaluate_cycle(cid, definition, [r for r in rows if r.cycle_id == cid], as_of) for cid, definition in cfg["cycles"].items()]
    market = {} if demo else _market_confirmation(session, as_of, settings().market_provider)
    outlooks = []
    for instrument_id, label in MARKETS.items():
        for horizon in ("1-3 months", "3-6 months"):
            active = [c for c in cycles if c["state"] != "indeterminate" and instrument_id in CHANNELS[c["id"]]]
            influences = [{"cycle_id": c["id"], "state": c["state"], "direction": CHANNELS[c["id"]][instrument_id] if c["state"] not in {"weakening", "reversing"} else "unresolved as the loop weakens", "influence": "material" if c["candidate"] else "secondary", "mechanism": cfg["cycles"][c["id"]]["thesis"], "horizon_reason": HORIZON_NOTES[c["id"]][0 if horizon == "1-3 months" else 1], "invalidation": c["invalidation"]} for c in active]
            outlooks.append({"instrument_id": instrument_id, "instrument": label, "horizon": horizon, "direction": "conditional / unresolved" if not influences or len({i["direction"] for i in influences}) > 1 else influences[0]["direction"], "influences": influences, "opposing_mechanisms": [c["name"] for c in cycles if c["balancing"]["supports"] and instrument_id in CHANNELS[c["id"]]], "priced_in": "unknown; secondary price history cannot establish expectations", "confirm_with": [cfg["cycles"][c["id"]]["strengthens_when"] for c in active], "invalidate_with": [c["invalidation"] for c in active], "uncertainty": "Research evidence is incomplete; conditional scenario only" if not active else "Mechanism attribution and market expectations remain unverified", "market_confirmation": market.get(instrument_id, {"status": "DATA_UNAVAILABLE"}), "caveat": "WTI/Brent are global futures proxies, not MCX crude" if instrument_id in {"wti_front_yahoo", "brent_front_yahoo"} else "Yahoo FX quote is not an RBI/FBIL reference fixing" if instrument_id == "usd_inr_yahoo" else None})
    return {"as_of": as_of.isoformat(), "mode": "demo" if demo else "private_research", "catalog_version": cfg["version"], "cycles": cycles, "material_cycles": [c for c in cycles if c["material"]], "candidates": [c["candidate"] for c in cycles if c["candidate"]], "outlooks": outlooks, "market_confirmation": market, "verified_facts": verified, "evidence_count": len(rows), "warning": "Exploratory hypotheses, not forecasts, probabilities or recommendations; synthetic demo is never treated as live evidence."}
