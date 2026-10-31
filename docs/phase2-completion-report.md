# Phase 2 completion report — feature branch review candidate

Branch: `feature/phase2-reflexivity-engine`. This report describes the code prepared for a pull request. **No production deployment, production migration or merge has been performed.** The current production website remains unchanged.

## Implemented

- Audited Phase 1 in `phase2-audit.md`, preserved v1 endpoints/rules and the 12-indicator demo view.
- Removed embedded Compose database password and admin token fallback. Added explicit environment modes, production fail-closed checks, admin token digest authentication, per-process rate limits, request-size checks and structured validation errors.
- Added the additive `0002` migration for demo/live provenance, source references, content hashes, ingestion runs and alert transitions. Froze the initial migration schema so a fresh installation upgrades cleanly. Production/staging startup requires an operator-run migration; demo/development startup still migrates and seeds.
- Added 30 Phase 2 registry indicators, including individual USD revenue trends for five Indian IT majors, a strict reviewed CSV importer, an unavailable adapter, and an official U.S. Treasury XML adapter. Imports validate units, dates, source references, vintages, quality, numeric ranges and outliers; duplicate imports are idempotent.
- Added reviewed 2026 India and 2026–27 U.S. exchange/Treasury-proxy calendar schedules, six v2 cycle scoring configurations, coverage/confidence, momentum, acceleration and confirmation. NSE 2027 is explicitly unverified pending its circular. Missing cycles produce N/A without weight redistribution.
- Added six cross-domain inflection rules with evidence, persistence, recovery hysteresis, explicitly quarterly release-count cadence for IT, historical replay and stored state changes after ingestion.

## PR #1 review follow-up

- Extracted and tested covered-weight cycle normalization and fixed-weight composite aggregation. A missing indicator is excluded from both sides of its cycle mean; a missing cycle makes the composite N/A.
- Extended daily alert reconstruction from 15 to 60 verified sessions and reset recovery streaks when a publication is missing. Regression sequences cover more than 15 sessions and repeated deterministic evaluation. Historical replay beyond the bounded 60-session window still needs event-sourced checkpoints.
- Split U.S. equity market sessions from the Treasury federal-publication proxy and added their published 2027 dates. India 2027 is represented as unverified and fails closed until NSE publishes and an operator reviews the official cash-market calendar. The update procedure is in `calendar-maintenance.md`.
- Renamed the IT persistence settings to `watch_releases`, `trigger_releases`, `confirm_releases` and `recovery_releases`; duplicate vintages for a reporting quarter do not count as separate releases.
- Reviewed shared-token authentication and process-local rate limiting in `phase2-security-review.md`. Regression tests confirm fail-closed authentication and independent limiter instances. Managed identity and ingress/shared-store rate limiting remain production prerequisites.
- Extended the existing monitor design with six cycle cards, regime/coverage, source-health details, selectable indicator charts and threshold lines, alert evidence/history and metric provenance. Demo and live mode labels differ visibly.

Preview: [v2 monitor with synthetic demonstration inputs](screenshots/phase2-monitor-demo.png).

## Validation performed

- PR #1 follow-up: `.venv/bin/python -m pytest -q`: 31 passed, one third-party Starlette deprecation warning. Targeted `tests/test_phase2.py`: 22 passed.
- `npm run typecheck` from `apps/web`: passed.
- `npm run build` from `apps/web`: passed.
- Playwright in `mcr.microsoft.com/playwright:v1.56.0-noble`: 2 passed against the isolated local demo stack (Phase 1 and v2 monitor at 1440px and 375px).
- Fresh isolated SQLite `alembic upgrade head`: passed. Existing local demo PostgreSQL migrated and served `/api/v1/health`, v2 dashboard, and Next.js page.
- Official Treasury feed read-only smoke request: timed out at 10 seconds on the validation host. A representative XML parser test passes; no real value was ingested or presented.
- Web runtime dependency audit: zero reported vulnerabilities. Final isolated local Compose rebuild passed; health, v1 dashboard, v2 dashboard, replay and source-health endpoints returned successfully.

## Feed status

- **Adapter implemented, no successful live fetch:** official U.S. Treasury 10-year par yield XML.
- **Manual import only, no live observations configured:** all RBI, NSE, AMFI, MoSPI, company filing, FPI/DII, commodity, FX, index, credit and consensus indicators listed in `data-sources.md`.
- **Synthetic:** the existing Phase 1 fixture, isolated in demo mode. It is never eligible for live scores.

## Outstanding review items and risks

1. Obtain and verify redistribution rights and exact publication/revision semantics for every Indian and licensed vendor feed. No commercial feed key or entitlement was supplied.
2. Successfully smoke-test the Treasury XML adapter from the intended staging environment before enabling it; conservative first-ingestion publication timestamps limit historical replay for backfilled rows.
3. Review v2 rules and weights with point-in-time historical data. Thresholds are uncalibrated hypotheses, and alert co-occurrence is not causal proof.
4. Verify RBI forward-position sign, maturities and instrument definitions before enabling a numeric stress signal. No net usable reserves proxy is calculated.
5. Replace the shared admin token and in-memory rate limiter with a managed identity and trusted-ingress or distributed limiter for multi-operator or multi-replica production use. See `phase2-security-review.md`.
6. Obtain and review NSE's 2027 cash-market calendar before enabling India daily scoring in 2027. Recheck annual and ad hoc exchange circulars as described in `calendar-maintenance.md`.
7. Alert transition history is recorded on approved imports/runs. A scheduled job and operational monitoring should be configured before public launch.
8. The API still exposes OpenAPI docs through Caddy; the deployment owner should decide whether to restrict them for production. Production Caddy, secrets and database were not altered.
9. The v2 chart and momentum comparisons are provisional research displays. They require frequency-aware refinement, historical calibration and independent methodology review before investment use.
10. Daily alert replay is bounded to 60 verified sessions. Multi-year historical state reconstruction needs event-sourced checkpoints or a full verified calendar/history scan.

The pull request must remain open for independent technical and financial review. Do not merge, deploy or migrate production without explicit approval.
