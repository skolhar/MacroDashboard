# Phase 3A completion report

## Branch and integration state

Development branch: `feature/phase3a-india-macro-data`, based on PR #2 head `a11047f12666374d41bbbebc0425407f66ce094a`. PRs #1, #2 and #3 remain open. PR #2's merge base exactly equals PR #1's head; PR #3's base exactly equals PR #2's head. Read-only merge-tree checks for PR #1 onto `main` and PR #2 onto PR #1 exited successfully. The full migration chain is `0001 → 0002 → 0003 → 0004`; `0004` is an additive Phase 3A review migration. No merge, production deployment, production secret change or production migration was performed.

## Delivered

- Two-operator source-release review for RBI, NSDL, AMFI and licensed Brent packages. Submission stores publisher-byte and extract hashes, original archive reference, separate publication evidence and explanatory note, entitlement document reference, definition version and submitter identity. A distinct scoped reviewer records approval only after explicitly attesting evidence and entitlement checks. Import must match the approved review and links observations to its durable record. A matching SHA-256 proves byte identity with submitted bytes only; it does **not** prove publisher authenticity, release timing or legal rights. The older CSV endpoint rejects these reviewed-release indicator IDs. RBI forwards remain blocked. These are reusable import controls, **not live feed connections**.
- Additive `/api/v1/external-liquidity` endpoint and `/external-liquidity` monitor with existing v2 cycle score and data confidence, cross-signal evidence classifications, source freshness, source-backed historical levels, alert evidence, and explicit demo/staging labels. FX depreciation alone never establishes a feedback-loop watch.
- [Isolated staging screen](screenshots/phase3a-external-liquidity-staging.png) captured with no Indian observations, showing DATA_UNAVAILABLE rather than fabricated charts.
- Read-only `scripts.phase3a_coverage` audit over the requested historical windows using system-known observations. The preliminary answer is N/A due to missing historical Indian source vintages.
- Five Phase 3A Python regressions covering independent approval, entitlement, units, original hash, idempotency, point-in-time access, CSV bypass, missing/counter evidence, conflicting definitions and stale data; a desktop/mobile Playwright screen test; preserved prior tests.

## Validation

| Check | Result |
| --- | --- |
| Full Python suite | **53 passed**, one upstream Starlette deprecation warning |
| Phase 3A Python tests | **5 passed**, one upstream Starlette warning |
| TypeScript typecheck | Passed |
| Next.js production build | Passed; non-fatal existing Autoprefixer `end` support warning in Docker build |
| Fresh SQLite migration | `0001→0004` passed. Initial SQLite foreign-key ALTER failed and was repaired with Alembic batch mode. |
| Isolated staging PostgreSQL migration | Existing `0003→0004` upgrade passed; `0004 (head)` confirmed. |
| Staging API/monitor smoke | `/api/v1/health` live/staging, `/api/v1/external-liquidity` returned `INSUFFICIENT_EVIDENCE`, FX score N/A and one existing U.S. Treasury source-backed indicator; Caddy screen HTTP 200. No synthetic data imported. |
| Staging historical audit | Zero eligible external indicators at all six fixed evaluation dates; no look-ahead substitutions |
| Playwright | 4 passed in isolated Playwright container, covering demo and staging at desktop/mobile sizes |

The host Playwright runner initially could not start Chromium because its browser revision was absent, then because the cached binary lacked host `libgbm.so.1`. The existing `mcr.microsoft.com/playwright:v1.56.0-noble` container completed the suite without host package changes. Source package and signal tests use synthetic unit-test bytes/values in private test databases only; no synthetic market values were imported into staging.

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

The release workflow requires identifiable, separate submitter and reviewer operators, but an organisation must still govern identity issuance and independently inspect publisher authenticity, publication evidence and permissions. Original source bytes are not stored in the observation database; the governed archive reference must remain accessible. RBI reference-rate observations are labelled as published fixings in v2, with a 20-session change that fails closed on missing sessions or a provider switch. Existing 2%/4% bands and the 2% alert threshold are provisional on that basis and were not historically calibrated. Historical calibration, forward-adjusted reserves, expectations-driven depreciation and alert accuracy remain unavailable. PR #1 and PR #2 each require separate explicit merge approval; production deployment and migration require separate authorisation.
