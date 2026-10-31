# Phase 2.5 completion report — independent review candidate

Branch: `feature/phase2-5-live-data`, based on open Phase 2 PR #1. This branch has **not** been merged or deployed. SmartHedge production remains unchanged.

## Delivered

- Isolated Docker Compose staging project, independent PostgreSQL volume, loopback-only services, explicit staging labels, restricted Caddy admin path, healthchecks and rollback instructions.
- Additive Alembic `0003` migration for named scoped operator credentials, audit events, shared database rate counters and immutable alert evaluation history. Offline issue/revoke/rotation tools, trusted-proxy validation and a staging-only Treasury scheduler.
- Official Treasury adapter now uses a longer bounded timeout and retries transient failures. Source catalog marks RBI, NSDL, AMFI, MoSPI and licensed indicators as manual-only or unavailable until rights and endpoints are reviewed.
- Separate data-confidence score, real-data coverage, last successful ingestion and point-in-time cycle history in the monitor. Live history transforms reject missing periods. Alert evaluation events allow replay beyond the previous 60-session window when historic events were actually recorded.
- Regression tests for auth/revocation, proxy spoofing and alternate paths, concurrent worker-shared rate limits and store failures, source failure, duplicate ingestion, operational confidence labeling, data gaps, checkpoint persistence, late observations, revised vintages, multi-year alert state and point-in-time filtering.

## Verified observation status

| Status | Indicators |
|---|---|
| **Actual verified observations in isolated staging** | U.S. Treasury 10-year par yield: 21 official October 2026 daily XML rows. |
| **Manual-only, no verified observations yet** | RBI USD/INR, India 10Y, reserves and forward position; NSDL FPI flows; AMFI SIP/category flows; MoSPI CPI; Indian IT/software/DII data. |
| **Unavailable pending licensed feed/rights** | Brent, DXY, Nasdaq 100, U.S. HY spreads, Nifty earnings revisions and valuation data, plus other licensed market series. |
| **Synthetic** | Existing Phase 1 demo fixture only; never used in live staging scoring. |

One source-backed indicator does not satisfy any six-cycle composite coverage gate. The staging dashboard correctly returns **N/A** for the reflexivity risk score and displays 6/100 data confidence. No live alert is claimed as financially validated.

All 42 registered IDs are classified below. “Manual-only” means a documented, rights-cleared import is possible; **none** of those IDs currently has a verified staging observation.

- **Connected (1):** `us_10y_yield`.
- **Manual-only, pending source/rights review (29):** `usd_inr_spot`, `fx_gross_reserves_usd`, `rbi_net_forward_usd`, `india_10y_yield`, `fpi_equity_net_inr`, `sip_contribution_inr`, `fpi_debt_net_inr`, `fcnr_deposits_usd`, `midcap_mf_net_inr`, `smallcap_mf_net_inr`, `sip_discontinuation_ratio`, `sip_registration_count`, `india_cpi_yoy`, `india_repo_rate`, `current_account_pct_gdp`, `net_services_exports_usd`, `india_software_services_exports_usd`, `it_major_usd_revenue_growth`, `tcs_usd_revenue_growth`, `infosys_usd_revenue_growth`, `hcltech_usd_revenue_growth`, `wipro_usd_revenue_growth`, `techmahindra_usd_revenue_growth`, `it_major_headcount_yoy`, `it_major_operating_margin`, `it_ai_revenue_share`, `it_ai_deal_tcv_usd`, `it_ai_pricing_pressure`, `hyperscaler_capex_guidance_growth`.
- **Unavailable pending licensed feed/redistribution rights (12):** `brent_usd`, `midcap150_pe`, `smallcap250_pe`, `nifty_eps_revision_3m`, `dxy`, `nifty50_price`, `dii_equity_net_inr`, `nasdaq100_price`, `us_ig_oas`, `us_high_yield_oas`, `market_breadth_pct_above_200dma`, `nifty50_trailing_pe`.

## Validation and open risks

- Initial Phase 2.5 `.venv/bin/python -m pytest -q`: **44 passed**, one upstream Starlette deprecation warning. PR #2 review follow-up: **48 passed**, same warning.
- `npm run typecheck` and `npm run build` in `apps/web`: passed. The isolated Docker web build also passed with an existing CSS autoprefixer warning.
- Playwright in pinned v1.56.0 container: **3 passed** (Phase 1 demo, Phase 2 monitor and Phase 2.5 staging at desktop/mobile widths).
- Fresh isolated PostgreSQL migration: `alembic current` reported `0003 (head)`. Staging API and DB healthchecks passed; Caddy blocked admin GET/POST with 403. Health, dashboard, source-health and historical replay endpoints returned 200.
- Official Treasury staging ingestion: HTTP 200 and 21 rows inserted. A second authenticated run inserted 0 and reported 21 duplicates. The scheduler completed a further idempotent run, then was stopped. Replay before first ingestion showed no source-backed reading.

Known limits: historical Treasury publication times are conservative first-ingestion timestamps; NSE 2027 remains unverified; source rights and licenses for Indian/market feeds are outstanding; v2 thresholds and indicator definitions lack historical activation/version validation; event checkpoints only exist from actual ingestion onward; operator credentials are still bearer tokens and require secure distribution; the database rate limiter adds a write per request and needs load testing before public scale. Independent financial and security review remains required.

## PR #2 staging review follow-up

- Replayed checkpoint history across 2024–2026, including a late-arriving observation and a later revised vintage. Tests verify that the earlier replay excludes future ingestion and that persisted evaluation evidence and alert transitions are not overwritten.
- The monitor and API now label Data Confidence as an **operational coverage/quality index, not statistical certainty**. It remains distinct from the 0–100 reflexivity risk index.
- Narrowed the staging trusted proxy from the whole Docker subnet to Caddy's pinned `172.30.51.10/32` address. Tested forged `X-SmartHedge-Client-IP` and `X-Forwarded-For` headers through Caddy, direct loopback API and another staging container. No fake-IP quota bucket was created.
- Added a reproducible loopback-only load script and concurrent regression tests. Staging PostgreSQL-backed HTTP quota: **300 requests / 24 workers / 2.7 seconds; 240 returned 200, 60 returned 429; p50 185 ms, p95 349 ms**. Expired-counter cleanup removed exactly one test row. A temporary **staging-only** database outage produced a generic 503; health/dashboard recovered to 200 with the Treasury data retained after restart.
- Final review validation: **48 Python tests passed**, Next.js build and sequential typecheck passed, **3 Playwright tests passed**. Merge-path verification is recorded in the PR after the review commits. Production remains untouched; staging volumes remain intact and the scheduler is stopped.
