"""Scheduler/operator-run daily India flow refresh: FPI/DII net flows and monthly SIP.

Example: APP_ENV=development python -m packages.jobs.india_flows_refresh --start 2026-04-01
"""
import argparse
import json
from datetime import date
from sqlalchemy.orm import Session
from packages.connectors.amfi_sip import fetch_sip
from packages.connectors.nse_flows import fetch as fetch_flows
from packages.domain.settings import settings
from packages.domain.store import engine
from packages.jobs.ingest import ingest_records


def refresh_once(session: Session, min_date: date) -> dict:
    """Ingest each independent source separately; one failure never blocks the other."""
    results = {}
    source_errors = {}
    try:
        raw, records = fetch_flows(min_date)
        results["fii_dii_flows"] = ingest_records(session, records, raw, "groww_fii_dii")
    except Exception as exc:
        source_errors["fii_dii_flows"] = type(exc).__name__
    try:
        raw, records = fetch_sip((min_date.year, min_date.month))
        results["sip_contributions"] = ingest_records(session, records, raw, "vrid_amfi_secondary")
    except Exception as exc:
        source_errors["sip_contributions"] = type(exc).__name__
    if not results and source_errors:
        raise RuntimeError(f"All India flow sources failed: {source_errors}")
    return {**results, **{f"source_error_{key}": value for key, value in source_errors.items()}}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", type=date.fromisoformat, required=True, help="inclusive backfill start")
    parser.add_argument("--end", type=date.fromisoformat, help="inclusive backfill end; defaults to today (UTC)")
    args = parser.parse_args()
    cfg = settings()
    if cfg.environment not in {"development", "staging"} or cfg.demo_mode:
        raise SystemExit("India flows refresh requires isolated non-demo development/staging")
    with Session(engine()) as session:
        print(json.dumps(refresh_once(session, args.start)), flush=True)


if __name__ == "__main__":
    main()
