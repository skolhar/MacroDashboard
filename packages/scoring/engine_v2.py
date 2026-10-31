"""Point-in-time six-cycle scoring; missing weight is never redistributed."""
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo
from packages.domain.calendar import market_for, sessions_between
from packages.domain.config import registry, rules
from packages.domain.store import observations_at
from .engine import feature, risk


def _freshness(row, definition, as_of, indicator_id):
    if row is None:
        return "DATA_UNAVAILABLE"
    if definition["frequency"] == "business_daily":
        market = market_for(indicator_id)
        local_now = as_of.astimezone(ZoneInfo("America/New_York" if market.startswith("us") else "Asia/Kolkata"))
        sessions = sessions_between(row.period_end, local_now.date(), market)
        if sessions is None:
            return "CALENDAR_UNVERIFIED"
        # The current session does not become stale until its expected close.
        close_hour = 18 if market == "india" else 17
        if sessions > 1 or (sessions == 1 and local_now.hour >= close_hour):
            return "stale"
    elif (as_of - row.published_at).total_seconds() > definition["max_age_hours"] * 3600:
        return "stale"
    return "demo" if row.quality == "demo" else row.quality


def covered_weighted_score(weighted_scores, minimum_coverage=0.7):
    """Normalize only observed signal weights; fail closed below coverage floor."""
    covered = sum(weight for score, weight in weighted_scores if score is not None)
    if covered < 100 * minimum_coverage or not covered:
        return None, covered / 100
    return round(sum(score * weight for score, weight in weighted_scores if score is not None) / covered, 2), covered / 100


def composite_score(cycles, coverage):
    """Use fixed cycle weights only when every configured cycle is scoreable."""
    if coverage < 0.75 or any(c["score"] is None for c in cycles) or sum(c["weight"] for c in cycles) != 100:
        return None
    return round(sum(c["score"] * c["weight"] for c in cycles) / 100, 2)


def _core(session, as_of, demo, vintage_mode):
    cfg = rules("v2")
    definitions = registry(phase2=True)
    metrics = []
    features = {}
    for id, definition in definitions.items():
        rows = observations_at(session, id, as_of, vintage_mode, demo)
        latest = rows[-1] if rows else None
        score_rows = [r for r in rows if demo or r.quality in {"verified", "revised"}]
        value, ids = feature(score_rows, definition["transform"])
        status = _freshness(latest, definition, as_of, id)
        valid = status in {"verified", "revised", "demo"} and value is not None
        features[id] = value if valid else None
        metrics.append({"id": id, "display_name": definition["display_name"], "cycle": definition["cycle"], "unit": definition["unit"], "frequency": definition["frequency"], "status": status, "value": float(latest.value) if latest else None, "feature": value, "scored_feature": features[id], "transform": definition["transform"], "observation_ids": ids, "period_start": latest.period_start.isoformat() if latest else None, "period_end": latest.period_end.isoformat() if latest else None, "published_at": latest.published_at.isoformat() if latest else None, "ingested_at": latest.ingested_at.isoformat() if latest else None, "provider": latest.provider if latest else None, "quality": latest.quality if latest else None, "vintage_id": latest.vintage_id if latest else None, "source_url": latest.source_reference or latest.source_url if latest else None, "provisional_threshold": True})
    cycles = []
    weighted_coverage = 0
    for cycle_id, cycle_weight in cfg["cycle_weights"].items():
        signals = cfg["cycle_signals"][cycle_id]
        contributors = []
        weighted_scores = []
        confirmations = 0
        for id, rule in signals.items():
            value = features.get(id)
            score = risk(value, rule["green"], rule["amber"], rule["red"]) if value is not None else None
            contributors.append({"indicator_id": id, "feature": value, "score": round(score, 2) if score is not None else None, "weight": rule["weight"], "status": "available" if score is not None else "unavailable", "thresholds": {k: rule[k] for k in ("green", "amber", "red")}})
            weighted_scores.append((score, rule["weight"]))
            if score is not None:
                confirmations += int(score >= 50)
        score, coverage = covered_weighted_score(weighted_scores)
        weighted_coverage += cycle_weight * coverage
        cycles.append({"id": cycle_id, "weight": cycle_weight, "score": score, "coverage": coverage, "level_risk": score, "confirmation": {"stressed_signals": confirmations, "available_signals": sum(c["score"] is not None for c in contributors)}, "confidence": "insufficient" if score is None else ("demo" if demo else "provisional" if coverage < 1 else "verified_inputs_provisional_rules"), "status": "insufficient" if score is None else "provisional", "adjustment": 0, "contributors": contributors, "reason": "Coverage below 70%" if score is None else None})
    coverage = weighted_coverage / 100
    overall_score = composite_score(cycles, coverage)
    sufficient = overall_score is not None
    regime = "insufficient_data" if overall_score is None else next(label for limit, label in [(25, "Supportive"), (45, "Watchful"), (65, "Fragile"), (80, "High stress"), (100, "Reflexive stress")] if overall_score <= limit)
    return {"as_of": as_of.isoformat(), "mode": "demo" if demo else "live", "ruleset_version": "v2", "overall": {"score": overall_score, "regime": regime, "coverage": round(coverage, 4), "reason": None if sufficient else "One or more required cycles lack 70% signal coverage; weights were not redistributed"}, "cycles": cycles, "metrics": metrics, "source_health": {"stale_count": sum(m["status"] == "stale" for m in metrics), "unavailable_count": sum(m["status"] == "DATA_UNAVAILABLE" for m in metrics), "calendar_unverified_count": sum(m["status"] == "CALENDAR_UNVERIFIED" for m in metrics)}, "warnings": ["Thresholds are provisional, not calibrated investment signals"] + (["Synthetic DEMO observations"] if demo else []), "features": features}


def compute_v2(session, as_of: datetime, demo=False, vintage_mode="system_known", with_momentum=True):
    current = _core(session, as_of, demo, vintage_mode)
    if with_momentum:
        prior = _core(session, as_of - timedelta(days=28), demo, vintage_mode)
        earlier = _core(session, as_of - timedelta(days=56), demo, vintage_mode)
        for index, cycle in enumerate(current["cycles"]):
            p, e = prior["cycles"][index]["score"], earlier["cycles"][index]["score"]
            score = cycle["score"]
            cycle["momentum"] = round(score - p, 2) if score is not None and p is not None else None
            cycle["acceleration"] = round(score - 2 * p + e, 2) if score is not None and p is not None and e is not None else None
            cycle["direction"] = "unknown" if cycle["momentum"] is None else "deteriorating" if cycle["momentum"] > 2 else "improving" if cycle["momentum"] < -2 else "stable"
        current["overall"]["prior_regime"] = prior["overall"]["regime"]
    current.pop("features")
    return current
