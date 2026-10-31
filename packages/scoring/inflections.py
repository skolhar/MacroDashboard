"""Explainable multi-signal alerts with persistence and recovery hysteresis."""
import json
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo
from sqlalchemy import select
from packages.domain.calendar import recent_sessions
from packages.domain.config import rules
from packages.domain.models import AlertTransition, Observation
from .engine_v2 import _core


def release_instants(rows, as_of, vintage_mode):
    """Use the first known vintage of each quarter as its release clock."""
    releases = {}
    for row in rows:
        known_at = row.published_at if vintage_mode == "source_known" else max(row.published_at, row.ingested_at)
        if known_at <= as_of:
            releases[row.period_end] = min(known_at, releases.get(row.period_end, known_at))
    return sorted(min(as_of, instant + timedelta(minutes=1)) for instant in releases.values())[-8:]


def _times(session, rule, as_of, demo, vintage_mode):
    if rule.get("cadence") == "publication":
        query = select(Observation).where(Observation.indicator_id == "it_major_usd_revenue_growth", Observation.published_at <= as_of)
        if vintage_mode == "system_known":
            query = query.where(Observation.ingested_at <= as_of)
        elif vintage_mode != "source_known":
            raise ValueError("Invalid vintage mode")
        query = query.where(Observation.quality == "demo" if demo else (Observation.quality != "demo") & Observation.is_demo.is_(False))
        return release_instants(session.scalars(query).all(), as_of, vintage_mode)
    tz = ZoneInfo("Asia/Kolkata")
    dates = recent_sessions(as_of.astimezone(tz), "india", 60)
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
    unit = "releases" if rule.get("cadence") == "publication" else "days"
    watch_limit = rule[f"watch_{unit}"]
    trigger_limit = rule[f"trigger_{unit}"]
    confirm_limit = rule[f"confirm_{unit}"]
    recovery_limit = rule[f"recovery_{unit}"]
    for known, triggered in checks:
        if known < rule["min_known"]:
            watch = trigger = confirm = recovery = 0
            if status not in {"WATCH", "TRIGGERED", "CONFIRMED"}:
                status = "UNKNOWN"
            continue
        if triggered >= rule["watch_count"]:
            watch += 1
            trigger = trigger + 1 if triggered >= rule["trigger_count"] else 0
            confirm = confirm + 1 if triggered >= rule["confirm_count"] else 0
            recovery = 0
            if confirm >= confirm_limit:
                status = "CONFIRMED"
            elif trigger >= trigger_limit and status != "CONFIRMED":
                status = "TRIGGERED"
            elif watch >= watch_limit and status not in {"TRIGGERED", "CONFIRMED"}:
                status = "WATCH"
        else:
            watch = trigger = confirm = 0
            if status in {"WATCH", "TRIGGERED", "CONFIRMED"}:
                recovery += 1
                if recovery >= recovery_limit:
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
        unit = "releases" if rule.get("cadence") == "publication" else "days"
        output.append({"id": f"{rule['id']}:v2:IN:{'demo' if demo else 'live'}", "rule_id": rule["id"], "label": rule["label"], "ruleset_version": "v2", "status": status, "severity": status if status in {"WATCH", "TRIGGERED", "CONFIRMED"} else None, "demo": demo, "triggered_at": evaluated_at.isoformat() if status in {"WATCH", "TRIGGERED", "CONFIRMED"} else None, "evaluated_at": as_of.isoformat(), "persistence_count": watch, "recovery_count": recovery, "evidence": latest_evidence, "counter_signals": [e for e in latest_evidence if e["result"] is False], "confirmation_conditions": [e for e in latest_evidence if e["result"] is not True], "invalidation_condition": f"Fewer than {rule['watch_count']} conditions for {rule[f'recovery_{unit}']} {unit}", "confidence": "demo" if demo else "provisional" if sum(e["result"] is not None for e in latest_evidence) >= rule["min_known"] else "insufficient"})
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
