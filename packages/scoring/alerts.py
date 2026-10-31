from datetime import timedelta
from packages.domain.config import rules
from .engine import compute


def fx_alert(session, as_of, demo=True, vintage_mode="system_known"):
    rule = rules()["fx_alert"]
    checks = []
    for offset in range(7, -1, -1):
        day = as_of - timedelta(days=offset)
        if day.weekday() >= 5:
            continue
        evaluation_at = min(as_of, day.replace(hour=23, minute=59, second=59))
        snapshot = compute(session, evaluation_at, demo, vintage_mode)
        metrics = {m["id"]: m for m in snapshot["metrics"]}
        evidence = []
        true_count = 0
        known_count = 0
        for id, condition in rule["conditions"].items():
            metric = metrics[id]
            value = metric["feature"] if metric["status"] in {"demo", "verified", "revised"} else None
            if condition["op"] == "contextual":
                result = None
            elif value is None:
                result = None
            else:
                result = value >= condition["value"] if condition["op"] == "gte" else value <= condition["value"]
                known_count += 1
                true_count += int(result)
            evidence.append({"indicator_id": id, "observed": value, "required": condition["value"], "operator": condition["op"], "result": result, "published_at": metric["published_at"]})
        checks.append({"at": day.isoformat(), "qualifies": true_count >= rule["min_conditions"], "critical": true_count >= rule["critical_conditions"] and any(e["indicator_id"] == "usd_inr_spot" and e["result"] for e in evidence) and any(e["indicator_id"] == "fx_gross_reserves_usd" and e["result"] for e in evidence), "true_count": true_count, "known_count": known_count, "evidence": evidence})
    if not checks:
        return []
    streak = 0
    critical_streak = 0
    for check in checks:
        streak = streak + 1 if check["qualifies"] else 0
        critical_streak = critical_streak + 1 if check["critical"] else 0
    latest = checks[-1]
    if latest["known_count"] < rule["min_conditions"]:
        status = "UNKNOWN"
    elif critical_streak >= rule["critical_persistence_days"]:
        status = "CRITICAL"
    elif streak >= rule["persistence_days"]:
        status = "WATCH"
    elif latest["qualifies"]:
        status = "CANDIDATE"
    else:
        status = "INACTIVE"
    return [{"id": f"{rule['id']}:v1:IN:demo" if demo else f"{rule['id']}:v1:IN", "rule_id": rule["id"], "ruleset_version": "v1", "status": status, "severity": status if status in ("WATCH", "CRITICAL") else None, "demo": demo, "triggered_at": latest["at"] if status in ("WATCH", "CRITICAL") else None, "evaluated_at": as_of.isoformat(), "persistence_count": streak, "evidence": latest["evidence"], "confidence": "demo" if demo else "provisional", "counter_signals": [e for e in latest["evidence"] if e["result"] is False]}]
