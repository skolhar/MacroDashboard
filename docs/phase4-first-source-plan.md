# Phase 4 plan: first approved Indian source-backed dataset

## Starting point

PR #6 was merged into `main` at `4fa451eba798ad8a62392d7db7f9bc8e9413ed02`. The merged tree contains Phase 2, 2.5, 3A, 3B and 3C, and Alembic head is `0004`. Local merged-main validation: 59 Python tests, TypeScript typecheck, Next.js production build and 5 Playwright tests passed. The GitHub post-merge CI run passed. No GitHub deployment record was created; the production health endpoint still reports the Phase 1 demo configuration. No production database or credential was changed.

The first candidate is **RBI weekly gross FX reserves**, conditional on the evidence and rights in [the acquisition audit](phase4-acquisition-audit.md). It has an official weekly release channel and a clear gross-stock meaning. This is a prioritisation for acquisition, **not permission to ingest**. If another provider supplies an approvable package first, apply the same gates to that dataset instead.

## Gate 1 — secure and review the source package

1. Obtain an RBI permission instrument or applicable licence that explicitly covers SmartHedge's original-file retention, extraction, commercial analysis and public numeric display. Record restrictions and expiry. For FBIL, NSDL and AMFI, obtain their respective source-specific agreements before using their feeds.
2. Obtain at least one untouched original WSS release and independent evidence of its exact publication timestamp. Enumerate historical originals and revisions from 2018 onward; a current revised table does not prove a historical vintage. If exact publication time cannot be established for a release, exclude it from point-in-time replay and do not fabricate a timestamp to satisfy the schema.
3. Have one scoped operator submit the archive bytes and extract, and a different scoped reviewer attest publisher authenticity, source definition, publication evidence and rights. Keep credentials outside the repository. Confirm original file size is within the archive limit or amend the limit with storage tests and review.

**Exit criterion:** a durable approved review links rights, original publisher bytes, publication evidence, definition version and both operator identities. No public numeric value is enabled before this gate.

## Gate 2 — implement one validated extraction path

1. Extend the existing reviewed-release connector for the approved original format only. Extract WSS gross total and component values as reported, with USD units and reference-week end date. Preserve publication and ingestion times separately, original URL, content hash, vintage and revision markers. Do not infer RBI intervention from a change in gross reserves, which can include valuation effects.
2. Reject missing or ambiguous release dates, unknown units, inconsistent components, duplicate conflicting payloads and outliers pending review. Keep the original file immutable. Make retries idempotent and make a changed vintage explicit.
3. Add parser fixtures made from legally retained originals in a restricted test area where rights permit, plus synthetic unit-test fixtures in the repository. No publisher data is committed without permission. Test late backfills, corrections, source-known versus system-known replay, missing weeks, malformed files, archive tampering and source failure.

**Exit criterion:** the same approved original produces the same observation and provenance on repeated staging runs; future revisions remain separate vintages.

## Gate 3 — isolated staging and interpretation

1. Import only approved releases into isolated staging. Run the historical gap report before and after import and retain its JSON. Reconcile a sample of values to the original WSS files and release notices with a second reviewer.
2. Confirm the External Liquidity Monitor shows the source, quality, vintage, publication time and approval reference. Missing FPI, FX and oil inputs remain `UNKNOWN`; the FX cycle and composite stay N/A below configured coverage. Gross reserves alone must not trigger an FX reflexivity alert.
3. Check point-in-time replay at dates before release, after publication but before SmartHedge ingestion, and after ingestion. Document any missing original vintages; do not claim predictive historical validation while coverage is insufficient.
4. Run Python, typecheck, Next.js build, Playwright, fresh and upgrade migration tests, ingestion duplicate/revision tests and an isolated staging smoke test. Prepare a feature PR targeting `main`, with exact source rights and validated observations listed separately from connector functionality.

**Exit criterion:** an independently reviewed, source-backed staging observation and reproducible tests. Public live-data deployment, production migrations and credential changes remain separate approval gates.

## Scope held pending evidence

The existing RBI/FBIL FX, NSDL and AMFI manual import gates remain available for reviewed packages. Do not activate their feeds from public pages or silently substitute another series. The daily India 10-year benchmark publisher/definition and RBI forward-position signs require financial-methodology review. Historical India trading calendars for 2018–2025 also require verification before daily session-based scoring. No market-direction prediction or crash probability will be inferred from a single newly connected series.
