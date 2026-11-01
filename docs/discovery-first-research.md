# Discovery-first private research policy

**Governing scope:** [Issue #9](https://github.com/skolhar/MacroDashboard/issues/9), 2026-11-01 authoritative decision. SmartHedge's core deliverable is discovering and interpreting macro-reflexivity cycles and inflection points, **not** building an exhaustive official-data archive.

## Separate evidence tiers

| Tier | What it is for | Entry criteria | What it cannot claim |
| --- | --- | --- | --- |
| **Research / exploratory** | Generate and revise falsifiable cycle hypotheses; surface evidence conflicts and candidate turning points in isolated personal research | Permission for intended access/use, intelligible source/metric/unit/observation period, retrieval date, publication date if known, caveats and source quality | Exact point-in-time historical knowledge, verified official release, permission for public redistribution, calibrated causal probability |
| **Verified / governed** | Published verified indicators, rigorous publication-vintage replay, authorized reuse/display | Existing source archive, entitlement/review, exact release/vintage checks where required | Cannot be silently inferred from a Yahoo quote or unreviewed secondary estimate |
| **Demo** | Tests and demonstrations only | Labelled synthetic data | Real economic observations or investable outlook |

Research evidence and verified official observations must remain isolated in storage and APIs. Avoid adding a burdensome second copy of the governed ingestion pipeline. Preserve authorization, safety, and provenance controls; do not change the rules for verified/public workflows. Where source terms do not permit a proposed use, do not ingest that source in that manner and find an authorized alternative.

**Minimal useful research evidence:** observation value, units and measurement definition, observation period, source and URL/reference, first retrieval/known-at timestamp, publication timestamp if available (otherwise explicitly unknown), revision/estimate status, reliability note. Preserve a timestamped research snapshot when creating a new hypothesis, inflection assessment, or investigation.

**No mandatory prerequisites for a present-day private exploratory hypothesis:** exact historical release clock, original publisher byte archive, two-operator review, publication-grade licence attestation, coverage of all configured indicators, long complete economic series. Missing evidence reduces confidence and affects which claims are permissible; it should not prevent tentative causal research.

**Historical honesty:** A reconstructed historical value with unknown release time cannot be treated as historically known at that time. Keep retrospective evaluation separate from strict point-in-time replay. Do not call correlations causation.

## Cycle and inflection workflow

1. **Mechanism:** record actors, incentives, reinforcing/balancing loops, policy response, economic channels, expected leads/lags, alternatives and falsifiers.
2. **Observe:** collect timely research evidence, including imperfect data where lawful; triangulate across independent series. Treat contradictory evidence distinctly from missing inputs.
3. **Evaluate state:** emerging, strengthening, mature, weakening, reversing, indeterminate. Mark where turning-point evidence is weak or mixed.
4. **Synthesize for instruments and horizon:** Nifty, global crude proxy versus MCX contract, USD/INR and relevant ETF exposures separately at 1–3 and 3–6 months. Explain direction, dominant supported cycles, overlapping channels, what may already be priced in, invalidation tests and data limitations. No fictional numerical importance weights or directional signal solely from price momentum.
5. **Discover anomalies:** screen for persistent material deviations; show baseline, duration, alternative hypotheses, corroborating/contradicting evidence. Price is one verification channel, not the sole trigger.
6. **Collaborate:** user explicitly starts investigation, reviews evidence and competing explanations, then accepts/rejects/monitors a new proposed cycle. No automatic cycle promotion.
7. **Learn:** track dated predictions, signals, and outcomes; revise models prospectively, do not rewrite historical hypotheses to match observed returns.

## Engineering priority

- Prefer a lean, reusable research-evidence adapter and editable mechanism catalog over new enterprise data-governance infrastructure.
- Reuse the existing six cycles, market-data adapter, status panels, alerts and vintage-aware storage where possible.
- Keep the attention-first interface sparse: consequential cycle changes, inflection candidates, conditional Nifty/crude/USDINR outlooks and exceptional ETF alerts.
- yfinance is the initial research market source; Upstox may be promoted later behind the same interface after coverage and rights checks.
- Do not implement broker connectivity, orders, options or intraday execution features.
- Never enable Yahoo research data on a public production deployment without confirming use/redistribution rights.

## Acceptance test

For each supported cycle, can a researcher see **what feedback loop may be operating, why its strength may have changed, what could falsify it, and the conditional impact on a relevant instrument**? Can they pursue a persistent anomaly collaboratively without manufacturing certainty? Improvements in data completeness count only insofar as they increase these capabilities.
