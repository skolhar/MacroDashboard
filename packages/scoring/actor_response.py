"""Provisional actor-response sequences from observed facts, never causal proof."""
from datetime import date, timedelta
from decimal import Decimal
from packages.connectors.rbi_research_mirror import registry

CREDIT = "rbi_mirror_bank_credit_cr"
DEPOSITS = "rbi_mirror_bank_deposits_cr"
LIQUIDITY = "rbi_mirror_net_injection_cr"


def _public(row):
    return {"kind": row["kind"], "id": row["id"], "series": row["series"], "period_end": row["date"].isoformat(), "value": float(row["value"]), "source_value_text": row.get("source_value_text"), "source": row["source"], "source_reference": row["reference"], "revision": row["revision"], "published_at": row["published_at"].isoformat() if row["published_at"] else None, "retrieved_at": row["retrieved_at"].isoformat(), "quality": row["quality"]}


def _add_evidence(result, rows):
    known = {(item["kind"], item["id"]) for item in result["observations"]}
    for row in rows:
        key = (row["kind"], row["id"])
        if key not in known:
            result["observations"].append(_public(row))
            known.add(key)


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


def evaluate(rows, as_of, episode_end=None, knowledge_mode="system_known"):
    """Evaluate a chronological bank funding / RBI operation question.

    `rows` must already be vintage-filtered at the knowledge cutoff. A mirror
    observation has no verified original publication timestamp.
    """
    config = registry()
    spec = config["mechanisms"]["credit_funding_liquidity_response"]
    reference = episode_end or as_of.date()
    result = {"key": f"{config['version']}:credit_funding_liquidity_response:{reference}", "mechanism_id": "credit_funding_liquidity_response", "status": "INSUFFICIENT_EVIDENCE", "causal_status": "unverified_interpretation", "analysis_basis": "retrospective_current_vintage" if episode_end else "retrospective_source_reconstruction" if knowledge_mode == "source_known" else "system_known_research", "rule_version": config["version"], "thesis": spec["thesis"], "initial_disturbance": spec["initial_disturbance"], "actors": spec["actors"], "incentives": spec["incentives"], "observed_response": spec["observed_response"], "proposed_feedback": spec["proposed_feedback"], "balancing_force": spec["possible_balancing"], "transmission": spec["transmission"], "alternatives": spec["alternatives"], "confirmation_needed": spec["confirmation"], "falsification_conditions": spec["falsification"], "implications_1_3_months": "Conditional: monitor funding conditions, bank lending and the next RBI operation releases; direction unresolved.", "implications_3_6_months": "Conditional: repeated bank and borrower responses plus policy motive evidence are needed before inferring a durable cycle.", "evidence_strength": "insufficient", "persistence": "unverified", "breadth": "banking and central-bank operations only; borrowers and market transmission unobserved", "observations": [], "disturbance_periods": [], "disturbance_growth": [], "response_periods": [], "followup_periods": [], "followup_growth": [], "missing_confirmation": list(spec["confirmation"]), "explanation": "Comparable credit, deposit and liquidity observations have not established a chronological actor-response sequence."}
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
    if (reference - gaps[-1]["date"]).days > spec["bank_freshness_days"] or not liquidity or (reference - max(liquidity)).days > spec["liquidity_freshness_days"]:
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
    _add_evidence(result, (row for gap in (gaps[i - 2], gaps[i - 1], onset, second) for row in gap["evidence"]))
    result["explanation"] = "Credit YoY growth exceeded deposit YoY growth in two reporting periods after two nonpositive periods; this is a funding-gap observation, not identified borrower behavior."
    response_days = [day for day in sorted(liquidity) if second["date"] < day <= min(reference, second["date"] + timedelta(days=spec["response_window_days"]))]
    if len(response_days) < spec["response_days"]:
        result["missing_confirmation"].insert(0, "At least five separately dated RBI liquidity-operation observations after the gap")
        return result
    selected = response_days[:spec["response_days"]]
    response_total = sum((liquidity[day]["value"] for day in selected), Decimal(0))
    result["response_periods"] = [day.isoformat() for day in selected]
    _add_evidence(result, (liquidity[day] for day in selected))
    result["observed_response_value_cr_days"] = float(response_total)
    if response_total <= 0:
        result["status"] = "CONTRADICTORY_EVIDENCE"
        result["evidence_strength"] = "observed counterforce; causal motive unverified"
        result["explanation"] += " The next five reported RBI operation days sum to net absorption or zero, contradicting the proposed net-injection response; unrelated liquidity drivers remain possible."
    else:
        result["evidence_strength"] = "chronological co-occurrence only; RBI motive and borrower response unverified"
        result["explanation"] += " The next five reported RBI operation days sum to net injection; the operation's motive is unknown."
    follow = [gap for gap in gaps[i + 2:] if selected[-1] < gap["date"] <= min(reference, selected[-1] + timedelta(days=spec["followup_window_days"]))]
    if len(follow) < spec["followup_periods"]:
        result["missing_confirmation"].insert(0, "Two bank-credit and deposit reports after the observed liquidity operations")
        return result
    follow = follow[:spec["followup_periods"]]
    result["followup_periods"] = [gap["date"].isoformat() for gap in follow]
    result["followup_growth"] = [{"period_end": gap["date"].isoformat(), "credit_yoy_pct": float(gap["credit_yoy_pct"]), "deposit_yoy_pct": float(gap["deposit_yoy_pct"]), "gap_pp": float(gap["gap_pp"])} for gap in follow]
    _add_evidence(result, (row for gap in follow for row in gap["evidence"]))
    if response_total <= 0 and all(gap["gap_pp"] <= 0 for gap in follow):
        result["status"] = "EMERGING_INFLECTION"
        result["explanation"] += " The next two bank reports show the gap closed after net absorption; this is a potential balancing sequence, not proof of RBI causation."
    elif response_total <= 0 and all(Decimal(0) < gap["gap_pp"] < second["gap_pp"] for gap in follow):
        result["status"] = "WEAKENING_REINFORCEMENT"
        result["explanation"] += " The next two bank reports show the positive gap narrowing after net absorption; the cause remains unresolved."
    elif response_total <= 0:
        result["explanation"] += " Follow-up bank reports do not establish a persistent balancing turn."
    elif all(gap["gap_pp"] <= 0 for gap in follow):
        result["status"] = "EMERGING_INFLECTION"
        result["explanation"] += " The next two bank reports show the funding gap closed; this is a potential balancing turn, with no causal attribution to the RBI operation."
    elif all(gap["gap_pp"] > second["gap_pp"] for gap in follow):
        result["status"] = "POTENTIAL_REINFORCEMENT"
        result["explanation"] += " The next two bank reports show a wider gap, consistent with continued pressure; actor feedback remains unproven."
    elif all(Decimal(0) < gap["gap_pp"] < second["gap_pp"] for gap in follow):
        result["status"] = "WEAKENING_REINFORCEMENT"
        result["explanation"] += " The funding gap persisted but narrowed in two reports; the mechanism may be weakening."
    else:
        result["status"] = "CONFLICTING_EVIDENCE"
        result["explanation"] += " Follow-up bank reports do not support one persistent direction."
    return result
