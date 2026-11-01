# Market-data foundation: isolated Yahoo research

## Contract and boundaries

`packages/market/base.py` defines an instrument registry, normalized daily candle, batch and `MarketProvider.fetch_daily()` protocol. `YahooProvider` implements it with `yfinance.Ticker.history()` and no provider key. `MARKET_DATA_PROVIDER` selects the active provider for the API and CLI; `upstox` is a fail-closed placeholder. A future Upstox adapter must map its instruments, calendar, adjustment and contract semantics into the same batch; no Upstox account or brokerage integration is present.

Market bars and fetch runs are in separate `market_bars` and `market_fetch_runs` tables. They do not enter official `observations`, source-release reviews, reflexivity cycle scores or alerts. Each row retains raw OHLC, optional adjusted close, volume, provider/exchange symbol, market, currency, exchange timezone, session date, retrieval timestamp, source URL, quality and content hash. Futures rows identify only the vendor's continuous front-month symbol; the actual delivery contract and roll policy remain unverified. Exact retries are idempotent. A changed vendor bar creates a new immutable vintage. `as_of` reads use only versions retrieved by that time; historical market close alone is never treated as a SmartHedge-known timestamp.

The adapter asks yfinance for **raw** daily OHLC (`auto_adjust=False`) and keeps adjusted close separate. It checks currency and timezone metadata, finite prices, OHLC ordering and volume. Invalid/missing rows are rejected and counted, producing `secondary_partial`; an empty valid result fails. Futures prices may be negative, preserving the historically possible WTI case. Incomplete current local sessions are excluded. Network timeouts/rate-limit-like exceptions have at most three attempts with bounded exponential pauses; access denial or permanent errors fail closed. The CLI spaces symbols by two seconds and applies a six-hour incremental cooldown. No proxy rotation, cookie bypass or synthetic fallback is used.

## Live symbol and historical-depth check

On 1 November 2026, one paced live yfinance request per symbol asked for daily history from 2018-01-01 through 2026-10-31. All 15 candidate Yahoo symbols returned dated bars; the table reports the **observed window in that one request**, not a guaranteed provider archive or proof of scheme identity, rights, continuity or official market quality. The latest returned session was 2026-10-30 for all symbols.

| Instrument | Yahoo symbol | First returned session | Returned bars | Caveat |
| --- | --- | --- | ---: | --- |
| Nifty 50 | `^NSEI` | 2018-01-02 | 2,176 | Index level, not an ETF or total-return series |
| Yahoo USD/INR | `INR=X` | 2018-01-01 | 2,202 valid | Europe/London Yahoo timezone; 97 rows rejected by strict OHLC validation; not RBI/FBIL fixing |
| WTI futures proxy | `CL=F` | 2018-01-02 | 2,222 | Global continuous front-month proxy, not MCX crude |
| Brent futures proxy | `BZ=F` | 2018-01-02 | 2,223 | Global continuous futures proxy; roll definition unverified |
| Gold futures proxy | `GC=F` | 2018-01-02 | 2,222 | Global continuous futures proxy |
| Nifty 50 BeES | `NIFTYBEES.NS` | 2018-01-01 | 2,180 | Yahoo symbol accessible; scheme mapping needs ongoing official review |
| Nifty Next 50 ETF | `SETFNN50.NS` | 2018-01-01 | 2,180 | Same caveat |
| Midcap 150 ETF | `MIDCAPETF.NS` | 2024-06-19 | 584 | No 2018 history returned |
| Nasdaq 100 ETF | `MON100.NS` | 2018-01-01 | 2,181 | India-listed price may lag underlying US close/NAV |
| S&P 500 Top 50 ETF | `MASPTOP50.NS` | 2021-09-24 | 1,258 | India-listed price may lag underlying US close/NAV |
| Hang Seng BeES | `HNGSNGBEES.NS` | 2018-01-01 | 2,180 | India-listed price may lag underlying HK close/NAV |
| Gold BeES | `GOLDBEES.NS` | 2018-01-01 | 2,180 | ETF price is not spot bullion or NAV |
| Silver ETF | `SILVERCASE.NS` | 2025-03-24 | 394 | No 2018 history returned |
| Liquid ETF | `LIQUIDCASE.NS` | 2024-01-17 | 687 | Price is not an overnight yield or total return |
| Long-term gilt ETF | `LTGILTBEES.NS` | 2018-05-11 | 1,832 | Current benchmark/listing status still needs NSE/AMC confirmation |

Yahoo symbol availability is not permission to store or redistribute quotes. [yfinance's own documentation](https://ranaroussi.github.io/yfinance/) says Yahoo's API is intended for personal use. [Yahoo's permission guidance](https://legal.yahoo.com/us/en/yahoo/permissions/requests/index.html) says chart/screenshot permissions do not cover third-party stock quotes. SmartHedge therefore defaults `MARKET_DATA_RESEARCH_ENABLED=false`; it rejects true in production and demo. Any broader or public use needs a separate documented entitlement and publisher/exchange rights review. This branch performed a live **private temporary-database** Nifty smoke: eight bars inserted for 2026-10-20 through 2026-10-31, a repeat inserted zero/eight duplicates, and the research API returned eight bars with status `AVAILABLE`. No Yahoo prices were added to shared staging or production. All automated tests mock Yahoo.

## Operations

1. Use an isolated development/staging database. Set `APP_ENV=development` or `staging`, `DEMO_MODE=false`, `MARKET_DATA_RESEARCH_ENABLED=true`, `MARKET_DATA_PROVIDER=yahoo`, and a private `DATABASE_URL`. Run `alembic upgrade head`. Never point this research job at production.
2. Backfill one mapping at a time with `python -m packages.jobs.market_refresh --instrument nifty50 --start 2018-01-01`; the end is exclusive and defaults to the next UTC date. The maximum request span is 15 years. Add ETF IDs only after reviewing identity and rights. The default command refreshes the five underlying references. Incremental runs overlap the last seven calendar days to detect vendor changes.
3. Run `python -m packages.jobs.market_refresh` once daily after the relevant market close through an isolated scheduler. The six-hour cooldown protects routine repeats. `--force` is an operator override for controlled rechecks. Failure records `MarketFetchRun.status=failed` with a safe error code; prior prices are marked `SOURCE_FAILED_USING_PRIOR_BAR`, never silently treated as a fresh success.
4. Read `/api/v1/market/instruments` for catalog, freshness and source state, and `/api/v1/market/instruments/{id}/history?basis=raw|adjusted_close&as_of=...` for bars. The scoped administrative endpoint `/api/v1/admin/market/refresh` uses the existing `ingestion:run` operator permission and audit log. The `/markets` Next.js route is an attention-first drilldown alongside the existing macro monitors.
5. Inspect `secondary_partial` and rejected-row counts before analysis. Missing weekday dates are candidates only; exchange holidays, FX sessions, futures rolls and ETF corporate actions are not fully verified. A stale or failed source must not produce a directional model signal.

## Migration and PR order

This branch starts from current main migration `0004` and adds independent revision `market_data_1`. Open Phase 5 PR #8 separately adds `0005` from `0004`. Merging both without a migration reconciliation would create two Alembic heads. Review PR order, then rebase the later migration onto the first or add a small explicit Alembic merge revision. Neither PR is merged by this assignment.

## Validation (1 November 2026)

- Python: **66 passed**, one existing FastAPI/Starlette deprecation warning. Yahoo is mocked in automated tests.
- TypeScript typecheck and Next.js production build: passed. Playwright: **6 passed** across demo and isolated staging, including desktop/mobile market-route unavailable states.
- Alembic: fresh isolated SQLite and disposable loopback-only PostgreSQL reached `market_data_1 (head)`; both market tables existed on PostgreSQL. The disposable PostgreSQL container was removed.
- Live Yahoo research: all 15 candidate symbols returned daily history in a paced, read-only audit. The finalized adapter and CLI inserted eight actual Nifty bars into a fresh temporary SQLite database. The incremental CLI then returned `cooldown`. An earlier controlled repeat on a separate temporary database inserted zero and reported eight duplicates. The API returned eight stored bars with status `AVAILABLE`. No actual Yahoo prices were copied into the repository, shared staging, governed macro tables or production.
- Existing macro API contracts, scoring and the demo/staging browser flows remained intact. A public market score, trend forecast or macro attribution was not introduced.

Known limits: the Yahoo API can rate-limit or change without notice; source data are secondary and have no verified redistribution right. `INR=X` had 97 rows rejected by strict OHLC checks in the 2018-present audit and must be reconciled before analysis. Vendor futures rolls, adjusted-close history, ETF scheme identity/corporate actions, exchange holidays, international ETF NAV age and as-of market close definitions need independent verification. No Upstox adapter, trend/anomaly engine or public data activation is claimed.

## Next assignment

Validate scheme/exchange mappings and corporate actions against official NSE/AMC records, obtain market-data storage/display permission, then implement point-in-time price regime and anomaly rules using these normalized bars. Do not treat price-only signals as known macro-cycle influence or an investable prediction.
