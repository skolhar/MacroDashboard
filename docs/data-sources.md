# Phase 2 data sources and entitlements

No production data is shipped in this branch. `DATA_UNAVAILABLE` is the correct live status until an approved source is imported. The synthetic Phase 1 fixture remains confined to `APP_ENV=demo`.

| Priority | Indicators | Acquisition path | Status and operator requirement |
|---|---|---|---|
| 0 | US 10-year yield | [U.S. Treasury daily XML par-yield feed](https://home.treasury.gov/treasury-daily-interest-rate-xml-feed) | Adapter implemented. Requires an approved run and successful feed smoke check; the validation host timed out. Historical release time is conservatively set to first ingestion because the feed does not provide a verified original publication timestamp for each historical row. |
| 0 | USD/INR, India 10Y, Nifty 50, Midcap 150 and Smallcap 250 P/E, Brent, DXY | RBI/NSE official publications or licensed market vendor | `DATA_UNAVAILABLE`. No public API or redistribution entitlement is assumed. Use reviewed CSV imports only after terms are checked. |
| 0 | FPI equity/debt flows | Applicable official depository publications | `DATA_UNAVAILABLE`; field units, release timing and redistribution terms need validation. |
| 1 | RBI reserves, forward dollar position, FCNR(B), current account, net services exports | [RBI Database on Indian Economy](https://data.rbi.org.in/) / official releases | `DATA_UNAVAILABLE`; manual import path exists. RBI forward stock remains contextual until sign, maturity and definition are documented. |
| 1 | SIP contributions, registrations, discontinuations, category fund flows | [AMFI public statistics](https://www.amfiindia.com/mutual-fund) | `DATA_UNAVAILABLE`; manual import path exists. SIP contributions do not imply net small-cap investment. |
| 1 | CPI, repo | MoSPI and RBI official releases | `DATA_UNAVAILABLE`; manual import path exists. |
| 2 | Software exports | RBI survey | `DATA_UNAVAILABLE`; annual releases must retain publication time. |
| 2 | TCS, Infosys, HCLTech, Wipro and Tech Mahindra USD revenue, employment, margins and AI disclosures | Company filings and investor presentations | `DATA_UNAVAILABLE`; a documented, comparable analyst aggregation is required before a weighted series can be marked verified. |
| 2 | Nasdaq 100, U.S. IG/HY spreads | Licensed index and credit data | `DATA_UNAVAILABLE`; no license configured. |
| 2 | Hyperscaler capex guidance | Primary company filings | `DATA_UNAVAILABLE`; manual review and fixed company universe required. |

The registry separates canonical IDs from source adapters. `UnavailableAdapter` explicitly raises `DataUnavailable`; it never fills gaps with sample values. `TreasuryAdapter` allows only the hardcoded official Treasury host, a 10-second timeout, no redirects, and a 5 MB response cap. Connector execution requires an admin token. Provider failures leave stored observations untouched and create a failed ingestion run.

## Reviewed CSV route

`POST /api/v1/admin/imports/csv` accepts `text/csv` bytes, an `X-Admin-Token`, `X-Source-Provider`, and `X-License-Attestation: public-redistributable`. It is disabled in demo mode. Columns must exactly be:

```text
indicator_id,value,unit,period_start,period_end,published_at,vintage_id,source_reference,quality
```

Dates use ISO `YYYY-MM-DD`; publication timestamps require an offset; source references require an HTTPS URL; value is a Decimal; quality must be `verified`, `revised`, `provisional`, `estimated`, or `source_conflict`. The operator must verify that the reference actually supports the value and that public display is permitted. This endpoint is deliberately not a way to import proprietary consensus data for public redistribution.

Import validation rejects unknown IDs, mismatched units, nonpositive prices/index levels, future publication timestamps, duplicate-vintage conflicts, formula-like text, invalid UTF-8, malformed rows and files over 1 MB. A greater than 50% jump in a positive-only series is retained as `source_conflict` and excluded from live scores pending review. Re-importing identical observations is idempotent. Raw snapshot hash and ingestion runs are retained.

## Calendars

The [NSE 2026 trading holidays](https://www.nseindia.com/resources/exchange-communication-holidays) and [U.S. 2026 federal holiday schedule](https://www.opm.gov/policy-data-oversight/pay-leave/federal-holidays/) are recorded in `config/calendars.yaml`. The U.S. list is a provisional Treasury publication-calendar proxy, not an exchange-specific Nasdaq calendar. Unknown years return `CALENDAR_UNVERIFIED` instead of asserting freshness. The 2026 NSE special Sunday sessions are included; the operator must update the file from primary releases each year.

## Pending before a public live launch

- Obtain and record licenses for commodity, index, valuation, flow, credit and consensus series.
- Verify U.S. Treasury XML parsing against a successful response in the deployment environment; only a local representative XML parser test has passed so far.
- Validate official publication timestamps, revision policy and redistribution rights for each imported series.
- Review forward position sign conventions and company-level aggregation methodology.
- Calibrate thresholds on point-in-time histories before interpreting v2 as an investment signal.
