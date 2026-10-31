from functools import lru_cache
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parents[2]


@lru_cache
def registry(phase2=False):
    items = {item["id"]: item for item in yaml.safe_load((ROOT / "config/indicators.yaml").read_text())["indicators"]}
    if phase2:
        for item in yaml.safe_load((ROOT / "config/indicators.phase2.yaml").read_text())["indicators"]:
            frequency = item["frequency"]
            defaults = {"direction_of_stress": "contextual", "max_age_hours": {"business_daily": 72, "weekly": 240, "monthly": 1080, "quarterly": 2880, "annual": 10000, "event": 10000}[frequency], "publication_lag_days": 0, "required_for_score": False, "source_priority": ["manual_import"]}
            items[item["id"]] = {**defaults, **item}
    return items


@lru_cache
def rules(version="v1"):
    if version not in {"v1", "v2"}:
        raise ValueError("Unsupported ruleset")
    data = yaml.safe_load((ROOT / f"config/rules.{version}.yaml").read_text())
    validate_rules(data)
    return data


def validate_rules(data):
    if sum(data["cycle_weights"].values()) != 100 or any(w < 0 for w in data["cycle_weights"].values()):
        raise ValueError("Cycle weights must be nonnegative and sum to 100")
    for cycle, signals in data["cycle_signals"].items():
        if signals and (sum(s["weight"] for s in signals.values()) != 100 or any(s["weight"] < 0 for s in signals.values())):
            raise ValueError(f"Signal weights for {cycle} must sum to 100")
        for signal in signals.values():
            g, a, r = (signal[k] for k in ("green", "amber", "red"))
            if not (g < a < r or g > a > r):
                raise ValueError("Thresholds must be strictly monotonic")
    if data["version"] == "v1" and data["fx_alert"]["id"] != "FX_LOOP_WATCH":
        raise ValueError("Unexpected FX alert ID")
    if data["version"] == "v2":
        ids = [item["id"] for item in data["alerts"]]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate alert rule IDs")
    return data
