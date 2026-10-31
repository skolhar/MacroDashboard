# Experimental v2 scoring and inflection methodology

> Phase 2.5 adds a separate data-confidence score, continuity checks for live transformed histories, and immutable alert evaluation events. See `phase2-5-implementation.md`. The provisional v2 risk thresholds and fixed cycle weights remain unchanged.

`config/rules.v2.yaml` is an immutable, provisional research ruleset. Its thresholds are hypotheses, not validated crash probabilities. `v1` remains available for Phase 1 compatibility. No numeric score is an investment recommendation.

## Inputs and provenance

Every calculation uses the latest eligible vintage for each observation period with `published_at <= as_of` and, in `system_known` mode, `ingested_at <= as_of`. `source_known` omits the ingestion bound and is labeled separately. Live scoring accepts only non-demo `verified` or `revised` observations. Provisional, estimated, stale, conflicting and missing readings remain visible but cannot contribute to a numeric score. A historical v2 replay is marked experimental because the ruleset has not yet been activated in production.

## Features and scores

- `change_pct(x,n) = 100 × (x_t/x_{t-n} − 1)`; `change_bps(y,n) = 100 × (y_t − y_{t-n})` for yields stored as percentage points.
- Rolling means/sums require all `n` observations. P/E percentile requires at least 252 available daily observations. SIP three-month YoY requires 15 monthly readings. A missing denominator or short history yields null.
- A valid feature maps piecewise linearly from green→10, amber→50, red→90, capped at 0–100. Downward-stress signals invert the axis. All thresholds and within-cycle weights are in YAML.
- Each cycle uses `Σ(observed signal risk × signal weight) / Σ(observed signal weight)` only if its own weight coverage is at least 70%. Missing signals are excluded from both numerator and denominator, never imputed as zero. Its `confirmation` counts available signals with risk at or above 50.
- `momentum` is the current cycle score minus its score 28 calendar days earlier; `acceleration` is current minus twice the 28-day score plus the 56-day score. Both are null if any comparison score is missing. The IT cycle should move to publication-event comparisons after sufficient quarterly vintages accumulate; the current calendar comparison is a provisional display.
- Overall coverage is `Σ(cycle weight × cycle signal coverage) / 100`. The composite is `Σ(cycle score × configured cycle weight) / 100` only when all six cycles are valid, configured weights sum to 100, and coverage is at least 75%. A missing cycle makes the composite N/A; its weight is never silently treated as zero or redistributed. Regime labels follow the v1 ranges and are conceptual.

The FX cycle shows reserves, FPI and forward commitments separately. RBI forward position is deliberately excluded from numeric v2 scoring until sign conventions, instrument maturities and eligible components are documented. Reserves plus forwards are **not** a net usable reserves estimate. P/E percentile signals are separate series; no trailing/forward P/E premium is calculated. SIP contributions are not equated with small-cap net flows.

## Six reflexive inflection rules

Rules test cross-domain combinations, not isolated high values: rupee/external liquidity; mid/small liquidity; broad de-rating; oil and inflation; global AI/credit; India IT exports. Each rule lists observed value, threshold, operator, source period, publication time, counter-signals, confidence and an invalidation condition. At least three of four conditions must be known. Two conditions over two daily evaluations create WATCH; three over three create TRIGGERED; four over five create CONFIRMED. Five consecutive nonqualifying evaluations resolve an active alert. Unknown inputs never count as false or as recovery. The India IT rule evaluates on new publication events instead of daily repeats.

The IT rule uses distinct quarterly reporting-period releases: two releases for WATCH, three for TRIGGERED, four for CONFIRMED, and two nonqualifying releases for recovery. Revised vintages for one quarter and repeated daily dashboard evaluations do not advance persistence. The system stores changed alert states with the exact `v2` rule version and evidence. Dashboard and replay GET requests recompute without writing history. Imports and approved ingestion runs can record transitions. Re-importing identical data cannot create duplicate observations or transitions.

## Limitations requiring independent review

Rules are not trained or validated against event labels. Calendar coverage includes verified U.S. exchange and federal proxy dates through 2027; NSE 2027 remains explicitly unverified until its annual circular is published and reviewed. See `calendar-maintenance.md`. Cohort SIP cancellations, AI pricing pressure and capex guidance are sparse; absent inputs lower coverage. Alert co-occurrence does not establish causality. No current v2 reading should be described as a crisis forecast.
