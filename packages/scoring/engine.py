from datetime import datetime, timedelta, timezone
from math import isfinite
from packages.domain.config import registry, rules
from packages.domain.store import observations_at


def change_pct(current, previous):
    if previous is None or previous <= 0 or current is None or current <= 0:
        return None
    return 100 * (float(current) / float(previous) - 1)


def change_bps(current, previous):
    if current is None or previous is None:
        return None
    return 100 * (float(current) - float(previous))


def fpi_usd_return(local_return, fx_start, fx_end):
    if fx_start <= 0 or fx_end <= 0:
        return None
    return (1 + local_return) * fx_start / fx_end - 1


def oil_bill_sensitivity_usd_bn(delta_oil_usd_per_bbl, crude_import_mbpd):
    return delta_oil_usd_per_bbl * crude_import_mbpd * 365 / 1000


def risk(value, green, amber, red):
    if value is None or not isfinite(value):
        return None
    if green > red:
        value, green, amber, red = -value, -green, -amber, -red
    if value <= green:
        return max(0, 10 + 40 * (value - green) / (amber - green))
    if value <= amber:
        return 10 + 40 * (value - green) / (amber - green)
    if value <= red:
        return 50 + 40 * (value - amber) / (red - amber)
    return min(100, 90 + 40 * (value - red) / (red - amber))


def feature(rows, transform):
    values = [float(r.value) for r in rows]
    if not values:
        return None, []
    last = rows[-1]
    if transform == "raw":
        return values[-1], [last.id]
    if transform.startswith("change_pct_"):
        n = int(transform.rsplit("_", 1)[1])
        return (change_pct(values[-1], values[-n-1]), [rows[-n-1].id, last.id]) if len(values) > n else (None, [])
    if transform.startswith("change_bps_"):
        n = int(transform.rsplit("_", 1)[1])
        return (change_bps(values[-1], values[-n-1]), [rows[-n-1].id, last.id]) if len(values) > n else (None, [])
    if transform.startswith("rolling_mean_"):
        n = int(transform.rsplit("_", 1)[1])
        return (sum(values[-n:]) / n, [r.id for r in rows[-n:]]) if len(values) >= n else (None, [])
    if transform.startswith("rolling_sum_"):
        n = int(transform.rsplit("_", 1)[1])
        return (sum(values[-n:]), [r.id for r in rows[-n:]]) if len(values) >= n else (None, [])
    if transform == "percentile_252":
        if len(values) < 252:
            return None, []
        history = values[-252:]
        return 100 * sum(v <= values[-1] for v in history) / len(history), [r.id for r in rows[-252:]]
    if transform == "yoy_3m":
        if len(values) < 15:
            return None, []
        current = sum(values[-3:]) / 3
        previous = sum(values[-15:-12]) / 3
        return change_pct(current, previous), [r.id for r in rows[-15:]]
    return None, []


def fresh(row, definition, as_of):
    if row is None:
        return False
    published = row.published_at.replace(tzinfo=timezone.utc) if row.published_at.tzinfo is None else row.published_at
    age = as_of - published
    if age < timedelta(0):
        return False
    if definition["frequency"] == "business_daily":
        # A Friday close remains current until the next weekday close.
        expected = published
        while expected.date() < as_of.date():
            expected += timedelta(days=1)
            if expected.weekday() < 5 and expected <= as_of:
                return False
        return True
    return age.total_seconds() <= definition["max_age_hours"] * 3600


def compute(session, as_of: datetime, demo=True, vintage_mode="system_known"):
    cfg = rules()
    definitions = registry()
    metrics = []
    features = {}
    for id, definition in definitions.items():
        rows = observations_at(session, id, as_of, vintage_mode, demo)
        latest = rows[-1] if rows else None
        valid_freshness = fresh(latest, definition, as_of)
        value, ids = feature(rows, definition["transform"])
        status = "unavailable" if latest is None else ("demo" if valid_freshness else "stale")
        features[id] = value if valid_freshness else None
        metrics.append({"id": id, "display_name": definition["display_name"], "cycle": definition["cycle"], "unit": definition["unit"], "frequency": definition["frequency"], "status": status, "value": float(latest.value) if latest else None, "feature": value, "transform": definition["transform"], "observation_ids": ids, "period_start": latest.period_start.isoformat() if latest else None, "period_end": latest.period_end.isoformat() if latest else None, "published_at": latest.published_at.isoformat() if latest else None, "ingested_at": latest.ingested_at.isoformat() if latest else None, "provider": latest.provider if latest else None, "quality": latest.quality if latest else None, "vintage_id": latest.vintage_id if latest else None, "source_url": latest.source_url if latest else None, "provisional_threshold": True})
    cycles = []
    weighted_coverage = 0
    for cycle_id, cycle_weight in cfg["cycle_weights"].items():
        signals = cfg["cycle_signals"][cycle_id]
        contributors = []
        covered = 0
        numerator = 0
        for id, rule in signals.items():
            value = features[id]
            score = risk(value, rule["green"], rule["amber"], rule["red"]) if value is not None else None
            contributors.append({"indicator_id": id, "feature": value, "score": round(score, 2) if score is not None else None, "weight": rule["weight"], "status": "available" if score is not None else "unavailable"})
            if score is not None:
                covered += rule["weight"]
                numerator += score * rule["weight"]
        coverage = covered / 100
        weighted_coverage += cycle_weight * coverage
        score = round(numerator / covered, 2) if covered and coverage >= .7 else None
        cycles.append({"id": cycle_id, "weight": cycle_weight, "score": score, "coverage": coverage, "direction": "unknown", "status": "provisional" if score is not None else "insufficient", "confidence": "demo" if demo and score is not None else "insufficient", "adjustment": 0, "contributors": contributors})
    coverage = weighted_coverage / 100
    valid = {c["id"] for c in cycles if c["score"] is not None}
    # A missing cycle is not silently reweighted into a deceptively precise total.
    sufficient = coverage >= .75 and len(valid) >= 4 and {"fx", "flows", "earnings"} <= valid and len(valid) == len(cycles)
    overall_score = round(sum(c["score"] * c["weight"] for c in cycles) / 100, 2) if sufficient else None
    regime = "insufficient_data" if overall_score is None else next(label for limit, label in [(25, "Supportive"), (45, "Watchful"), (65, "Fragile"), (80, "High stress"), (100, "Reflexive stress")] if overall_score <= limit)
    return {"as_of": as_of.isoformat(), "mode": "demo" if demo else "live", "ruleset_version": cfg["version"], "overall": {"score": overall_score, "regime": regime, "coverage": round(coverage, 4)}, "cycles": cycles, "metrics": metrics, "source_health": {"stale_count": sum(m["status"] == "stale" for m in metrics), "unavailable_count": sum(m["status"] == "unavailable" for m in metrics)}, "warnings": ["Synthetic DEMO observations; no live trading interpretation", "Thresholds are provisional and not historically calibrated"] if demo else ["Thresholds are provisional and not historically calibrated"]}
