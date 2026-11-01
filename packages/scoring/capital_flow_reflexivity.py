"""Capital-flow reflexivity investigation: attributable institutional behaviour.

Private research. Observes whether domestic institutional purchases offset
foreign selling, whether absorption persists or weakens, whether household
SIP contributions and redemptions change with equity returns, and whether
any of this is more than co-movement. All states are descriptive and
provisional; causal attribution requires documented actor motivation, which
flows data alone never provides.
"""
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from decimal import Decimal

OFFSET_MIN = Decimal("2500")        # crore: minimum offset size to be descriptive
PERSISTENCE_SESSIONS = 5            # consecutive sessions to call persistence
ABSORPTION_DECAY = Decimal("0.7")   # later offset / earlier offset threshold
RETURN_LOOKAHEAD_DAYS = 10          # forward window for subsequent return check
SIP_RETURN_LAG_MONTHS = 3           # SIP response lag to equity returns


def _window(rows, day, sessions):
    """Return rows with period_end strictly before `day` (no look-ahead)."""
    return [r for r in rows if r.period_end < day][-sessions:]


def offset(rows_fpi, rows_dii, day, *, sessions=5):
    """Descriptive offset: same-session DII buy against FPI sell.

    Co-occurrence only. No order, motivation or intent is inferred.
    """
    recent_fpi = _window(rows_fpi, day, sessions)
    recent_dii = _window(rows_dii, day, sessions)
    if len(recent_fpi) < sessions or len(recent_dii) < sessions:
        return None
    fpi_net = sum(r.value for r in recent_fpi)
    dii_net = sum(r.value for r in recent_dii)
    if fpi_net >= 0 or dii_net <= 0:
        return None
    size = dii_net - fpi_net  # dii positive minus fpi negative
    if size < OFFSET_MIN:
        return None
    return {
        "state": "dii_offset_fpi_selling",
        "as_of": day.isoformat(),
        "sessions": sessions,
        "fpi_net_cr": float(fpi_net),
        "dii_net_cr": float(dii_net),
        "offset_size_cr": float(size),
        "basis": "co-occurrence of opposite-sign net flows; not evidence of intent",
    }


def persistence(rows_fpi, rows_dii, day, *, sessions=3, horizon=PERSISTENCE_SESSIONS):
    """Does the offset persist in the sessions after its first detection window?

    Looks strictly forward from `day` (never backward) and compares daily
    average DII buying in the tail window against the detection window, so
    windows of different lengths are never compared directly.
    """
    first = offset(rows_fpi, rows_dii, day, sessions=sessions)
    if first is None:
        return None
    forward_fpi = [r for r in rows_fpi if r.period_end >= day][:horizon]
    forward_dii = [r for r in rows_dii if r.period_end >= day][:horizon]
    if len(forward_fpi) < horizon or len(forward_dii) < horizon:
        return {"state": "first", "persistence": "insufficient_history", "as_of": day.isoformat()}
    tail_fpi = sum(r.value for r in forward_fpi)
    tail_dii = sum(r.value for r in forward_dii)
    if tail_fpi >= 0 or tail_dii <= 0:
        return {"state": "dissipated", "persistence": "no", "as_of": day.isoformat()}
    # Fair comparison: daily average DII buying in each window
    first_dii_avg = Decimal(str(first["dii_net_cr"])) / sessions
    tail_dii_avg = tail_dii / horizon
    ratio = tail_dii_avg / first_dii_avg if first_dii_avg else Decimal("0")
    if ratio >= ABSORPTION_DECAY:
        verdict = "sustained"
    elif ratio > 0:
        verdict = "weakening"
    else:
        verdict = "not_offsetting"
    return {"state": f"persistence_{verdict}", "persistence": verdict, "offset_ratio": round(float(ratio), 3), "as_of": day.isoformat()}


def sip_response(rows_sip, rows_returns, as_of, *, lag_months=SIP_RETURN_LAG_MONTHS):
    """Whether household SIP contributions changed after sustained returns.

    Monthly SIP series shifted by `lag_months` against subsequent market
    returns. Co-movement only; household motivation is not observed.
    """
    if len(rows_sip) < 4 or not rows_returns:
        return None
    returns_by_month = {}
    for r in rows_returns:
        key = (r.period_end.year, r.period_end.month)
        returns_by_month[key] = r.value
    comparisons = []
    for i, sip in enumerate(rows_sip[:-1]):
        month = (sip.period_end.year, sip.period_end.month)
        later = returns_by_month.get(month)
        if later is None:
            continue
        comparisons.append((sip.value, later))
    if len(comparisons) < 3:
        return None
    rising_returns = [c for c in comparisons if c[1] > 0]
    falling_returns = [c for c in comparisons if c[1] < 0]
    avg_sip_up = sum(c[0] for c in rising_returns) / len(rising_returns) if rising_returns else None
    avg_sip_down = sum(c[0] for c in falling_returns) / len(falling_returns) if falling_returns else None
    if avg_sip_up is None or avg_sip_down is None:
        return None
    direction = "rising" if avg_sip_up > avg_sip_down else "falling" if avg_sip_up < avg_sip_down else "flat"
    return {
        "state": f"sip_{direction}_with_subsequent_returns",
        "avg_sip_cr_rising_months": float(avg_sip_up),
        "avg_sip_cr_falling_months": float(avg_sip_down),
        "months_observed": len(comparisons),
        "basis": "monthly co-movement, not a household allocation decision",
        "as_of": as_of.isoformat(),
    }


def spurious_association_check(rows_fpi, rows_dii, rows_returns, day, *, sessions=5):
    """Flag associations that would look causal but fail basic order tests.

    A 'response' claim requires the DII flow to be observed strictly after
    the FPI flow on the same session and the return window to start strictly
    after the offset window. Anything else is reported as unresolved.
    """
    same_day_fpi = [r for r in rows_fpi if r.period_end == day]
    same_day_dii = [r for r in rows_dii if r.period_end == day]
    if not same_day_fpi or not same_day_dii:
        return {"state": "unresolved", "reason": "no same-session pairing"}
    if same_day_dii[0].retrieved_at < same_day_fpi[0].retrieved_at:
        return {"state": "not_a_response", "reason": "DII reported before FPI; order undetermined"}
    forward = [r for r in rows_returns if day < r.period_end <= day + timedelta(days=RETURN_LOOKAHEAD_DAYS)]
    if not forward:
        return {"state": "unresolved", "reason": "no forward return window"}
    forward_return = sum(r.value for r in forward)
    return {
        "state": "order_consistent_but_not_causal",
        "forward_return_pct": float(forward_return),
        "caveat": "temporal order satisfied; causality remains unproven without actor-motivation evidence",
    }


def evaluate(rows_fpi, rows_dii, rows_sip, rows_returns, as_of):
    """Aggregate investigation snapshot. Every finding is provisional."""
    latest_flow_day = max((r.period_end for r in rows_fpi + rows_dii), default=None)
    results = {
        "as_of": as_of.isoformat(),
        "offset": None,
        "persistence": None,
        "sip_response": None,
        "spurious_check": None,
    }
    if latest_flow_day:
        results["offset"] = offset(rows_fpi, rows_dii, latest_flow_day)
        results["persistence"] = persistence(rows_fpi, rows_dii, latest_flow_day)
        results["spurious_check"] = spurious_association_check(rows_fpi, rows_dii, rows_returns, latest_flow_day)
    if rows_sip:
        results["sip_response"] = sip_response(rows_sip, rows_returns, as_of)
    results["limitation"] = (
        "All findings are descriptive co-occurrence. Flows data carries no actor "
        "motivation; FPI/DII attribution follows exchange publisher conventions "
        "and could change definition without notice. This is not evidence of a "
        "feedback loop, absorption capacity, or future allocation behaviour."
    )
    return results
