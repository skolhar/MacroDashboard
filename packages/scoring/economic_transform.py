"""Versioned, frequency-aware economic normalization; never mutates source facts."""
from datetime import date, timedelta
from decimal import Decimal
from pathlib import Path
from statistics import median, pstdev
import yaml

CONFIG_PATH = Path(__file__).resolve().parents[2] / "config/economic_transformations.v2.yaml"
MAX_GAP = {"business_daily": 6, "daily": 5, "weekly": 11, "fortnightly": 35, "monthly": 45, "quarterly": 110, "annual": 400}


def configuration():
    cfg = yaml.safe_load(CONFIG_PATH.read_text())
    if cfg.get("version") != "economic-transformations-v2":
        raise ValueError("Unsupported transformation version")
    return cfg


def _period_before(day: date, frequency: str, count: int):
    if frequency == "annual":
        return (day.year - count, day.month)
    if frequency == "quarterly":
        n = day.year * 12 + day.month - 1 - 3 * count
        return (n // 12, n % 12 + 1)
    if frequency == "monthly":
        n = day.year * 12 + day.month - 1 - count
        return (n // 12, n % 12 + 1)
    return None


def _consecutive(rows):
    return all((b["date"] - a["date"]).days <= MAX_GAP.get(b["frequency"], 90) for a, b in zip(rows, rows[1:]))


def _reference(rows, index, count):
    current = rows[index]
    frequency = current["frequency"]
    if frequency == "fortnightly" and count in {26, 52}:
        target = current["date"] - timedelta(days=365 if count == 26 else 730)
        candidates = [row for row in rows[:index] if abs((row["date"] - target).days) <= 17]
        return min(candidates, key=lambda row: abs((row["date"] - target).days)) if candidates else None
    period = _period_before(current["date"], frequency, count)
    if period:
        return next((r for r in rows[:index] if (r["date"].year, r["date"].month) == period), None)
    if index < count:
        return None
    chunk = rows[index - count:index + 1]
    return chunk[0] if _consecutive(chunk) else None


def transform_series(rows, spec):
    """Return transformed rows; absent inputs stay absent and raw values remain attached."""
    rows = sorted(rows, key=lambda r: r["date"])
    kind = spec.get("primary", "raw")
    window = int(spec.get("window", 3))
    output = []
    for index, current in enumerate(rows):
        prior = _reference(rows, index, 26 if kind in {"yoy_pct", "seasonally_comparable"} and current["frequency"] == "fortnightly" else 12 if kind in {"yoy_pct", "seasonally_comparable"} and current["frequency"] == "monthly" else 1 if kind in {"yoy_pct", "seasonally_comparable"} else window if kind in {"rolling_growth"} else 1)
        value = current["value"]
        used = [current]
        base_effect_possible = False
        if kind == "raw":
            pass
        elif kind in {"yoy_pct", "mom_pct", "rolling_growth"}:
            if prior is None or prior["value"] <= 0 or current["value"] <= 0:
                continue
            if any(prior["date"] < date.fromisoformat(str(point)) <= current["date"] for point in spec.get("definition_breaks", [])):
                continue
            value = (current["value"] / prior["value"] - 1) * Decimal(100)
            used.append(prior)
            if kind == "yoy_pct" and spec.get("base_effect_drop_pct"):
                two_years = _reference(rows, index, 24 if current["frequency"] == "monthly" else 2)
                if two_years and two_years["value"] > 0 and prior["value"] < two_years["value"] * (1 - Decimal(str(spec["base_effect_drop_pct"])) / 100):
                    base_effect_possible = True
                    used.append(two_years)
        elif kind in {"first_difference", "momentum", "seasonally_comparable"}:
            if prior is None:
                continue
            value = current["value"] - prior["value"]
            used.append(prior)
        elif kind in {"growth_change", "acceleration"}:
            before = _reference(rows, index, 2)
            if prior is None or before is None:
                continue
            if kind == "growth_change":
                if before["value"] <= 0 or prior["value"] <= 0 or current["value"] <= 0:
                    continue
                value = (current["value"] / prior["value"] - prior["value"] / before["value"]) * Decimal(100)
            else:
                value = current["value"] - 2 * prior["value"] + before["value"]
            used.extend([prior, before])
        elif kind in {"rolling_sum", "rolling_deviation", "rolling_volatility"}:
            if index < window - 1:
                continue
            chunk = rows[index - window + 1:index + 1]
            if not _consecutive(chunk):
                continue
            used = chunk
            if kind == "rolling_sum":
                value = sum((r["value"] for r in chunk), Decimal(0))
            elif kind == "rolling_deviation":
                if index < window:
                    continue
                history = rows[index - window:index]
                if not _consecutive(history + [current]):
                    continue
                value = current["value"] - Decimal(str(median(r["value"] for r in history)))
                used = history + [current]
            else:
                if any(r["value"] <= 0 for r in chunk):
                    continue
                returns = [float((b["value"] / a["value"] - 1) * 100) for a, b in zip(chunk, chunk[1:])]
                value = Decimal(str(pstdev(returns)))
        else:
            raise ValueError(f"Unknown economic transformation: {kind}")
        output.append({**current, "value": value, "raw_value": current["value"], "transform": kind, "transform_unit": spec.get("unit", current.get("unit")), "base_effect_possible": base_effect_possible, "transform_inputs": [{"kind": r["kind"], "id": r["id"], "revision": r["revision"]} for r in used]})
    return output


def spread_series(left, right, key, unit="percentage_points"):
    """Same-period spread; period/frequency mismatches remain unavailable."""
    right_by_period = {r["date"]: r for r in right}
    output = []
    for a in left:
        b = right_by_period.get(a["date"])
        if b is None or a["frequency"] != b["frequency"]:
            continue
        output.append({**a, "series": key, "kind": "derived_spread", "value": a["value"] - b["value"], "raw_value": None, "transform": "spread", "transform_unit": unit, "transform_inputs": a["transform_inputs"] + b["transform_inputs"], "source": f"{a['source']} / {b['source']}"})
    return output
