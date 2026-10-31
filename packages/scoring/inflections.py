"""Explainable multi-signal alerts with persistence and recovery hysteresis."""
import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from packages.domain.calendar import recent_sessions
from packages.domain.config import rules
from packages.domain.models import AlertTransition
from packages.domain.store import observations_at
from .engine_v2 import _core


def _times(session, rule, as_of, demo, vintage_mode):
    if rule.get("cadence") == "publication":
        rows = observations_at(session, "it_major_usd_revenue_growth", as_of, vintage_mode, demo)
        return [min(as_of, (r.published_at if vintage_mode == "source_known" else r.ingested_at) + timedelta(minutes=1)) for r in rows[-4:]]
    tz = ZoneInfo("Asia/Kolkata")
    dates = recent_sessions(as_of.astimezone(tz), "india", 15)
    times = [datetime.combine(day, time(23, 59), tz) for day in dates]
    return [min(as_of, instant) for instant in times if instant <= as_of or instant.date() == as_of.astimezone(tz).date()]


def _evidence(metrics, rule):
    by_id = {m["id"]: m for m in metrics}
    evidence = []
    for id, condition in rule["conditions"].items():
        metric = by_id[id]
        value = metric["scored_feature"]
        result = None if value is None else (value >= condition["value"] if condition["op"] == "gte" else value <= condition["value"])
        evidence.append({"indicator_id": id, "observed": value, "required": condition["value"], "operator": condition["op"], "result": result, "published_at": metric["published_at"], "period_end": metric["period_end"], "provider": metric["provider"], "quality": metric["quality"], "status": metric["status"]})
    return evidence


def status_for_evaluations(checks, rule):
    """Pure lifecycle reducer; unknown inputs never count as recovery."""
    status = "UNKNOWN"
    watch = trigger = confirm = recovery = 0
    for known, triggered in checks:
        if known < rule["min_known"]:
            watch = trigger = confirm = 0
            if status not in {"WATCH", "TRIGGERED", "CONFIRMED"}:
                status = "UNKNOWN"
            continue
        if triggered >= rule["watch_count"]:
            watch += 1
            trigger = trigger + 1 if triggered >= rule["trigger_count"] else 0
            confirm = confirm + 1 if triggered >= rule["confirm_count"] else 0
            recovery = 0
            if confirm >= rule["confirm_days"]:
                status = "CONFIRMED"
            elif trigger >= rule["trigger_days"] and status != "CONFIRMED":
                status = "TRIGGERED"
            elif watch >= rule["watch_days"] and status not in {"TRIGGERED", "CONFIRMED"}:
                status = "WATCH"
        else:
            watch = trigger = confirm = 0
            if status in {"WATCH", "TRIGGERED", "CONFIRMED"}:
                recovery += 1
                if recovery >= rule["recovery_days"]:
                    status = "RESOLVED"
            else:
                status = "RESOLVED"
    return status, watch, recovery


def evaluate_v2(session, as_of: datetime, demo=False, vintage_mode="system_known"):
    output = []
    cache = {}
    for rule in rules("v2")["alerts"]:
        checks = []
        latest_evidence = []
        evaluated_at = as_of
        for instant in _times(session, rule, as_of, demo, vintage_mode):
            key = instant.isoformat()
            if key not in cache:
                cache[key] = _core(session, instant, demo, vintage_mode)["metrics"]
            evidence = _evidence(cache[key], rule)
            known = sum(e["result"] is not None for e in evidence)
            triggered = sum(e["result"] is True for e in evidence)
            checks.append((known, triggered))
            latest_evidence = evidence
            evaluated_at = instant
        status, watch, recovery = status_for_evaluations(checks, rule)
        output.append({"id": f"{rule['id']}:v2:IN:{'demo' if demo else 'live'}", "rule_id": rule["id"], "label": rule["label"], "ruleset_version": "v2", "status": status, "severity": status if status in {"WATCH", "TRIGGERED", "CONFIRMED"} else None, "demo": demo, "triggered_at": evaluated_at.isoformat() if status in {"WATCH", "TRIGGERED", "CONFIRMED"} else None, "evaluated_at": as_of.isoformat(), "persistence_count": watch, "recovery_count": recovery, "evidence": latest_evidence, "counter_signals": [e for e in latest_evidence if e["result"] is False], "confirmation_conditions": [e for e in latest_evidence if e["result"] is not True], "invalidation_condition": f"Fewer than {rule['watch_count']} conditions for {rule['recovery_days']} evaluations", "confidence": "demo" if demo else "provisional" if sum(e["result"] is not None for e in latest_evidence) >= rule["min_known"] else "insufficient"})
    return output


def persist_transitions(session, alerts, as_of):
    inserted = 0
    for alert in alerts:
        latest = session.scalar(select(AlertTransition).where(AlertTransition.rule_id == alert["rule_id"], AlertTransition.ruleset_version == alert["ruleset_version"], AlertTransition.mode == ("demo" if alert["demo"] else "live")).order_by(AlertTransition.evaluated_at.desc()))
        if latest and latest.status == alert["status"]:
            continue
        key = f"{alert['rule_id']}:{alert['ruleset_version']}:{'demo' if alert['demo'] else 'live'}:{as_of.isoformat()}:{alert['status']}"
        session.add(AlertTransition(rule_id=alert["rule_id"], ruleset_version=alert["ruleset_version"], market="IN", mode="demo" if alert["demo"] else "live", status=alert["status"], evaluated_at=as_of, evidence_json=json.dumps(alert["evidence"]), deduplication_key=key))
        inserted += 1
    session.commit()
    return inserted
