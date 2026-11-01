# Assignment 3: persistent anomaly discovery

This private research layer extends the merged cycle-intelligence architecture. It does not change the public Inflection Monitor, approved-release workflow, Yahoo provider interface, or six-cycle catalog. `discovery_1` follows `research_2` and adds immutable discovery snapshots plus human-opened provisional hypotheses. Apply it only to an isolated development or staging database until separately approved.

## Observation to investigation

1. Numeric private research facts, approved non-demo macro observations and Yahoo/other provider-neutral market bars retain their original ID, source, revision, observation period, and retrieval time. Synthetic regression fixtures are excluded from normal discovery reads. Qualitative research remains available to the existing cycle-intelligence process but does not enter a numeric anomaly calculation.
2. `config/discovery.v1.yaml` defines provisional minimum baseline (six periods), persistence (three distinct periods), robust median deviation, structural-break comparison, and frequency-aware freshness and gap limits. A single extreme value is labelled `ISOLATED`. Missing consecutive releases, conflicting publisher values or stale inputs block a current persistent claim. Direction, momentum and acceleration are descriptive, not forecasts. The robust rule can misclassify noisy or seasonal series; it is not calibrated financial significance.
3. Cross-indicator candidates require persistent anomalies in *both* configured economically related series, aligned dates and a matching directional pattern. The pair configuration is an editable research question independent of the six established cycles. A price pair or generic statistical correlation never creates a causal claim. The current example questions are FPI/DII offsets, FX/reserves divergence, and a bank-liquidity/credit disconnect outside the existing cycle catalog. They are not live findings. The relationship list is extensible; unconfigured relationships will not be auto-promoted.
4. Each provisional candidate carries the raw supporting observation IDs and revisions, actors/incentives, conditional reinforcing and balancing mechanisms, alternative causes, confirmation and falsification requirements, and separate unresolved 1–3 and 3–6 month implications. A `research:write` operator freezes a snapshot and opens an investigation. The hypothesis remains separate from the established cycle catalog; `research:read` can inspect it. Operator actions are audited. There is no automatic promotion.

## Historical semantics and reproducibility

`GET /api/v1/research/discovery?as_of=<timezone-aware timestamp>&knowledge_mode=system_known|source_known` is private. System-known excludes observations retrieved/ingested after the date. Source-known is explicitly **retrospective reconstruction**: it may include a record first ingested later only when an independently documented publication timestamp proves source availability by the date. When publication time is unknown, retrieval is the conservative availability bound. Future-dated data and demo macro observations are excluded. Source revisions published later cannot enter an earlier reconstruction. A frozen snapshot stores the complete rules, exact result and input IDs/revisions; `GET /api/v1/research/discovery/snapshots/{id}` replays it unchanged after later revisions or rule edits. Recomputing an old episode with current rules is labelled accordingly and does not pretend to be a previously published live assessment.

Private API endpoints:

| Method and path | Scope | Purpose |
| --- | --- | --- |
| `GET /api/v1/research/discovery` | `research:read` | Current or dated analysis and coverage gaps |
| `POST /api/v1/research/discovery/snapshots` | `research:write` | Freeze dated rules, inputs and result |
| `GET /api/v1/research/discovery/snapshots/{id}` | `research:read` | Replay frozen result |
| `POST /api/v1/research/discovery/hypotheses` | `research:write` | Open provisional investigation from a frozen candidate |
| `GET /api/v1/research/discovery/hypotheses/{id}` | `research:read` | Inspect evidence and competing explanations |
| `PATCH /api/v1/research/discovery/hypotheses/{id}` | `research:write` | Track open, investigating, rejected, archived |

`/intelligence/discovery` inherits the existing Basic-auth private research middleware. The read token remains server-side; a write-scoped operator token is required to open an investigation. Discovery remains disabled by the API in demo and production environments. Do not provide source access tokens or private research material to public browsers.

## Actual-source smoke and limitations

Run `PYTHONPATH=. python scripts/discovery_treasury_smoke.py` for an optional read-only, in-memory request to official U.S. Treasury XML. On 2026-11-01 it retrieved **21 actual October 2026 daily 10-year par-yield records**, latest 2026-10-30 at **4.94%**, and returned `NO_PATTERN` and zero mechanism candidates. The source XML gives observation dates; original publication timestamps and vintages were not independently verified, so the smoke uses retrieval time and makes no historical availability or public redistribution claim. No observations were imported into production or a shared database. Economic values in automated tests are explicitly synthetic.

The engine does not adjust for seasonality, reporting-definition changes, policy announcement timing, or the effect of revisions on later economic decisions. Cross-indicator questions are configured, not exhaustively discovered from every possible pair. A statistical break cannot demonstrate an actor response, and a retrospective hypothesis cannot establish predictive performance. Additional assignments should obtain rights-cleared multi-sector Indian observations, verify source-specific publication schedules, compare candidates to independently documented actor responses, and review false positives before any public claim.
