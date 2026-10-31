# Phase 3A completion report

## Branch and integration state

Development branch: `feature/phase3a-india-macro-data`, based on PR #2 head `a11047f12666374d41bbbebc0425407f66ce094a`. PR #1 and PR #2 remain open, with successful latest `phase1` checks at initial audit. PR #2's merge base is exactly PR #1's head. No merge, production deployment, production secret change or production migration was performed. Phase 3A adds no database migration; staging remains at `0003 (head)`.

## Delivered

- Authenticated reviewed-release package path for RBI, NSDL, AMFI and a licensed Brent provider. It validates approved indicator/unit/provider mapping, publication evidence, rights declaration, source payload hash and vintage. RBI forward positions are deliberately blocked pending signed-definition review. These are reusable parsers and import controls, **not live feed connections**.
- Additive `/api/v1/external-liquidity` endpoint and `/external-liquidity` monitor with existing v2 cycle score and data confidence, cross-signal evidence classifications, source freshness, source-backed historical levels, alert evidence, and explicit demo/staging labels. FX depreciation alone never establishes a feedback-loop watch.
- [Isolated staging screen](screenshots/phase3a-external-liquidity-staging.png) captured with no Indian observations, showing DATA_UNAVAILABLE rather than fabricated charts.
- Read-only `scripts.phase3a_coverage` audit over the requested historical windows using system-known observations. The preliminary answer is N/A due to missing historical Indian source vintages.
- Four Phase 3A Python regression tests covering entitlement, units, provenance hash, idempotency, point-in-time access, scoped API authentication, missing data and FX classification; a desktop/mobile Playwright screen test; preserved prior tests.

## Validation

| Check | Result |
| --- | --- |
| Full Python suite | 52 passed, one upstream Starlette deprecation warning |
| Phase 3A Python tests | 4 passed, one upstream Starlette warning |
| TypeScript typecheck | Passed |
| Next.js production build | Passed; non-fatal existing Autoprefixer `end` support warning in Docker build |
| Isolated staging PostgreSQL migration | `0003 (head)`; no Phase 3A migration |
| Staging API/monitor smoke | `/api/v1/health` live/staging, `/api/v1/external-liquidity` returned `INSUFFICIENT_EVIDENCE`, FX score N/A; Caddy screen HTTP 200 |
| Staging historical audit | Zero eligible external indicators at all six fixed evaluation dates; no look-ahead substitutions |
| Playwright | 4 passed in isolated Playwright container, covering demo and staging at desktop/mobile sizes |

The host Playwright runner initially could not start Chromium because its browser revision was absent, then because the cached binary lacked host `libgbm.so.1`. The existing `mcr.microsoft.com/playwright:v1.56.0-noble` container completed the suite without host package changes. The source package API test used synthetic unit-test bytes only; no synthetic market values were imported into staging.

## Feed status

| Source | Actual status |
| --- | --- |
| U.S. Treasury 10Y | Existing Phase 2.5 official feed; one source-backed observation visible in isolated staging at validation time. |
| RBI USD/INR, gross reserves, India 10Y | Reviewed package parser only; **no verified observations imported**. Redistribution approval and release-time archive needed. |
| RBI net forwards | Unavailable for scoring/import until sign, maturity and definition review. |
| NSDL FPI equity/debt | Reviewed package parser only; **no verified observations imported**. Confirmed/provisional basis and redistribution permission needed. |
| AMFI SIP and fund flows | Reviewed package parser only; **no verified observations imported**. Written commercial-use agreement required. |
| Brent | Licensed package parser only; no contract, credential or observations. |

## Remaining risks and approvals

The release API relies on authenticated operators' attestation and an external permission/archive record; it verifies bytes against the submitted original SHA-256 but cannot independently verify legal rights or historical publication clocks. Original source bytes are not stored in the observation database. Historical calibration, forward-adjusted reserves, expectations-driven depreciation and alert accuracy remain unavailable. The existing v2 thresholds are provisional. Independent financial-methodology and security review are required before PR integration. PR #1 and PR #2 each require separate explicit merge approval; production deployment and migration require separate authorisation.
