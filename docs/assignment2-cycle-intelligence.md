# Assignment 2: cycle intelligence

## Audit and boundary

The existing v2 monitor defines six fixed-weight stress baskets (`config/rules.v2.yaml`) and persistence-based multivariate alerts. It correctly distinguishes missing input, stale data and contradictory threshold evidence, but a stress score is not a causal model or a market forecast. The FX loop and flow reversal rules are closest to feedback hypotheses; single levels of oil, yields, inflation, valuations and prices are stress context until actors and response channels are independently evidenced. Existing verified releases, immutable vintages, demo isolation, market bars and API contracts remain unchanged.

`config/cycle_mechanisms.v1.yaml` now records the six economic hypotheses, actors, incentives, reinforcing and balancing mechanisms, leads and lags, policy responses, channels, alternatives and falsifiers. Every cycle has an explicit unresolved definition. A simple correlation or one-way price move is insufficient evidence of reflexivity. This catalog is independent of v2 score weights and makes no numerical influence claim. The open [policy PR #15](https://github.com/skolhar/MacroDashboard/pull/15) is documentation-only; this branch implements its discovery-first policy without editing its file or changing its PR.

## Private research evidence

Migration `research_1` follows `market_data_1` and adds separate `research_evidence` and `cycle_investigations` tables. Evidence contains a typed numeric value or qualitative finding, unit, period, source URL/name, server retrieval time, optional independently known publication time, quality, reliability caveat, permitted-use basis, hypothesis stance and operator identity. A unique observation key makes retries idempotent. A changed finding needs a new key and remains a distinct record. Exact source release bytes and two-person review are unnecessary for this private exploratory tier; governed release rules remain in force for official/public claims.

Only isolated development and staging permit research endpoints. The existing database operator system now supports `research:read` and `research:write`; production and demo reject private research access. Staging's optional `STAGING_RESEARCH_OPERATOR_TOKEN` should contain a **read-only** token and remains server-side in Next.js. Write actions require a separately entered write-scoped operator token. Keep staging loopback-bound or behind access control. Operator claims about permitted use must be verified by the operator; a free-text usage basis is not a legal entitlement check. Research evidence is never silently promoted to a verified macro observation or seeded as demo.

API:

- `GET /api/v1/research/catalog` publishes definitions only.
- `POST /api/v1/research/evidence` requires `research:write`; `GET /api/v1/research/overview` requires `research:read`.
- `POST /api/v1/research/investigations`, `GET /api/v1/research/investigations/{id}` and `PATCH` on the same path preserve an evidence snapshot and human status. There is no automatic catalog promotion.

Issue separate credentials with `python -m packages.jobs.operators issue <name> --scopes research:read` and `research:write` for an investigator. Research endpoints are also subject to existing rate limiting and audit events. The public Caddy production path is not configured to serve private research data.

## Inference rules

The evaluator reads only research records retrieved by `as_of`; records with known publication times after `as_of` or future observation periods are excluded. Unknown original publication time is disclosed and never used to claim strict historical availability. Repeated reports of the same claim/mechanism/period count once. Sources that disagree on the stance for the same claim are surfaced as conflicts and excluded from the state count. Distinct observation periods, not duplicate daily evaluations, establish persistence. IT uses a 400-day window to allow quarterly releases; the other cycles use 180 days.

Reinforcement support across two periods without a balancing signal means **mature/persistent**. New support is **emerging**; support returning after contradiction is **strengthening**. A prior reinforcing loop with contradictory reinforcement and an observed balancing force is **weakening**. Two distinct periods of each, after prior support, indicate **reversing**. Otherwise the result is **indeterminate**. These are provisional research classifications, not statistical confidence or proof of causation. Missing mechanism evidence never becomes contradiction. A candidate appears only when a weakening/reversing loop has a balancing force observed in at least two periods. It carries supporting and opposing observations, alternative explanations, confirmation requirements, economic channels and a falsifier. A single price fluctuation cannot create a candidate.

Market history is read through `packages.market.operations.history_at`, so a future Upstox adapter can replace Yahoo without changing the cycle engine. Stored vendor prices are reported as response/confirmation with retrieval timestamps; they do not create a macro stance. Outlooks are conditional by instrument and by 1–3 versus 3–6 month transmission timing. Influences are qualitative (`material`, `secondary`, `unresolved`); there are no invented percentages or directional probabilities. Brent/WTI futures are labelled global proxies, distinct from MCX crude; Yahoo FX is distinct from an RBI/FBIL reference fixing. “Already priced in” remains unknown until independent expectations evidence exists.

## Actual-source smoke and limits

On 1 November 2026 UTC, a read-only call to the official [U.S. Treasury XML feed](https://home.treasury.gov/resource-center/data-chart-center/interest-rates/pages/xml) returned 21 October dated 10-year par-yield observations. The last dated 30 October reported **4.94%**. `python -m scripts.research_treasury_example` placed that attributed fact in a temporary in-memory research table with publication time explicitly unknown, evaluated the global cycle and returned **indeterminate**. This is an actual source request and actual evaluator run, not a persistent staging import, public display entitlement, validated historical backtest or financial conclusion. All other test values are explicitly synthetic fixtures. No live Indian cycle can currently be asserted from the available isolated evidence.

Known limits: operator-entered causal stances need independent review; the state rules are not calibrated; conflicts are grouped only by claim/mechanism/period; one-cycle price change is descriptive and cannot establish whether expectations were priced in; no autonomous discovery or statistically validated influence exists. Detailed trend attribution, policy-event correlation, dated outcome tracking and human-reviewed new-cycle promotion belong to the next assignment.
