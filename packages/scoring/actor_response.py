"""Provisional actor-response sequences from observed facts, never causal proof."""
from datetime import date, timedelta
from decimal import Decimal
from packages.connectors.rbi_research_mirror import registry

CREDIT = "rbi_mirror_bank_credit_cr"
DEPOSITS = "rbi_mirror_bank_deposits_cr"
LIQUIDITY = "rbi_mirror_net_injection_cr"

DESCRIPTIVE = "descriptive_observation"
CAUSAL = "causal_interpretation"


def _public(row):
    return {"kind": row["kind"], "id": row["id"], "series": row["series"], "period_end": row["date"].isoformat(), "value": float(row["value"]), "source_value_text": row.get("source_value_text"), "source": row["source"], "source_reference": row["reference"], "revision": row["revision"], "published_at": row["published_at"].isoformat() if row["published_at"] else None, "retrieved_at": row["retrieved_at"].isoformat(), "quality": row["quality"]}


def _add_evidence(result, rows):
    known = {(item["kind"], item["id"]) for item in result["observations"]}
    for row in rows:
        key = (row["kind"], row["id"])
        if key not in known:
            result["observations"].append(_public(row))
            known.add(key)


def _evidence_layers(divergence=False, operations=False, transmission=False, motivation=False, inflection=False):
    """Separate observed facts from interpretation so no layer is presented as proven."""
    return {
        "observed_divergence": {"observed": divergence, "note": "Credit and deposit YoY growth from fortnightly bank reports; the funding gap is an observed accounting divergence, not actor behavior."},
        "subsequent_operations": {"observed": operations, "note": "RBI liquidity operations separately dated after the divergence; reported values and injection/absorption labels are publisher-defined only and the operation motive is not observed."},
        "plausible_transmission": {"observed": transmission, "note": "A proposed liquidity-to-lending channel; not independently measured in the imported mirror data."},
        "documented_motivation": {"observed": motivation, "note": "A dated RBI statement or policy document stating the operation's objective; the mirror provides none."},
        "feedback_inflection": {"observed": inflection, "note": "Later bank reports showing the gap widen, narrow or close after operations; timing association only, and no causal direction is inferred."},
    }


LIQUIDITY_INTERPRETATION = {
    "classification": "unresolved_definition",
    "independently_validated": False,
    "sign_convention": "Publisher label: positive means net injection and negative means net absorption. The mirror cannot independently verify RBI's sign convention or formula.",
    "aggregation": "The imported column is RBI's published daily net across mixed operation types; offsetting instrument-level flows are not separately imported.",
    "measure": "The summed value is a cumulative signed net of reported daily operation flows, not a change in outstanding liquidity and not a liquidity stock.",
    "summation": "Summing daily observations is bookkeeping over a fixed reporting window, not an economically meaningful liquidity quantity.",
    "definition_risk": "RBI reporting-convention or definition changes could create false signals; the mirror definition was not independently validated.",
    "causal_boundary": "Aggregate operations must not be read as an intentional RBI response to a bank funding gap without independently dated policy rationale.",
}


def _series(rows, key, expected_frequency):
    periods = {}
    for row in rows:
        if row["series"] != key:
            continue
        if row["frequency"] != expected_frequency:
            raise ValueError(f"Incompatible reporting frequency for {key}")
        prior = periods.get(row["date"])
        if prior and (prior["value"] != row["value"] or prior["kind"] != row["kind"]):
            raise ValueError(f"Conflicting independent observations for {key} on {row['date']}")
        if not prior or row["retrieved_at"] > prior["retrieved_at"]:
            periods[row["date"]] = row
    return periods


def _growth(current, historical, day):
    target = day - timedelta(days=365)
    candidates = [d for d in historical if d < day and abs((d - target).days) <= 17]
    if not candidates or current["value"] <= 0:
        return None
    prior_day = min(candidates, key=lambda d: (abs((d - target).days), -d.toordinal()))
    prior = historical[prior_day]
    if prior["value"] <= 0:
        return None
    return (current["value"] / prior["value"] - 1) * Decimal(100), prior


def _gap_history(rows):
    credit, deposits = _series(rows, CREDIT, "fortnightly"), _series(rows, DEPOSITS, "fortnightly")
    gaps = []
    for day in sorted(credit.keys() & deposits.keys()):
        cg, dg = _growth(credit[day], credit, day), _growth(deposits[day], deposits, day)
        if cg is None or dg is None:
            continue
        gaps.append({"date": day, "gap_pp": cg[0] - dg[0], "credit_yoy_pct": cg[0], "deposit_yoy_pct": dg[0], "evidence": [credit[day], cg[1], deposits[day], dg[1]]})
    return gaps


def _bank_cadence(gaps):
    cadence = [(gaps[j]["date"] - gaps[j - 1]["date"]).days for j in range(1, len(gaps))]
    anomalies = [{"after": gaps[j - 1]["date"].isoformat(), "period_end": gaps[j]["date"].isoformat(), "gap_days": cadence[j - 1]} for j in range(1, len(gaps)) if not 7 <= cadence[j - 1] <= 21]
    return cadence, anomalies


def _describe_followup(follow, second):
    """Classify the follow-up bank divergence. These are descriptive states only."""
    if all(gap["gap_pp"] <= 0 for gap in follow):
        return "OBSERVED_FUNDING_GAP_CLOSED", "The next two bank reports show the funding gap closed; timing association only, with no causal attribution to any operation."
    if all(Decimal(0) < gap["gap_pp"] < second["gap_pp"] for gap in follow):
        return "OBSERVED_FUNDING_GAP_NARROWING", "The positive funding gap narrowed in the next two bank reports; the cause remains unresolved."
    if all(gap["gap_pp"] > second["gap_pp"] for gap in follow):
        return "OBSERVED_FUNDING_GAP_WIDENING", "The funding gap widened further in the next two bank reports; widening divergence alone cannot establish a reinforcing loop."
    return "MIXED_DIVERGENCE_EVIDENCE", "Follow-up bank reports do not show one persistent divergence direction."


def _elevate(status, note, response_total, validated):
    """Promote a descriptive divergence state to a causal classification only
    when the RBI operation definition is independently validated AND the
    reported operation direction is consistent with the proposed response.
    Otherwise the descriptive state stands on its own."""
    if not validated:
        return None
    if response_total <= 0:
        if status == "OBSERVED_FUNDING_GAP_CLOSED":
            return CAUSAL, "EMERGING_INFLECTION", "The gap closed after reported net absorption; this is a potential balancing sequence, not proof of RBI causation."
        if status == "OBSERVED_FUNDING_GAP_NARROWING":
            return CAUSAL, "WEAKENING_REINFORCEMENT", "The positive gap narrowed after reported net absorption; the proposed mechanism may be weakening."
        return None
    if status == "OBSERVED_FUNDING_GAP_WIDENING":
        return CAUSAL, "POTENTIAL_REINFORCEMENT", "A wider gap co-occurred with reported net injection; actor feedback remains unproven and alternative drivers are unresolved."
    if status == "OBSERVED_FUNDING_GAP_NARROWING":
        return CAUSAL, "WEAKENING_REINFORCEMENT", "The funding gap persisted but narrowed alongside reported net injection; the mechanism may be weakening."
    return None


def evaluate(rows, as_of, episode_end=None, knowledge_mode="system_known"):
    """Evaluate a chronological bank funding / RBI operation question.

    `rows` must already be vintage-filtered at the knowledge cutoff. A mirror
    observation has no verified original publication timestamp. While the RBI
    liquidity-operation definition and aggregation remain unvalidated
    (`liquidity_definition_validated: false`), only descriptive divergence
    states are assigned; operation-dependent causal classifications are
    suppressed regardless of how the reported operations align.
    """
    config = registry()
    spec = config["mechanisms"]["credit_funding_liquidity_response"]
    validated = bool(spec.get("liquidity_definition_validated", False))
    reference = episode_end or as_of.date()
    result = {"key": f"{config['version']}:credit_funding_liquidity_response:{reference}", "mechanism_id": "credit_funding_liquidity_response", "status": "INSUFFICIENT_EVIDENCE", "state_class": DESCRIPTIVE, "causal_status": "unverified_interpretation", "operation_status": "validated_definition" if validated else "publisher_defined_only", "analysis_basis": "retrospective_current_vintage" if episode_end else "retrospective_source_reconstruction" if knowledge_mode == "source_known" else "system_known_research", "rule_version": config["version"], "thesis": spec["thesis"], "initial_disturbance": spec["initial_disturbance"], "actors": spec["actors"], "incentives": spec["incentives"], "observed_response": spec["observed_response"], "proposed_feedback": spec["proposed_feedback"], "balancing_force": spec["possible_balancing"], "transmission": spec["transmission"], "alternatives": spec["alternatives"], "confirmation_needed": spec["confirmation"], "falsification_conditions": spec["falsification"], "implications_1_3_months": "Conditional: monitor funding conditions, bank lending and the next RBI operation releases; direction unresolved.", "implications_3_6_months": "Conditional: repeated bank and borrower responses plus policy motive evidence are needed before inferring a durable cycle.", "evidence_strength": "insufficient", "persistence": "unverified", "breadth": "banking and central-bank operations only; borrowers and market transmission unobserved", "observations": [], "disturbance_periods": [], "disturbance_growth": [], "response_periods": [], "response_operations": [], "followup_periods": [], "followup_growth": [], "evidence_layers": _evidence_layers(), "liquidity_interpretation": dict(LIQUIDITY_INTERPRETATION, independently_validated=validated), "coverage": {"bank_report_cadence_days": None, "bank_cadence_anomalies": [], "input_staleness_days": {}, "response_window_days": None, "observed_operation_days": 0, "days_without_operation_report": None, "max_gap_between_operation_reports_days": None, "operation_dates_are_consecutive_sessions": False, "chronological_order_verified": False}, "missing_confirmation": list(spec["confirmation"]), "explanation": "Comparable credit, deposit and liquidity observations have not established a chronological actor-response sequence."}
    try:
        gaps = [gap for gap in _gap_history(rows) if gap["date"] <= reference]
        liquidity = _series(rows, LIQUIDITY, "daily")
    except ValueError as exc:
        result["status"] = "CONFLICTING_EVIDENCE"
        result["explanation"] = str(exc)
        return result
    if len(gaps) < 6:
        result["explanation"] = "At least six comparable bank-reporting periods, including a prior regime, are needed."
        return result
    if not liquidity:
        result["explanation"] = "Bank growth can be compared, but no independently observed RBI liquidity-operation response is available."
        return result
    candidates = []
    for i in range(2, len(gaps) - 1):
        before, onset, second = gaps[i - 1], gaps[i], gaps[i + 1]
        if gaps[i - 2]["gap_pp"] <= 0 and before["gap_pp"] <= 0 and onset["gap_pp"] > 0 and second["gap_pp"] > 0 and (second["date"] - onset["date"]).days <= 35:
            candidates.append((i, onset, second))
    if not candidates:
        result["explanation"] = "No transition from an observed nonpositive funding gap to two consecutive positive reporting periods was found. A positive gap alone cannot establish a new actor response."
        return result
    i, onset, second = candidates[-1]
    result["key"] = f"{config['version']}:credit_funding_liquidity_response:{onset['date']}"
    if (reference - second["date"]).days > spec["max_episode_age_days"]:
        result["status"] = "HISTORICAL_ONLY"
        result["disturbance_periods"] = [onset["date"].isoformat(), second["date"].isoformat()]
        result["explanation"] = "The last qualifying funding-gap onset is outside the current investigation window; inspect its retrospective episode explicitly. It is not a current actor-response signal."
        return result
    cadence, anomalies = _bank_cadence(gaps)
    result["coverage"]["bank_report_cadence_days"] = cadence[-1] if cadence else None
    result["coverage"]["bank_cadence_anomalies"] = anomalies
    staleness = {"bank_reports": (reference - gaps[-1]["date"]).days, "liquidity": (reference - max(liquidity)).days}
    result["coverage"]["input_staleness_days"] = staleness
    if staleness["bank_reports"] > spec["bank_freshness_days"] or staleness["liquidity"] > spec["liquidity_freshness_days"]:
        result["status"] = "STALE_EVIDENCE"
        result["explanation"] = "A bank or liquidity series is older than its configured reporting-cadence window; the past sequence is not a current signal."
        return result
    breaks = [date.fromisoformat(str(value)) for value in spec["definition_breaks"]]
    if any(any(prior["date"] < point <= gap["date"] for point in breaks) for gap in (onset, second) for prior in (gap["evidence"][1], gap["evidence"][3])):
        result["status"] = "DEFINITION_REVIEW"
        result["explanation"] = "The year-on-year comparison crosses a documented bank-series definition break; a comparable series is required before assessing actor response."
        return result
    result["disturbance_periods"] = [onset["date"].isoformat(), second["date"].isoformat()]
    result["disturbance_growth"] = [{"period_end": gap["date"].isoformat(), "credit_yoy_pct": float(gap["credit_yoy_pct"]), "deposit_yoy_pct": float(gap["deposit_yoy_pct"]), "gap_pp": float(gap["gap_pp"])} for gap in (onset, second)]
    result["persistence"] = "two consecutive bank reporting periods after a nonpositive prior regime"
    result["evidence_layers"]["observed_divergence"]["observed"] = True
    _add_evidence(result, (row for gap in (gaps[i - 2], gaps[i - 1], onset, second) for row in gap["evidence"]))
    result["explanation"] = "Credit YoY growth exceeded deposit YoY growth in two reporting periods after two nonpositive periods; this is a funding-gap observation, not identified borrower behavior."
    window_end = min(reference, second["date"] + timedelta(days=spec["response_window_days"]))
    window_days = (window_end - second["date"]).days
    observed_days = [day for day in sorted(liquidity) if second["date"] < day <= window_end]
    if len(observed_days) < spec["response_days"]:
        result["missing_confirmation"].insert(0, "At least five separately dated RBI liquidity-operation observations after the gap")
        return result
    selected = observed_days[:spec["response_days"]]
    inter_day = [(b - a).days for a, b in zip(selected, selected[1:])]
    coverage = result["coverage"]
    coverage.update({"response_window_days": window_days, "observed_operation_days": len(observed_days), "days_without_operation_report": max(window_days - len(observed_days), 0), "max_gap_between_operation_reports_days": max(inter_day) if inter_day else 0, "operation_dates_are_consecutive_sessions": len(inter_day) >= 1 and all(gap_days <= 3 for gap_days in inter_day), "chronological_order_verified": True})
    if coverage["max_gap_between_operation_reports_days"] > 14:
        result["status"] = "COVERAGE_INCOMPLETE"
        result["missing_confirmation"].insert(0, "Daily operation reporting inside the response window is incomplete; widely separated reporting dates are not consecutive operation sessions")
        result["explanation"] += " The separately reported operation dates are widely spaced, so they are not interpreted as consecutive operation sessions and no operation-response direction is assessed."
        return result
    response_total = sum((liquidity[day]["value"] for day in selected), Decimal(0))
    result["response_periods"] = [day.isoformat() for day in selected]
    result["response_operations"] = [{"period_end": day.isoformat(), "net_cr": float(liquidity[day]["value"]), "reported_label": "publisher net injection" if liquidity[day]["value"] > 0 else "publisher net absorption" if liquidity[day]["value"] < 0 else "publisher zero net"} for day in selected]
    _add_evidence(result, (liquidity[day] for day in selected))
    result["observed_response_net_cr"] = float(response_total)
    result["evidence_layers"]["subsequent_operations"]["observed"] = True
    direction = "net injection" if response_total > 0 else "net absorption" if response_total < 0 else "zero net"
    result["explanation"] += f" The first five separately dated reported operation days after the gap sum to {direction} under publisher-defined labels; this is a cumulative signed flow total, not a change in outstanding liquidity, mixed operation types are aggregated by RBI's published net formula, and the operation's motive is unknown."
    if not validated:
        result["missing_confirmation"].insert(0, "Independent validation of the RBI liquidity-operation series definition, aggregation and sign convention")
    follow = [gap for gap in gaps[i + 2:] if selected[-1] < gap["date"] <= min(reference, selected[-1] + timedelta(days=spec["followup_window_days"]))]
    if len(follow) < spec["followup_periods"]:
        result["missing_confirmation"].insert(0, "Two bank-credit and deposit reports after the observed liquidity operations")
        return result
    follow = follow[:spec["followup_periods"]]
    if follow[0]["date"] <= selected[-1]:
        result["status"] = "CONFLICTING_EVIDENCE"
        result["explanation"] = "Follow-up bank reports are not chronologically after the observed operations; the sequence cannot be assessed."
        return result
    result["followup_periods"] = [gap["date"].isoformat() for gap in follow]
    result["followup_growth"] = [{"period_end": gap["date"].isoformat(), "credit_yoy_pct": float(gap["credit_yoy_pct"]), "deposit_yoy_pct": float(gap["deposit_yoy_pct"]), "gap_pp": float(gap["gap_pp"])} for gap in follow]
    _add_evidence(result, (row for gap in follow for row in gap["evidence"]))
    result["evidence_layers"]["feedback_inflection"]["observed"] = True
    status, note = _describe_followup(follow, second)
    elevated = _elevate(status, note, response_total, validated)
    if elevated:
        result["state_class"], status, note = elevated
        result["causal_status"] = "provisional_interpretation"
    result["status"] = status
    result["explanation"] += " " + note
    return result
