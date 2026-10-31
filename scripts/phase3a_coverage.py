"""Read-only exploratory point-in-time coverage audit for isolated environments.

Run: APP_ENV=staging DATABASE_URL=... python -m scripts.phase3a_coverage
No thresholds are fitted and no predictive performance is calculated.
"""
import json
from datetime import datetime, timezone
from sqlalchemy.orm import Session
from packages.domain.settings import settings
from packages.domain.store import engine
from packages.scoring.engine_v2 import compute_v2

PERIODS = ("2018-12-31T18:29:00+05:30", "2020-12-31T18:29:00+05:30", "2022-12-31T18:29:00+05:30", "2024-12-31T18:29:00+05:30", "2025-12-31T18:29:00+05:30", "2026-10-30T18:29:00+05:30")


def audit(session: Session, demo: bool = False) -> list[dict]:
    output = []
    for label in PERIODS:
        as_of = datetime.fromisoformat(label)
        if as_of > datetime.now(timezone.utc):
            continue
        result = compute_v2(session, as_of, demo=demo, vintage_mode="system_known", with_momentum=False)
        metrics = result["metrics"]
        selected = {"usd_inr_spot", "fx_gross_reserves_usd", "rbi_net_forward_usd", "fpi_equity_net_inr", "fpi_debt_net_inr", "india_10y_yield", "brent_usd"}
        known = [m["id"] for m in metrics if m["id"] in selected and m["status"] in {"verified", "revised", "demo"}]
        output.append({"as_of": label, "known_external_indicators": known, "known_count": len(known), "external_cycle_score": next(c["score"] for c in result["cycles"] if c["id"] == "fx"), "calibration_status": "exploratory_only" if len(known) >= 5 else "insufficient_point_in_time_data"})
    return output


def main():
    config = settings()
    if config.environment not in {"development", "demo", "staging"}:
        raise ValueError("Coverage audit is restricted to isolated environments")
    with Session(engine()) as session:
        print(json.dumps({"mode": "demo" if config.demo_mode else "live", "periods": audit(session, config.demo_mode)}, indent=2))


if __name__ == "__main__":
    main()
