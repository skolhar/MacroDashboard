# SmartHedge — macro reflexivity and market research

SmartHedge is a FastAPI, Next.js and PostgreSQL research application for Indian macroeconomic feedback loops. The Inflection Monitor has six experimental risk cycles, point-in-time observations and explainable alerts. The External Liquidity Monitor keeps missing confirmation distinct from contradictory evidence. **A 0–100 risk index is not a crash probability or a trading recommendation.**

Assignment 2 adds a private [Cycle Intelligence](http://localhost:3000/intelligence) research view with six inspectable economic mechanisms, tentative state and inflection assessment, conditional 1–3 and 3–6 month outlooks, and human investigations. It uses separate exploratory evidence; no unapproved source data is promoted to verified observations. See [methodology and evidence limits](docs/assignment2-cycle-intelligence.md). Private research requires separate UI credentials and research-scoped operator tokens; it is disabled in production and demo.

Assignment 3 adds [private anomaly discovery](http://localhost:3000/intelligence/discovery): cadence-aware persistence and provisional structural-break checks, configured cross-indicator research questions, retrospective source-known versus system-known reconstruction, and frozen provisional hypothesis investigations. These are statistical research leads, not established causal cycles. The six-cycle catalog is unchanged. See [discovery methodology](docs/assignment3-discovery.md).

Assignment 4 extends that private view with a focused 11-indicator Indian research registry, actual World Bank WDI/GEM annual and monthly acquisition, versioned economic transformations, explicit stale/missing coverage, and retrospective episode analysis. It has **no live reflexivity-cycle claim**: the actual-source demonstration found single-series patterns but no confirmed cross-indicator feedback candidate. See the [methodology](docs/assignment4-indian-macro.md) and [real-data report](docs/assignment4-real-data-report.md).

Assignment 5 adds private actor-response research using RBI Innovation Hub's experimental DBIE mirror for fortnightly bank credit/deposits, daily signed RBI liquidity operations, and weekly gross reserves. It tests chronological disturbances, later operations, counterforces and follow-up bank reports without treating correlation as causation. The [actual-source investigation](docs/assignment5-real-data-report.md) found contradictory evidence for a proposed 2025 RBI liquidity-injection response, not a confirmed feedback loop. See the [methodology and access limits](docs/assignment5-actor-response.md). Mirror data is not used by the public monitor.

The existing application has a separate, provider-neutral **market-data foundation** for daily Nifty, USD/INR, global futures proxies and a ten-symbol NSE ETF watchlist. Yahoo/yfinance is the initial research adapter; Upstox is a future adapter slot. Market prices never enter the governed RBI/NSDL/AMFI release tables or macro scores automatically. There is no brokerage connection, options execution or order routing.

## Current data status

| Area | Status |
| --- | --- |
| Bundled demo | Deterministic **synthetic** observations, labelled DEMO and isolated from live mode. No bundled market quote is real. |
| Official macro staging | U.S. Treasury 10-year is the only previously verified source-backed indicator in isolated staging. Indian source rights and release evidence remain pending. |
| RBI WSS reserves | [Phase 5 PR #8](https://github.com/skolhar/MacroDashboard/pull/8) is merged. It has an executable governed adapter but **zero actual RBI observations**. |
| Yahoo market research | This branch supports real, persistent daily prices in isolated development or staging when explicitly enabled. A live Nifty test ingested eight October 2026 bars into a temporary local database; a repeat inserted zero and reported eight duplicates. No Yahoo data was imported into production or the governed macro database. |
| Public production | Market-data display and ingestion stay disabled until storage and redistribution rights are reviewed. No development PR should be deployed or merged without approval. |

Yahoo/yfinance is an unverified secondary source. Its own documentation describes the Yahoo Finance API as intended for personal use; public archiving and redistribution are **not** authorised by the existence of a downloadable quote. WTI (`CL=F`) and Brent (`BZ=F`) are global continuous futures proxies, not MCX crude. Yahoo `INR=X` is not an RBI/FBIL published fixing. Futures roll history and adjusted prices need provider-specific validation. See [market-data operations and source review](docs/market-data-foundation.md).

## Start the existing demo

Copy `.env.example` to `.env`; set a strong `POSTGRES_PASSWORD` and a matching `DATABASE_URL` using `postgresql+psycopg://<user>:<url-encoded-password>@db:5432/<database>`. Then:

```sh
docker compose up --build
```

Open the [Inflection Monitor](http://localhost:3000), [External Liquidity Monitor](http://localhost:3000/external-liquidity), [Market Research](http://localhost:3000/markets), [API docs](http://localhost:8000/docs) and [health](http://localhost:8000/api/v1/health). Demo startup runs migrations and synthetic seeding only in demo/development; the market route shows `DATA_UNAVAILABLE` in demo mode and never substitutes demo prices.

## Isolated market research

Use a separate development database or [isolated staging](docs/staging-validation.md). Set `APP_ENV=development` or `staging`, `DEMO_MODE=false`, `MARKET_DATA_RESEARCH_ENABLED=true` and `MARKET_DATA_PROVIDER=yahoo` only in that private environment, then migrate its database. Production rejects the research flag. `upstox` is a reserved provider choice that stays unavailable until its adapter and entitlements exist. An operator can backfill or refresh daily end-of-day history:

```sh
alembic upgrade head
python -m packages.jobs.market_refresh --instrument nifty50 --start 2018-01-01
python -m packages.jobs.market_refresh --instrument nifty50
```

Run the incremental command daily through an isolated scheduler or cron. The job observes a six-hour cooldown for routine repeats and records failures without inserting synthetic values. Its default set is Nifty, Yahoo USD/INR, WTI, Brent and gold; use `--instrument` for each ETF. The provider requires no source API key. Administrative HTTP refresh uses the existing named operator `ingestion:run` scope; source access itself requires no credentials. Research history and status are at `/api/v1/market/instruments` and `/api/v1/market/instruments/{id}/history`.

Market bars have raw OHLC, separate adjusted close, exchange session date/timezone, currency, Yahoo symbol, retrieval timestamp, source URL and immutable content hash. Repeated identical bars are skipped; changed vendor bars become new vintages. Historical queries use only bars SmartHedge had retrieved by the requested `as_of`. Missing and stale data remain explicit. The new market tables are separate from `observations` and `source_release_reviews`.

## Source governance and deployment

Official Indian releases still require the [two-operator archive and approval process](docs/phase3b-source-archive.md). Phase 5 migration `0005` is on main. This branch adds `market_data_1` after `0005`, preserving one Alembic head. No production migrations, secrets or infrastructure are changed here.

The Caddy [production profile](Caddyfile) remains a separate reviewed deployment path. Scoped operator credentials and shared database rate limiting are required in staging/production. Keep credentials out of Git and frontend bundles.

## Validate

```sh
python3 -m venv .venv
. .venv/bin/activate
pip install -r requirements.txt
python -m pytest -q
cd apps/web
npm ci
npm run typecheck
npm run build
npx playwright install chromium
npm run test:e2e
```

Playwright uses a local demo API at `http://localhost:8000`; staging tests additionally use `STAGING_BASE_URL`. The repository also supports the pinned Playwright container when host browser libraries are unavailable.

## Project references

- [Issue #9](https://github.com/skolhar/MacroDashboard/issues/9) is the governing product scope. Its latest decision removes options execution and prioritises a working Yahoo/yfinance research system before any future Upstox adapter.
- [Market-data audit](docs/market-data-foundation-audit.md) compares open PRs #10, #11 and #13 and explains why this implementation does not merge their prototypes.
- [Market-data foundation](docs/market-data-foundation.md) covers symbols, historical depth, operations, rights and known limits.
- [Scoring methodology](docs/scoring-methodology.md), [data sources](docs/data-sources.md) and [Phase 4 acquisition audit](docs/phase4-acquisition-audit.md) describe the macro research path.

SmartHedge is research software. Its thresholds and market mappings require independent methodology, source-rights and point-in-time validation before any public investment-intelligence claim.
