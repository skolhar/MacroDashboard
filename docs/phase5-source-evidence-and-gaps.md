# Phase 5 RBI reserves evidence and historical gaps

## Source status

Candidate source: RBI Weekly Statistical Supplement (WSS) gross foreign-exchange reserves, official portal <https://wss.rbi.org.in/>. The WSS portal presented a CAPTCHA during this audit; the implementation does not bypass it. An RBI-published reserves table uses paired INR-crore and US-dollar-million columns and reports total reserves, foreign currency assets, gold, SDRs and the IMF reserve position. The connector requires an original publisher HTML or text-layer PDF with an explicit reference week and these five first-column USD-million values. It rejects changed or ambiguous layouts.

No original RBI WSS release, independently verified publication timestamp, or instrument granting SmartHedge archive, processing and public numeric-display rights was available for this phase. **Actual RBI observations imported: 0.** All test numbers and file bytes are synthetic. SHA-256 links stored bytes to reviewed bytes; it does not establish RBI authorship, historical publication time, or redistribution rights.

## Required evidence for each release

1. Untouched original file and official source URL. Record how authenticity was independently checked.
2. Separate official release notice or other independently checked publication evidence and the exact timestamp with timezone. A date-only page cannot be turned into an invented time.
3. Written permission or an applicable open licence covering the specific archive, extraction, analysis and display uses, including retention and expiry. Record the instrument reference.
4. WSS definition version, reference week, units, gross-versus-net basis, and whether this file is an original or revised vintage.
5. Two different named operators: submitter and approver. Approval must precede import.

The parser uses an explicit **3 USD million** tolerance between the reported gross total and the sum of four components. This allows rounding of five separately published USD-million cells; a larger discrepancy is rejected, never silently adjusted. The USD-million original is stored with its components; `fx_gross_reserves_usd` is normalized to USD billions for the existing scoring contract. Gross reserve movement alone cannot establish RBI intervention because valuation and other flows also change the stock.

## Historical coverage

The read-only `python -m scripts.phase3b_gap_report` lists source-known and system-known coverage, vintages, unreviewed periods, missing months and expected Friday reference-week anchors from 2018 onward. A missing Friday is an **audit candidate**, not proof RBI failed to publish: holidays or alternate reference dates require review against originals. Historical backfills retain real ingestion timestamps, so they never appear in system-known history before import. A source-known replay still requires proven historical publication timestamps and original vintages. No complete 2018-present RBI archive has been acquired, and no historical RBI coverage claim is made.

Isolated staging report at **2026-11-01 00:00 IST**: source-known RBI reserves periods **0**, system-known **0**, reviewed vintages **0**. There are **106 missing month buckets** and **461 expected Friday anchors** from the report's 2018-01-01 start. These are unfilled audit slots, not assertions about actual WSS publication schedules. The generated machine-readable report was retained locally outside the repository at `/tmp/smarthedge-phase5-staging-gaps.json` for staging review.

## Remaining blocker

Obtain the rights instrument, authentic original files, and independently verifiable publication timestamps. The reviewer must establish the first-column definition and any revisions from the original WSS file. Text-layer PDF/HTML are supported; image-only PDFs require a separately reviewed extraction method and must fail closed meanwhile.
