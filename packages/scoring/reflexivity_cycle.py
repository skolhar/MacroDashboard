"""Cycle-centric research view for the domestic equity flows cycle.

Composes the existing capital-flow investigation outputs
(`packages.scoring.capital_flow_reflexivity`) into one analyst-facing
narrative: current observations, the proposed feedback hypothesis,
evidence classified as supporting / contradictory / insufficient,
inflection conditions to monitor, and conditional 1-3 and 3-6 month
implications.

Every statement is descriptive. Nothing here is an established causal
relationship, a price target, a probability, or a buy/sell signal; the
hypothesis remains a hypothesis until independently dated actor-response
evidence supports it, and the page stays useful when observations are
missing or stale.
"""
from datetime import datetime

DAILY_STALE_DAYS = 7      # daily flow/index observations older than this are flagged stale
MONTHLY_STALE_DAYS = 45   # monthly AMFI observations older than this are flagged stale

RESEARCH_QUESTION = (
    "Are domestic institutional and household investment flows reinforcing "
    "the Indian equity market, or is this feedback mechanism weakening?"
)

HYPOTHESIS = (
    "Market performance influences investor allocation decisions; domestic "
    "institutional (DII) and household (SIP) flows add equity demand; and "
    "that demand in turn supports market performance. This loop is a "
    "proposed mechanism for investigation, not an established causal "
    "relationship: flows data carries no actor motivation, and "
    "co-occurrence is not causation."
)

MONITOR_CONDITIONS = [
    {"condition": "Declining domestic buying relative to recently observed sessions.", "status": "monitor"},
    {"condition": "Weaker SIP contribution growth relative to the long-run median.", "status": "monitor"},
    {"condition": "Divergence between market performance and domestic investment flows.", "status": "monitor"},
]

UNAVAILABLE_IMPLICATIONS = [
    {
        "horizon": "1-3 months",
        "scenario": "Insufficient stored observations to condition a 1-3 month reading; monitor incoming domestic flows and SIP contributions as they are ingested.",
        "would_strengthen": "Matched FPI-selling/DII-buying sessions with sustained follow-up buying.",
        "would_weaken": "Domestic buying absent while the index advances.",
    },
    {
        "horizon": "3-6 months",
        "scenario": "Insufficient stored observations to condition a 3-6 month reading; the divergence between market performance and domestic participation remains the primary monitoring focus.",
        "would_strengthen": "Repeated matched offset windows with sustained follow-up buying.",
        "would_weaken": "A widening gap between market performance and domestic participation.",
    },
]


def _fmt_cr(value):
    return f"\u20b9{value:,.0f} crore"


def _pct(value):
    return "unavailable" if value is None else f"{value:.1f}%"


def classify_evidence(evaluation, series_summaries):
    """Classify stored evidence as supporting, contradictory or insufficient.

    Classification is descriptive: an item supports the hypothesis when the
    observed pattern is consistent with the proposed loop, contradicts it
    when the observed pattern runs against the loop, and is insufficient
    when the stored data cannot evaluate that leg. No conclusion is
    manufactured from absence.
    """
    evidence = []
    offset = evaluation.get("offset")
    persistence = evaluation.get("persistence")
    sip = evaluation.get("sip_response")
    spurious = evaluation.get("spurious_check")

    if offset:
        evidence.append({
            "stance": "supporting",
            "statement": (f"DII net buying of {_fmt_cr(offset['dii_net_cr'])} co-occurred with FPI net selling of "
                          f"{_fmt_cr(abs(offset['fpi_net_cr']))} over {offset['matched_sessions']} matched reporting "
                          f"sessions; the matched offset is {_fmt_cr(offset['offset_size_cr'])}."),
            "basis": offset["basis"],
        })
    else:
        evidence.append({
            "stance": "insufficient",
            "statement": ("No qualified offset window is observable: the stored sessions do not (yet) show five "
                          "matched FPI-selling/DII-buying sessions above the descriptive minimum."),
            "basis": "offset detection requires matched sessions; missing sessions are never zero-filled",
        })

    verdict = (persistence or {}).get("persistence")
    follow_up_semantics = (persistence or {}).get("follow_up", {}).get("semantics", "retrospective follow-up evidence")
    if verdict == "sustained":
        evidence.append({
            "stance": "supporting",
            "statement": (f"Domestic buying sustained into the follow-up sessions (daily-average DII ratio "
                          f"{persistence['offset_ratio']} of the detection-window level)."),
            "basis": follow_up_semantics,
        })
    elif verdict == "weakening":
        evidence.append({
            "stance": "contradictory",
            "statement": (f"Domestic buying weakened in the follow-up sessions (daily-average DII ratio "
                          f"{persistence['offset_ratio']} of the detection-window level)."),
            "basis": follow_up_semantics,
        })
    elif verdict in {"no", "not_offsetting"}:
        evidence.append({
            "stance": "contradictory",
            "statement": "Domestic buying did not continue against foreign selling in the follow-up sessions.",
            "basis": follow_up_semantics,
        })
    elif persistence:
        evidence.append({
            "stance": "insufficient",
            "statement": "Not enough matched follow-up sessions are stored to assess whether domestic buying persisted.",
            "basis": follow_up_semantics,
        })

    if sip:
        if sip["state"] == "sip_rising_after_recent_returns":
            evidence.append({
                "stance": "supporting",
                "statement": (f"Average SIP contributions after rising lagged returns "
                              f"({_fmt_cr(sip['avg_sip_cr_after_rising_returns'])}) exceeded those after falling "
                              f"returns ({_fmt_cr(sip['avg_sip_cr_after_falling_returns'])}) across "
                              f"{sip['months_observed']} matched months; median month-over-month growth "
                              f"{_pct(sip.get('median_sip_mom_growth_pct'))}."),
                "basis": sip["basis"],
            })
        elif sip["state"] == "sip_falling_after_recent_returns":
            evidence.append({
                "stance": "contradictory",
                "statement": (f"Average SIP contributions after rising lagged returns "
                              f"({_fmt_cr(sip['avg_sip_cr_after_rising_returns'])}) were below those after falling "
                              f"returns ({_fmt_cr(sip['avg_sip_cr_after_falling_returns'])}); household "
                              f"contributions did not track returns upward."),
                "basis": sip["basis"],
            })
        else:
            evidence.append({
                "stance": "insufficient",
                "statement": ("SIP contributions did not differ clearly between rising and falling return months; "
                              "the household-flow leg cannot be classified."),
                "basis": sip["basis"],
            })
        if sip.get("limited_directions"):
            evidence.append({
                "stance": "insufficient",
                "statement": ("The SIP comparison rests on limited rising or falling return observations; treat the "
                              "household-flow reading as provisional."),
                "basis": "few return months in one direction",
            })
    else:
        evidence.append({
            "stance": "insufficient",
            "statement": "Not enough matched SIP/return months are stored to evaluate the household-flow leg of the hypothesis.",
            "basis": "monthly SIP comparisons require matched lagged return months",
        })

    if spurious:
        if spurious["state"] == "co_occurrence_observed":
            evidence.append({
                "stance": "insufficient",
                "statement": (f"The compounded market return over the {spurious['forward_months']} complete month(s) "
                              f"after the offset window was {spurious['forward_return_pct']:.2f}%; this context "
                              f"cannot establish that flows caused performance."),
                "basis": spurious["caveat"],
            })
        else:
            evidence.append({
                "stance": "insufficient",
                "statement": f"Forward-return context unresolved: {spurious['reason']}.",
                "basis": "an incomplete forward window is never reported as an outcome",
            })

    labels = (("fpi", "FPI equity flows"), ("dii", "DII equity flows"), ("sip", "SIP contributions"), ("returns", "Nifty closes"))
    for key, label in labels:
        summary = series_summaries.get(key) or {}
        if summary.get("status") == "stale":
            evidence.append({
                "stance": "insufficient",
                "statement": (f"{label} observations are {summary.get('days_behind_as_of')} days behind the "
                              f"evaluation date; the corresponding leg may be stale."),
                "basis": "staleness reduces the evidential weight of the latest reading",
            })
        elif summary.get("status") == "missing":
            evidence.append({
                "stance": "insufficient",
                "statement": f"No {label} observations are stored for this evaluation window.",
                "basis": "missing observations are reported, never substituted",
            })

    return evidence


def inflection_conditions(evaluation):
    """Conditions that could indicate weakening reinforcement.

    These are conditions to monitor, not automatic predictions; a condition
    is marked observed only when the stored evidence already shows it.
    """
    persistence = evaluation.get("persistence") or {}
    sip = evaluation.get("sip_response") or {}
    verdict = persistence.get("persistence")
    return [
        {
            "condition": "Declining domestic buying: DII daily-average buying in the sessions after a detected offset window falls below the detection-window level.",
            "status": ("observed" if verdict in {"weakening", "no", "not_offsetting"} else
                       ("no qualified offset window to follow up" if not persistence else "not observed in the stored window")),
        },
        {
            "condition": "Weaker SIP contribution growth: incoming monthly SIP growth falling below the long-run median contribution growth.",
            "status": (f"monitor: long-run median month-over-month SIP growth is {_pct(sip.get('median_sip_mom_growth_pct'))}"
                       if sip else "monitor: no matched SIP months stored yet"),
        },
        {
            "condition": "Divergence between market performance and investment flows: the index advancing while domestic net buying declines or disappears.",
            "status": "monitor: compare the latest stored index closes with the latest stored FPI/DII sessions",
        },
    ]


def implications(evaluation):
    """Conditional 1-3 and 3-6 month implications.

    Each implication is a conditional scenario, never a price target,
    probability or buy/sell signal.
    """
    persistence = evaluation.get("persistence") or {}
    sip = evaluation.get("sip_response") or {}
    median_growth = sip.get("median_sip_mom_growth_pct")
    growth_clause = (f"holds at or above its observed long-run median growth ({_pct(median_growth)} per month)"
                     if median_growth is not None else "holds near recently observed levels")
    detection = persistence.get("detection") or {}
    buying_clause = (f"continues at or near the observed daily average ({_fmt_cr(detection['dii_daily_avg_cr'])} per session)"
                     if detection.get("dii_daily_avg_cr") is not None else "continues at recently observed levels")
    ratio_clause = (f" (latest observed ratio {persistence['offset_ratio']})"
                    if persistence.get("offset_ratio") is not None else "")
    return [
        {
            "horizon": "1-3 months",
            "scenario": (f"If domestic buying {buying_clause} and SIP contribution growth {growth_clause}, the "
                         "proposed reinforcement reading remains intact over the next 1-3 months."),
            "would_strengthen": "A new matched FPI-selling/DII-buying window with sustained follow-up buying, and SIP contributions in line with the long-run median.",
            "would_weaken": (f"Follow-up DII buying decaying materially below the detection-window daily average"
                             f"{ratio_clause}, or SIP growth falling below the long-run median."),
        },
        {
            "horizon": "3-6 months",
            "scenario": ("If the index advances while domestic net buying declines, the divergence itself becomes the "
                         "primary monitoring focus over the next 3-6 months: reinforcement would be weakening even "
                         "while performance holds."),
            "would_strengthen": "Repeated matched offset windows with sustained follow-up buying across successive weeks.",
            "would_weaken": "A widening gap between market performance and domestic participation, or SIP contribution growth stalling below trend.",
        },
    ]


def reflexivity_cycle_view(evaluation, series_summaries):
    """Assemble the five-section cycle view from existing investigation outputs."""
    return {
        "as_of": evaluation["as_of"],
        "state": "investigation_available",
        "cycle": "domestic_equity_flows_market_reflexivity",
        "research_question": RESEARCH_QUESTION,
        "hypothesis": HYPOTHESIS,
        "observations": series_summaries,
        "evidence": classify_evidence(evaluation, series_summaries),
        "inflection": inflection_conditions(evaluation),
        "implications": implications(evaluation),
        "limitation": evaluation.get("limitation", ""),
    }


def unavailable_view(reason, series_summaries, as_of):
    """View used when the capital-flow investigation has no usable data.

    The page must remain useful with incomplete data: the hypothesis and
    monitoring conditions are still shown, the evidence list is empty, and
    the implications are explicitly unconditioned monitoring statements.
    """
    return {
        "as_of": as_of.isoformat() if isinstance(as_of, datetime) else str(as_of),
        "cycle": "domestic_equity_flows_market_reflexivity",
        "state": "data_unavailable",
        "reason": reason,
        "research_question": RESEARCH_QUESTION,
        "hypothesis": HYPOTHESIS,
        "observations": series_summaries,
        "evidence": [],
        "inflection": MONITOR_CONDITIONS,
        "implications": UNAVAILABLE_IMPLICATIONS,
        "limitation": ("Descriptive co-occurrence only; flows data carries no actor motivation. "
                       "No feedback loop, absorption capacity or allocation forecast is established."),
    }
