"""Operator-run daily EOD Yahoo research refresh; schedule via isolated cron.

Example: MARKET_DATA_RESEARCH_ENABLED=true python -m packages.jobs.market_refresh
         --instrument nifty50 --start 2018-01-01
"""
import argparse
import json
import time
from datetime import date, datetime, timedelta, timezone
from sqlalchemy import select
from sqlalchemy.orm import Session
from packages.domain.models import MarketFetchRun
from packages.domain.settings import settings
from packages.domain.store import engine
from packages.market.base import instruments
from packages.market.operations import refresh
from packages.market.providers import provider_for


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--instrument", action="append", help="registry ID; repeat for multiple symbols")
    parser.add_argument("--start", type=date.fromisoformat, help="inclusive historical backfill start")
    parser.add_argument("--end-exclusive", type=date.fromisoformat)
    parser.add_argument("--force", action="store_true", help="bypass six-hour incremental cooldown")
    args = parser.parse_args()
    cfg = settings()
    if not cfg.market_research_enabled or cfg.environment not in {"development", "staging"}:
        parser.error("Isolated market research must be explicitly enabled")
    selected = args.instrument or ["nifty50", "usd_inr_yahoo", "wti_front_yahoo", "brent_front_yahoo", "gold_front_yahoo"]
    known = instruments()
    if any(item not in known for item in selected):
        parser.error("Unknown market instrument")
    provider = provider_for(cfg.market_provider)
    if any(known[item].symbol(provider.name) is None for item in selected):
        parser.error("Selected provider has no symbol mapping")
    database = engine()
    failed = False
    for index, id in enumerate(selected):
        if index:
            time.sleep(2)  # modest provider cadence; no circumvention
        with Session(database) as session:
            previous = session.scalar(select(MarketFetchRun).where(MarketFetchRun.instrument_id == id, MarketFetchRun.provider == provider.name).order_by(MarketFetchRun.finished_at.desc()).limit(1))
            if not args.force and args.start is None and previous and previous.finished_at >= datetime.now(timezone.utc) - timedelta(hours=6):
                print(json.dumps({"instrument_id": id, "status": "cooldown", "last_fetch_at": previous.finished_at.isoformat()}), flush=True)
                continue
            try:
                result = refresh(session, provider, known[id], args.start, args.end_exclusive)
                print(json.dumps({"instrument_id": id, **result}), flush=True)
            except Exception as exc:
                failed = True
                print(json.dumps({"instrument_id": id, "status": "failed", "error_code": type(exc).__name__}), flush=True)
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
