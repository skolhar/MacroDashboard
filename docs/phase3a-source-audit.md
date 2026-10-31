# Phase 3A source audit (31 October 2026)

## Controlled integration

PR #1 (`feature/phase2-reflexivity-engine`, `b9033e62deed309914fffd5e4ff189398640dd32`) and PR #2 (`feature/phase2-5-live-data`, `a11047f12666374d41bbbebc0425407f66ce094a`) remain open and mergeable. Their latest `phase1` checks succeeded at audit time. PR #2 is based on PR #1: their merge base equals the PR #1 head, and the PR #2 comparison contains six Phase 2.5 commits. The dependent Phase 3A branch starts at the PR #2 head. No merge or production action is authorised. Recheck review, CI and conflicts immediately before any separately approved merge.

The migration sequence is `0001_initial.py → 0002_pipeline.py → 0003_staging_security.py`; `0003` declares `down_revision = "0002"`. Phase 3A adds no migration. Existing Phase 1 routes remain unchanged; `/api/v1/external-liquidity` and `/api/v1/admin/imports/release` are additive.

## Access and entitlement findings

| Indicator | Official publication | Technical access | Public redistribution / automated ingestion decision |
| --- | --- | --- | --- |
| USD/INR reference rate | [RBI DBIE](https://statistics.rbi.org.in/) | Downloadable RBI statistical series; exact approved machine endpoint not established | Reviewed release package only, after written/open redistribution grant. RBI reference fixing is not a tradable spot quote. |
| Gross FX reserves | [RBI Weekly Statistical Supplement](https://wss.rbi.org.in/) | Weekly releases and historical DBIE series | Reviewed package only. FCA valuation effects must not be described as intervention without evidence. |
| RBI net forward USD | [RBI statistics](https://statistics.rbi.org.in/) | Monthly reserve template/forward maturity reporting requires exact series mapping | **Blocked from scoring and Phase 3A package import** until assets minus liabilities, maturity buckets, gross/net scope and release vintage are independently checked. |
| India 10Y G-Sec | [RBI DBIE](https://statistics.rbi.org.in/) | Historical government-securities series reported by RBI | Reviewed package only; choose and document benchmark versus specific-security yield. Unit is percent, changes are basis points. |
| FPI equity/debt | [NSDL latest report](https://pilot.fpi.nsdl.co.in/Reports/Latest.aspx) | Web report and archive; no approved automated API established | Reviewed package only with redistribution permission. Provisional exchange trades and confirmed custodian records cannot be mixed as one series. |
| SIP and mid/small-cap fund flows | [AMFI](https://www.amfiindia.com/), [terms](https://www.amfiindia.com/terms-of-use) | Monthly publications | AMFI terms grant personal non-commercial use and require written agreement for other uses; **no public ingestion without written permission**. |
| Brent | Licensed commodity provider | No credential or provider contract supplied | DATA_UNAVAILABLE. A licensed package can be imported only when distribution and historical-use rights are documented. |

The RBI [DBIE FAQ](https://dbieold.rbi.org.in/DBIE/doc/Frequently%20Asked%20Questions%20-%20DBIE.pdf) says data may be downloaded without login; downloadability is not a redistribution licence. The [DBIE brochure](https://dbieold.rbi.org.in/DBIE/doc/Brochure%20on%20DBIE%20-2022%20English.pdf) describes available forex and government-security series. No credentials, feed rights or Indian observations were supplied in this repository. No Indian series was auto-fetched, scraped, backfilled or presented as connected.

## Reviewed release connector

`packages/connectors/india_release.py` supports operator-supplied RBI, NSDL, AMFI and licensed Brent extracts. `POST /api/v1/admin/imports/release` requires an operator with `imports:write`, original publisher bytes, reviewed normalized CSV, publisher URL, publication evidence URL, actual timezone-aware publication timestamp, original SHA-256, definition version, vintage, and `written-permission` or `open-license` redistribution basis. The endpoint verifies the uploaded original hash and records it on each observation. The operator remains responsible for keeping the permission record and original release. The parser accepts only approved indicator/unit/provider combinations and excludes RBI forward positions. It does not interpret a public URL as permission.

Extract columns: `indicator_id,value,unit,period_start,period_end,vintage_id,quality`. Request fields: `provider`, `source_reference`, `publication_evidence_url`, `published_at`, `source_sha256`, `redistribution_basis`, `definition_version`, `original_source_base64`, `extract_csv_base64`. Maximum is 750 KB each for original and extract, subject to the existing 1 MB total request limit. The definition version is prefixed to the stored vintage ID. Verified release time must be proved independently; if absent, do not import a historical release with an invented earlier timestamp. Existing manual import remains available under its own controls. Import, rejection, publication evidence URL, rights basis, vintage and source hash are auditable; the raw source bytes themselves are not retained in the database, so keep them in a governed source archive.

## Precise access needed next

1. RBI permission or licence for public display and historical reuse; select stable official download/API series and document release clocks.
2. NSDL permission for daily FPI equity and debt redistribution, plus a confirmed/provisional series definition and archive access.
3. AMFI written agreement for SIP/category-flow reuse and category-definition history.
4. Brent provider contract, API credential, display and historical/backfill rights.
5. For forward positions, independently validated RBI template, signs and maturities before any scoring proposal.
