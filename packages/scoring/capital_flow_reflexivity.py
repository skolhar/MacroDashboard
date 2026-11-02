"""Capital-flow reflexivity investigation: attributable institutional behaviour.

Private research. Observes whether domestic institutional purchases offset
foreign selling, whether absorption persists or weakens in sessions after
the detection window, whether household SIP contributions differ after
rising versus falling returns, and whether any of this is more than
co-movement. All states are descriptive and provisional; causal attribution
requires documented actor motivation, which flows data alone never provides.

Timing semantics used throughout:
- `as_of` is the evaluation timestamp: what the system knew (system_known)
  or what the source had published (source_known) at that moment.
- A row is usable only when its reporting date is not in the future relative
  to `as_of` and the observation itself was known by `as_of`; anything else
  is excluded and counted, never zero-filled.
- Sessions after a detection date are retrospective follow-up evidence
  gathered later; they are never described as signals known on that date.
- Reporting or retrieval timestamps cannot establish the order in which
  investor groups actually traded; same-session flows are co-occurrence.
"""
from datetime import date, datetime, timedelta
from decimal import Decimal

OFFSET_MIN = Decimal("2500")        # crore: minimum offset size to be descriptive
OFFSET_MIN_SESSIONS = 5             # matched sessions required to describe an offset
PERSISTENCE_SESSIONS = 5            # follow-up sessions for the retrospective check
ABSORPTION_DECAY = Decimal("0.7")   # later offset / earlier offset threshold
SPURIOUS_FORWARD_MONTHS = 3         # complete forward months for the return check
SIP_RETURN_LAG_MONTHS = 3           # SIP response lag to equity returns
SIP_MIN_MONTHS = 3                  # matched SIP/return months required
SIP_LIMITED_DIRECTIONS = 2          # below this count per direction the view is flagged limited


def _usable(rows, as_of):
    """Rows observable at `as_of`: no future reporting dates, and the row
    itself known (retrieved/published) by the evaluation timestamp."""
    cutoff = as_of.date()
    return [r for r in rows if r.period_end <= cutoff and r.retrieved_at <= as_of]


def _excluded_counts(rows, as_of):
    """Why rows were withheld from an evaluation, for explicit reporting."""
    cutoff = as_of.date()
    return {
        "future_dated": sum(1 for r in rows if r.period_end > cutoff),
        "late_ingested": sum(1 for r in rows if r.period_end <= cutoff and r.retrieved_at > as_of),
    }


def _daily_net(rows):
    """Latest net-basis row per reporting date; gross turnover rows are
    excluded from net-flow comparisons and counted separately."""
    by_date = {}
    gross = 0
    for row in sorted(rows, key=lambda x: (x.period_end, x.retrieved_at)):
        if row.flow_basis != "net":
            gross += 1
            continue
        by_date[row.period_end] = row
    return by_date, gross


def _compound(returns_pct):
    """Compound percentage returns into one cumulative percentage change."""
    factor = Decimal("1")
    for value in returns_pct:
        factor *= Decimal("1") + value / Decimal("100")
    return (factor - Decimal("1")) * Decimal("100")


def _first_of_month(day):
    return day.replace(day=1)


def _shift_month(year, month, delta):
    total = year * 12 + (month - 1) + delta
    return total // 12, total % 12 + 1


def matched_sessions(rows_fpi, rows_dii, as_of=None):
    """Common net-basis reporting sessions for FPI and DII.

    Observations are paired by identical reporting date; dates present in
    only one series are excluded (never zero-filled) and counted. Gross
    turnover rows never enter the net-flow comparison.
    """
    if as_of is None:
        fpi_rows, dii_rows = list(rows_fpi), list(rows_dii)
    else:
        fpi_rows, dii_rows = _usable(rows_fpi, as_of), _usable(rows_dii, as_of)
    fpi, fpi_gross = _daily_net(fpi_rows)
    dii, dii_gross = _daily_net(dii_rows)
    return fpi, dii, sorted(set(fpi) & set(dii)), {
        "fpi_gross_rows_excluded": fpi_gross,
        "dii_gross_rows_excluded": dii_gross,
        "fpi_unmatched_sessions": len(set(fpi) - set(dii)),
        "dii_unmatched_sessions": len(set(dii) - set(fpi)),
    }


def offset(rows_fpi, rows_dii, day, *, sessions=OFFSET_MIN_SESSIONS, as_of=None):
    """Descriptive offset: DII buying against FPI selling over the same sessions.

    Both series must cover identical reporting dates; unmatched dates are
    excluded rather than zero-filled and gross rows never mix with net rows.
    Co-occurrence only — no order, motivation or intent is inferred.
    """
    fpi, dii, common, exclusions = matched_sessions(rows_fpi, rows_dii, as_of)
    window = [d for d in common if d <= day][-sessions:]
    if len(window) < sessions:
        return None
    fpi_net = sum(fpi[d].value for d in window)
    dii_net = sum(dii[d].value for d in window)
    if fpi_net >= 0 or dii_net <= 0:
        return None
    # Matched offset: only the smaller side can offset the other. Adding the
    # two magnitudes (dii_net - fpi_net) would overstate domestic buying that
    # offsets foreign selling, because DII buying beyond the FPI selling
    # magnitude offsets nothing that was sold.
    fpi_selling = -fpi_net
    offset_amount = min(dii_net, fpi_selling)
    if offset_amount < OFFSET_MIN:
        return None
    return {
        "state": "dii_offset_fpi_selling",
        "as_of": day.isoformat(),
        "matched_sessions": len(window),
        "fpi_net_cr": float(fpi_net),
        "dii_net_cr": float(dii_net),
        "offset_size_cr": float(offset_amount),
        "gross_opposing_flow_cr": float(fpi_selling + dii_net),
        "unoffset_fpi_selling_cr": float(fpi_selling - dii_net) if dii_net < fpi_selling else 0.0,
        "excess_dii_buying_cr": float(dii_net - fpi_selling) if dii_net > fpi_selling else 0.0,
        "unmatched_sessions_excluded": exclusions["fpi_unmatched_sessions"] + exclusions["dii_unmatched_sessions"],
        "gross_rows_excluded": exclusions["fpi_gross_rows_excluded"] + exclusions["dii_gross_rows_excluded"],
        "basis": "co-occurrence of opposite-sign net flows over identical reporting sessions; offset size is the smaller opposing magnitude, not evidence of intent or absorption capacity",
    }


def persistence(rows_fpi, rows_dii, day, *, sessions=3, horizon=PERSISTENCE_SESSIONS, as_of=None):
    """Retrospective follow-up assessment of a detected offset.

    The detection window (sessions ending at `day`) is the signal observable
    on the detection date. Sessions strictly after `day` are follow-up
    evidence gathered later and only count when both series reported the
    same session; the verdict is always labelled retrospective and is never
    described as a signal known on the detection date.
    """
    first = offset(rows_fpi, rows_dii, day, sessions=sessions, as_of=as_of)
    if first is None:
        return None
    fpi, dii, common, _ = matched_sessions(rows_fpi, rows_dii, as_of)
    detection = [d for d in common if d <= day][-sessions:]
    detection_avg = sum(dii[d].value for d in detection) / len(detection)
    follow_up = [d for d in common if d > day][:horizon]
    result = {
        "state": "first",
        "persistence": "insufficient_history",
        "as_of": day.isoformat(),
        "detection": {
            "sessions": len(detection),
            "dii_daily_avg_cr": float(detection_avg),
            "semantics": "signal observable on the detection date",
        },
        "follow_up": {
            "sessions": len(follow_up),
            "required": horizon,
            "semantics": "retrospective assessment using evidence available only after the detection date; not a signal known on that date",
        },
    }
    if len(follow_up) < horizon:
        return result
    tail_fpi = sum(fpi[d].value for d in follow_up)
    tail_dii = sum(dii[d].value for d in follow_up)
    if tail_fpi >= 0 or tail_dii <= 0:
        result["state"] = "dissipated"
        result["persistence"] = "no"
        return result
    # Fair comparison: daily average DII buying in each matched window
    tail_avg = tail_dii / len(follow_up)
    ratio = tail_avg / detection_avg if detection_avg else Decimal("0")
    verdict = "sustained" if ratio >= ABSORPTION_DECAY else "weakening" if ratio > 0 else "not_offsetting"
    result["state"] = f"persistence_{verdict}"
    result["persistence"] = verdict
    result["offset_ratio"] = round(float(ratio), 3)
    result["follow_up"]["dii_daily_avg_cr"] = float(tail_avg)
    return result


def sip_response(rows_sip, rows_returns, as_of, *, lag_months=SIP_RETURN_LAG_MONTHS):
    """Whether household SIP contributions differ after rising vs falling returns.

    SIP contributions in month M are compared with the index return of month
    M - `lag_months`: returns strictly precede contributions by the
    configured response lag, so co-movement is at best a lagged response.
    Both absolute contribution levels and month-over-month contribution
    growth are reported, because a long-run upward trend can dominate a
    level comparison; the growth view partially controls for that trend.
    Gross instalment contributions cannot distinguish new registrations,
    discontinuations or switches between schemes.
    """
    cutoff = as_of.date()
    sip_by_month = {}
    for row in sorted((r for r in rows_sip if r.period_end <= cutoff and r.retrieved_at <= as_of), key=lambda x: x.period_end):
        sip_by_month[(row.period_end.year, row.period_end.month)] = row.value  # latest revision wins
    returns_by_month = {}
    for row in rows_returns:
        if row.period_end > cutoff or row.retrieved_at > as_of:
            continue  # never use returns not yet known at the evaluation date
        returns_by_month[(row.period_end.year, row.period_end.month)] = row.value
    comparisons = []
    skipped_missing_return = 0
    skipped_missing_prior_sip = 0
    for (year, month), value in sorted(sip_by_month.items()):
        prior_y, prior_m = _shift_month(year, month, -lag_months)
        prior_return = returns_by_month.get((prior_y, prior_m))
        if prior_return is None:
            skipped_missing_return += 1
            continue
        prev_y, prev_m = _shift_month(year, month, -1)
        previous = sip_by_month.get((prev_y, prev_m))
        growth = None
        if previous is not None and previous != 0:
            growth = (value - previous) / previous * Decimal("100")
        else:
            skipped_missing_prior_sip += 1
        comparisons.append((value, prior_return, growth))
    if len(comparisons) < SIP_MIN_MONTHS:
        return None
    rising = [(value, growth) for value, ret, growth in comparisons if ret > 0]
    falling = [(value, growth) for value, ret, growth in comparisons if ret < 0]
    if not rising or not falling:
        return None  # need both directions before any comparison is meaningful
    avg_sip_up = sum(value for value, _ in rising) / len(rising)
    avg_sip_down = sum(value for value, _ in falling) / len(falling)
    growth_up = [g for _, g in rising if g is not None]
    growth_down = [g for _, g in falling if g is not None]
    all_growth = sorted(g for _, _, g in comparisons if g is not None)
    trend = all_growth[len(all_growth) // 2] if all_growth else None
    direction = "rising" if avg_sip_up > avg_sip_down else "falling" if avg_sip_up < avg_sip_down else "flat"
    state = f"sip_{direction}_after_recent_returns" if direction != "flat" else "sip_flat_after_recent_returns"
    return {
        "state": state,
        "avg_sip_cr_after_rising_returns": float(avg_sip_up),
        "avg_sip_cr_after_falling_returns": float(avg_sip_down),
        "avg_sip_mom_growth_pct_after_rising_returns": float(sum(growth_up) / len(growth_up)) if growth_up else None,
        "avg_sip_mom_growth_pct_after_falling_returns": float(sum(growth_down) / len(growth_down)) if growth_down else None,
        "median_sip_mom_growth_pct": float(trend) if trend is not None else None,
        "lag_months": lag_months,
        "months_observed": len(comparisons),
        "rising_return_months": len(rising),
        "falling_return_months": len(falling),
        "limited_directions": len(rising) < SIP_LIMITED_DIRECTIONS or len(falling) < SIP_LIMITED_DIRECTIONS,
        "months_skipped_missing_returns": skipped_missing_return,
        "months_skipped_missing_prior_sip": skipped_missing_prior_sip,
        "basis": "SIP levels and month-over-month growth compared after lagged returns; long-run contribution growth is reported separately because it can dominate a level comparison. Gross instalment flows cannot distinguish registrations, discontinuations or switches; co-movement only, not a household allocation decision",
        "as_of": as_of.isoformat(),
    }

def spurious_association_check(rows_fpi, rows_dii, rows_returns, day, *, as_of=None):
    """Flag associations that would look causal but fail basic order tests.

    Same-session FPI and DII flows are co-occurrence: reporting or retrieval
    timestamps cannot establish trading order. A forward return is reported
    only when the complete configured forward window — every required
    calendar month, starting the month after the evaluation date — is
    available. Percentage returns are compounded, never summed, and an
    incomplete horizon is always unresolved rather than a conclusion.
    """
    if as_of is None:
        fpi_rows, dii_rows, return_rows = rows_fpi, rows_dii, rows_returns
    else:
        fpi_rows, dii_rows, return_rows = _usable(rows_fpi, as_of), _usable(rows_dii, as_of), _usable(rows_returns, as_of)
    fpi_dates = {r.period_end for r in fpi_rows}
    dii_dates = {r.period_end for r in dii_rows}
    if day not in fpi_dates or day not in dii_dates:
        return {"state": "unresolved", "reason": "no same-session pairing"}
    forward = sorted(
        (r for r in return_rows if r.frequency == "monthly" and _first_of_month(r.period_end) > day),
        key=lambda x: x.period_end,
    )
    if not forward:
        return {"state": "unresolved", "reason": "no complete forward return month available"}
    # The forward window must begin with the calendar month after the offset
    # date and contain every configured forward month. A missing first month,
    # a missing intermediate month, or fewer than the configured number of
    # complete months all leave the horizon incomplete, so no outcome is
    # reported from an unfinished window.
    expected_first = _shift_month(day.year, day.month, 1)
    if (forward[0].period_end.year, forward[0].period_end.month) != expected_first:
        return {
            "state": "unresolved",
            "reason": "incomplete forward return window: monthly return missing for the first required forward month",
        }
    forward = forward[:SPURIOUS_FORWARD_MONTHS]
    if len(forward) < SPURIOUS_FORWARD_MONTHS:
        return {
            "state": "unresolved",
            "reason": f"incomplete forward return window: only {len(forward)} of {SPURIOUS_FORWARD_MONTHS} required forward months available",
        }
    for previous, current in zip(forward, forward[1:]):
        expected = _shift_month(previous.period_end.year, previous.period_end.month, 1)
        if (current.period_end.year, current.period_end.month) != expected:
            return {
                "state": "unresolved",
                "reason": "incomplete forward return window: missing monthly return between observed months",
            }
    return {
        "state": "co_occurrence_observed",
        "as_of": day.isoformat(),
        "forward_months": len(forward),
        "forward_return_pct": float(_compound([r.value for r in forward])),
        "caveat": "same-session flows are co-occurrence; reporting timestamps cannot establish trading order, and causality remains unproven without independently dated actor-response evidence",
    }



def evaluate(rows_fpi, rows_dii, rows_sip, rows_returns, as_of):
    """Aggregate investigation snapshot. Every finding is provisional.

    Rows are first filtered to what was observable at the evaluation
    timestamp: future-dated rows and rows ingested after the knowledge
    cutoff are excluded and counted, never zero-filled or silently used.
    """
    usable_fpi, usable_dii = _usable(rows_fpi, as_of), _usable(rows_dii, as_of)
    latest_flow_day = max((r.period_end for r in usable_fpi + usable_dii), default=None)
    results = {
        "as_of": as_of.isoformat(),
        "offset": None,
        "persistence": None,
        "sip_response": None,
        "spurious_check": None,
        "excluded_observations": {
            "fpi": _excluded_counts(rows_fpi, as_of),
            "dii": _excluded_counts(rows_dii, as_of),
            "sip": _excluded_counts(rows_sip, as_of),
            "returns": _excluded_counts(rows_returns, as_of),
        },
        "data_freshness": {},
        "observed_vs_hypothesized": {
            "observed": [
                "FPI net selling over matched reporting sessions",
                "DII net buying over the same reporting sessions",
                "SIP contribution levels and month-over-month growth",
                "derived month-over-month index returns",
            ],
            "hypothesized_not_observed": [
                "actor motivation or intent behind any flow",
                "the order in which investor groups actually traded",
                "absorption capacity or a feedback loop",
                "future allocation behaviour",
            ],
        },
    }
    if latest_flow_day:
        results["offset"] = offset(rows_fpi, rows_dii, latest_flow_day, as_of=as_of)
        results["persistence"] = persistence(rows_fpi, rows_dii, latest_flow_day, as_of=as_of)
        results["spurious_check"] = spurious_association_check(rows_fpi, rows_dii, rows_returns, latest_flow_day, as_of=as_of)
    if rows_sip:
        results["sip_response"] = sip_response(rows_sip, rows_returns, as_of)
    for key, rows in (("fpi", rows_fpi), ("dii", rows_dii), ("sip", rows_sip), ("returns", rows_returns)):
        usable = _usable(rows, as_of)
        latest = max((r.period_end for r in usable), default=None)
        results["data_freshness"][key] = {
            "latest_period_end": latest.isoformat() if latest else None,
            "days_behind_as_of": (as_of.date() - latest).days if latest else None,
        }
    results["limitation"] = (
        "All findings are descriptive co-occurrence. Flows data carries no actor "
        "motivation; FPI/DII attribution follows exchange publisher conventions and "
        "could change definition without notice. Reporting timestamps cannot establish "
        "trading order. Follow-up assessments use evidence gathered after the detection "
        "date and are never treated as signals known on that date. This is not evidence "
        "of a feedback loop, absorption capacity, or future allocation behaviour."
    )
    return results
