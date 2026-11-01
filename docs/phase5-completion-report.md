# Phase 5 completion report

## Delivered

- Strict source-specific RBI WSS HTML and text-layer PDF gross-reserves parser with USD-million component reconciliation, explicit 3 USD million tolerance, reference-week validation and fail-closed format handling.
- Deterministic operator extract command, approved-release cross-check, immutable component table (migration `0005`) and idempotent vintage/revision handling. The existing two-operator entitlement and publication-evidence review remains mandatory.
- Configurable, bounded original-file archive (4 MB default, 8 MB ceiling), atomic concurrent writes, no-symlink reads, integrity checks and backup/retention runbook.
- External Liquidity Monitor gross reserves, components, reference week, publication time, previous-week change, quality, reviewer provenance and expected-Friday gap count. Existing FX and composite coverage gates remain in force.
- Synthetic regression fixtures for parsing, mismatch rejection, concurrent archival, corruption, duplicate/revised ingestion and point-in-time replay.

## Source coverage

**Actual approved RBI observations imported: 0. Synthetic records used in isolated tests: 2 distinct vintages plus duplicate retries.** No real RBI publisher bytes or financial values were added to the repository or staging. Original releases, independently documented exact publication times and a rights instrument for archive/processing/public display remain outstanding. The official WSS portal presented a CAPTCHA during the audit; no access control was bypassed. No automated real-source scheduling is enabled until those gates are met.

## Validation and status (1 November 2026 IST)

- Python: **64 passed**, one existing FastAPI/Starlette deprecation warning.
- TypeScript: `npm run typecheck` passed. Next.js production build passed with an existing CSS Autoprefixer warning.
- Playwright: **5 passed** in the cached Playwright browser image, covering demo and isolated staging at desktop/mobile widths.
- Migration: fresh isolated SQLite and `0004 → 0005` isolated SQLite both reached `0005 (head)`; backed-up isolated staging PostgreSQL migrated to and reported `0005 (head)`.
- Isolated staging: rebuilt API/web healthy; health reports `mode=live`, `environment=staging`; External Liquidity reports `INSUFFICIENT_EVIDENCE`, FX score N/A and `rbi_reserves=null`. SQL count of approved, non-demo RBI reserves observations: **0**. The PDF extraction binary is present in the staging API image. No synthetic RBI numeric observation was inserted into staging.
- Read-only staging gap report: RBI reserves source-known **0**, system-known **0**, unreviewed vintages **0**, 106 missing month buckets and 461 expected Friday anchors from 2018-01-01; Friday counts are candidates pending holiday/reference-week review.
- Import regression: synthetic original HTML and text-layer PDF fixtures, total/component and week mismatch rejection, archive >750 KB, eight concurrent identical uploads, corruption rejection, approved two-operator review linkage, idempotent retries, distinct revised vintages, source-known/system-known replay, and monitor coverage gate passed.

Phase 5 is an executable, governed import path for supported WSS originals; actual data activation remains gated on source rights, authentic files and exact publication evidence. The parser has not yet been tested against an authentic RBI original, so a publisher-layout change may require a reviewed adapter update. No production deployment, database migration, secret change or production infrastructure change occurred.
