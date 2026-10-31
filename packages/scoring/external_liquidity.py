"""Explainable external-liquidity evidence over the existing v2 ruleset."""
from packages.domain.config import rules

DISPLAY_IDS = (
    "usd_inr_spot", "fx_gross_reserves_usd", "rbi_net_forward_usd",
    "fpi_equity_net_inr", "fpi_debt_net_inr", "india_10y_yield",
    "brent_usd", "sip_contribution_inr", "midcap_mf_net_inr", "smallcap_mf_net_inr",
)


def external_liquidity_view(dashboard: dict) -> dict:
    metrics = {item["id"]: item for item in dashboard["metrics"]}
    selected = [metrics[id] for id in DISPLAY_IDS if id in metrics]
    thresholds = rules("v2")["alerts"][0]["conditions"]
    def signal(id: str, limit: float, op: str) -> bool | None:
        metric = metrics.get(id)
        value = metric.get("scored_feature") if metric else None
        if value is None:
            return None
        return value >= limit if op == "gte" else value <= limit

    # Use the existing provisional rule thresholds, but require independent
    # flow and liquidity/oil confirmation before describing reinforcement.
    fx = signal("usd_inr_spot", 2, "gte")
    fpi = signal("fpi_equity_net_inr", -15000, "lte")
    reserves = signal("fx_gross_reserves_usd", -3, "lte")
    oil = signal("brent_usd", 100, "gte")
    if fx is None:
        classification = "INSUFFICIENT_EVIDENCE"
        explanation = "A source-backed USD/INR momentum series is unavailable. No FX feedback assessment is possible."
    elif not fx:
        classification = "NO_CONFIRMED_FX_PRESSURE"
        explanation = "The provisional depreciation threshold is not met. Other pressures remain contextual."
    elif fpi is True and (reserves is True or oil is True):
        classification = "REINFORCING_STRESS_WATCH"
        explanation = "Depreciation, foreign equity selling, and reserve decline or elevated oil coincide. This is a provisional feedback-loop watch, not proof of causality."
    elif fpi is None:
        classification = "AWAITING_FOREIGN_FLOW_EVIDENCE"
        explanation = "Depreciation is observed, but FPI flow evidence is missing or stale. No external-financing conclusion can be drawn."
    elif fpi is False:
        classification = "DEPRECIATION_WITH_COUNTER_FLOW_EVIDENCE"
        explanation = "Depreciation is observed while eligible FPI flow data contradicts the foreign-selling condition. Managed adjustment remains possible."
    elif reserves is None or oil is None:
        classification = "FINANCING_PRESSURE_AWAITING_LIQUIDITY_EVIDENCE"
        explanation = "Depreciation and foreign selling coincide, but reserve or oil confirmation is missing or stale. The absent signal is unknown, not contradictory."
    else:
        classification = "FINANCING_PRESSURE_WITH_COUNTER_LIQUIDITY_EVIDENCE"
        explanation = "Depreciation and foreign selling coincide, but observed reserves and oil do not meet the provisional liquidity-stress conditions."
    fx_cycle = next(item for item in dashboard["cycles"] if item["id"] == "fx")
    alert = next((item for item in dashboard["alerts"] if item["rule_id"] == "RUPEE_STRESS"), None)
    return {
        "as_of": dashboard["as_of"], "mode": dashboard["mode"], "environment": dashboard.get("environment"),
        "ruleset_version": "v2", "cycle": fx_cycle, "data_confidence": dashboard.get("data_confidence"),
        "source_health": dashboard["source_health"], "metrics": selected,
        "classification": classification, "explanation": explanation,
        "expectations_evidence": "UNAVAILABLE: observed prices and flows cannot establish investor expectations or RBI intervention motives",
        "forward_interpretation": "CONTEXT_ONLY: gross reserves are not netted with RBI forward positions until signs, maturity buckets, and definitions are validated",
        "signals": {"depreciation": fx, "foreign_equity_selling": fpi, "gross_reserve_decline": reserves, "elevated_oil": oil},
        "evidence_status": {"depreciation": "UNKNOWN" if fx is None else "MET" if fx else "COUNTER", "foreign_equity_selling": "UNKNOWN" if fpi is None else "MET" if fpi else "COUNTER", "gross_reserve_decline": "UNKNOWN" if reserves is None else "MET" if reserves else "COUNTER", "elevated_oil": "UNKNOWN" if oil is None else "MET" if oil else "COUNTER"},
        "alert": alert,
        "thresholds": {key: value for key, value in thresholds.items() if key in {"usd_inr_spot", "fpi_equity_net_inr", "brent_usd", "fx_gross_reserves_usd"}},
        "warning": "Exploratory risk index with provisional thresholds; no causal or predictive claim",
    }
