# Phase 3B completion report

## Integration and production status

Branch `feature/phase3b-india-data-backfill` starts from PR #3 head `a73858d0fd3dd9df992d58943c0b67a552e96c37`. A later GitHub status check found PR #1 merged, PR #2 closed **without** merge, and PR #3 still open against the Phase 2.5 branch. This work did not merge or close any PR. Phase 3B remains dependent on PR #3 and must target its Phase 3A branch; PR #3's own integration path still requires independent review of the closed PR #2 dependency. No production deployment, secret, infrastructure or database was touched. No migration was added; the branch's chain remains `0001 → 0002 → 0003 → 0004`.

## Delivered

- A content-addressed, staging-only original-release volume and scoped archive upload/download endpoints. The existing two-operator review now verifies that the original bytes remain in the archive at submission, approval and import. SHA-256 establishes retained byte identity only; authenticity, publication time and rights remain independent human decisions.
- Source-definition gates for RBI's 9 July 2018 to FBIL's 10 July 2018 USD/INR reference-rate handover. FBIL observations are explicitly published reference fixings. Monthly RBI 10-year yields cannot enter a daily yield indicator. RBI gross reserves require a weekly WSS definition. NSDL confirmed custody and provisional exchange basis must be labelled separately; monthly cumulative FPI rows cannot enter daily flow IDs.
- A read-only, point-in-time historical gap report from 2018 onward, showing separate source-known/system-known coverage, missing months, reviewed vintages and only calendar-verified missing daily dates. The External Liquidity Monitor now exposes quality, vintage and approved review ID when present. Missing cross-signals remain `UNKNOWN`; the FX score and composite remain N/A with inadequate coverage.
- Synthetic unit-test fixtures exercise archiving, tampering, source definitions, duplicate imports, late backfills, revisions, missing periods and point-in-time separation. Fixtures are confined to test databases. No synthetic financial values were imported to staging.

## Validated source coverage and gaps

The isolated staging gap audit found **zero** source-known and **zero** system-known observations for all ten audited Indian/Brent indicators: USD/INR, gross reserves, RBI forwards, India 10Y, FPI equity/debt, AMFI SIP, AMFI mid/small fund flows and Brent. Missing months begin January 2018. Exact historical daily gaps for 2018–2025 cannot be certified because their India trading calendars have not been independently reviewed. Forward position is context only and its import/scoring remains disabled. The staging monitor reports Indian inputs as `DATA_UNAVAILABLE`, external-liquidity cycle score N/A and `INSUFFICIENT_EVIDENCE`. It continues to show the previously connected official U.S. Treasury 10Y observation, which is outside the Indian coverage audit.

No Indian release was imported: no original historical release files, independently documented publication timestamps, and no specific storage/display/redistribution entitlements were provided. RBI/FBIL, NSDL, AMFI and Brent each require the rights and source evidence listed in `docs/phase3b-source-entitlements.md`. This is an intentionally incomplete source-backed dataset, not a five-year backfill. Historical calibration, alert lead-time claims and live Indian FX assessments are not possible yet.

## Validation

| Check | Result |
| --- | --- |
| Python suite | 59 passed, one existing upstream Starlette deprecation warning |
| Phase 3A/3B provenance regressions | 11 passed |
| TypeScript typecheck | Passed |
| Next.js production build | Passed; existing non-fatal Autoprefixer `end` warning |
| Playwright desktop/mobile demo and staging | 5 passed in isolated browser container |
| Isolated staging PostgreSQL | `0004 (head)`; migration history `0001 → 0002 → 0003 → 0004` |
| Staging API/Caddy | Health `staging/live`, external-liquidity N/A/`INSUFFICIENT_EVIDENCE`, page HTTP 200 |
| Staging gap audit | Ten selected indicators have zero Indian/Brent observations; unverified calendar years 2018–2025 listed explicitly |

## Remaining limitations and review items

The 750 KB archive cap may be too small for some publisher datasets and must be raised only after storage/processing review. Archive volume retention, backup and operator access control are deployment obligations. Human review is not replaced by hashes or URL allowlists. No scheduled Indian connector is activated. The legacy `usd_inr_spot` API identifier remains for compatibility, but RBI/FBIL values are reference rates, not continuous tradable prices; the 20-session change and FX thresholds remain provisional. The 2018–2025 India calendars and publisher-specific revision inventories must be reviewed before historical signal calibration. Phase 3B remains dependent on PR #3 and its Phase 2.5 ancestry, and requires independent technical, security and financial-methodology review.
