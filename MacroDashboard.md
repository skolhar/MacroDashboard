India Macro Reflexivity Dashboard

Product Requirements Document + Technical Implementation Specification

Version: 1.0
Specification date: 2026-10-31
Audience: Codex / software engineers / product owner
Status: Implementation-ready specification; numeric triggers are proposed defaults, not empirically validated investment signals.

────────

0. Build instruction for Codex

Build a functioning, testable India-focused macro and equity-market monitoring web application that identifies transitions from stable trends to self-reinforcing stress using George Soros’s reflexivity framework. Implement the data contracts, calculations, scoring engine, rules, historical replay, UI, alerting and automated tests described here. Do not invent live market data or credentials. If a licensed feed is unavailable, use tagged demonstration fixtures and display DEMO clearly. Ship a working vertical slice before expanding to all indicators.

Do not infer a bullish/bearish investment recommendation from one signal. Expose uncertainties, sources, confidence, and missing inputs. This is market research and decision support, not an automated trade executor.

0.1 Definition of done

• Users can see the six cycle panels, overall risk score, inflection alerts, market regime, and source freshness on desktop and mobile.
• All indicator computations are reproducible at a chosen as_of timestamp (vintage-aware, no look-ahead).
• Operator can edit rules, thresholds and weights through versioned configuration; every score identifies the ruleset version used.
• Historical replay reproduces the information actually available at that time and differentiates publication dates from observation periods.
• System runs locally with Docker Compose, migrations, sample/demo dataset, unit tests and documented connector configuration.
• Incomplete/late sources produce visible stale or unavailable status and reduce score coverage rather than pretending values were updated.

────────

1. User need and decision questions

Primary user: Indian long-term investor who follows Nifty, mid/small caps, INR, macro liquidity and risk controls.
Secondary user: Research analyst maintaining economic indicators and event commentary.

The product must answer:

1. What macro/market regime is India in as of the latest available observations?
2. Which loops (FX, energy/rates, flows, valuations/earnings, IT exports, global yields) are reinforcing one another?
3. Is an observed equity decline merely a valuation reset, or is a flow-driven negative feedback loop developing?
4. What has changed over 1 day, 1 week, 1 month, 3 months and 12 months, with frequency-appropriate comparisons?
5. Which explicit combinations are near a trigger; what condition would invalidate the alert?
6. What indicators lack reliable data and therefore limit confidence?
7. How would a user-configured sustained-oil/high-yield/LTCG-disappointment scenario affect indicator stress and portfolio exposure qualitatively?

Non-goals for v1: order placement, personalized investment advice, real-money brokerage integration, individual stock picks, undocumented AI-generated daily signals, probabilistic crisis forecasts, inferred government intent, or proprietary datasets without permission.

────────

2. Architecture and recommended stack

Frontend: Next.js (App Router), React, TypeScript, Tailwind CSS, accessible components, ECharts or Recharts.
Backend: Python 3.12+, FastAPI, Pydantic v2, SQLAlchemy, Alembic.
Database: PostgreSQL 16 with TimescaleDB optional; store revisions/vintages explicitly.
Jobs: APScheduler for MVP; Celery + Redis in production if required.
Caching: Redis optional; response caching with time-to-live by metric frequency.
Testing: Pytest, Hypothesis where applicable, Playwright, TypeScript type checking.
Packaging: Docker Compose for local deployment; environment-driven secrets and connections.

Connector adapters -> raw source snapshots -> normalize/validate
                   -> vintage-aware observations -> feature engine
                   -> cycle scores + cross-loop rules -> event log
                   -> FastAPI REST endpoints -> Next.js dashboard
                                      \-> alert evaluation -> notifications

Keep provider adapters separate from canonical indicator IDs. Never make downstream calculations dependent on provider-specific field names. Provide an injectable Clock and immutable scoring configuration for deterministic tests.

2.1 Repository layout

apps/web/                  # Next.js UI
apps/api/                  # FastAPI entry point and routes
packages/domain/           # shared schemas, indicator registry
packages/scoring/          # deterministic scoring + alert engine
packages/connectors/       # provider adapters and parsers
packages/jobs/             # ingestion, recomputation, notifications
config/indicators.yaml     # registry + validation + sources
config/rules.v1.yaml       # thresholds, scores, composite rules
config/events.yaml         # known Budget/FOMC/RBI events, not forecasts
db/migrations/             # Alembic
fixtures/demo/             # watermarked demonstration histories
tests/                     # unit, integration, replay, UI tests
docs/                      # operator runbook and source licenses

────────

3. Interface and workflow

3.1 Desktop layout (single-screen summary)

[As-of | LIVE/DELAYED/DEMO | Source health | Ruleset | Scenario]
[Overall Reflexivity Risk: 0-100 | Regime | Score coverage | Δ 7d]
[FX Stress] [Oil/Rates] [Flows/SIP] [Earnings/Valuation] [IT/AI] [Global]
[Active Inflection Alerts: severity, direction, evidence, timestamp]
[Cycle interaction map: nodes + edges; click for rationale]
[Main time series: configurable overlays + event annotations]
[Watchlist: 12 priority metrics, last value, delta, stale badge]
[Scenario Lab | Historical Replay | Indicator Explorer | Methodology]

3.2 Mobile layout

Top summary, horizontally scrolling cycle tabs, prioritized alerts, one time-series chart per selected cycle; tables collapse to metric cards. No horizontal scrolling of the whole page. All alerts accessible without hover; adequate contrast and keyboard support.

3.3 Required features

• Filters: as_of, date range, market segment, frequency, data-quality threshold, and scoring ruleset.
• On each metric: latest reading, unit, comparison, trend, observation period, published_at, ingested_at, provider, status, revision history, explanation, methodology link.
• On each cycle: score, weight, coverage, rate of deterioration/improvement, top three contributing indicators, and linked alerts.
• Alerts: WATCH, WARNING, CRITICAL, RESOLVED; show start, last evaluation, triggers, contributing observations, counter-signals and confidence.
• Shareable deep links preserving filters (no secrets in query params).
• User can download indicator data and scores as CSV; report export optional.
• A source-health view displays last successful ingestion, typical publication lag, failed jobs and stale/unavailable fields.
• All hypothetical values are visibly labeled Scenario or Demo and never mixed into live scores.

────────

4. Canonical data model and time semantics

4.1 Core objects

IndicatorDefinition

{
  "id":"usd_inr_spot", "display_name":"USD/INR spot",
  "unit":"INR_per_USD", "frequency":"business_daily",
  "direction_of_stress":"up", "source_priority":["licensed_vendor","rbi"],
  "max_age_hours":48, "publication_lag_days":0,
  "transform":"raw", "required_for_score":true
}

Observation (unique by indicator, period, provider and vintage)

{
  "indicator_id":"usd_inr_spot", "period_start":"2026-10-30",
  "period_end":"2026-10-30", "value":"94.95", "unit":"INR_per_USD",
  "published_at":"2026-10-30T18:00:00+05:30",
  "ingested_at":"2026-10-30T18:10:00+05:30",
  "provider":"fixture", "source_url":null,
  "vintage_id":"demo-20261030-01", "quality":"demo",
  "is_revision":false
}

The numeric example above is DEMO ONLY, not a provider-verified spot quote.

FeatureValue: indicator ID, transform ID, window, value, observations used, computed_at, as_of, ruleset version, missing flag.

ScoreSnapshot: as_of, ruleset_version, per-cycle scores, normalized weights, effective coverage, total score (nullable), status, contributors, warnings.

AlertEvent: rule ID/version, status, severity, start/end, fired_at, confirmed_at, evidence IDs, observed vs required values, deduplication key, acknowledged_at.

PolicyEvent: event ID, date/time zone, type, description, primary source, status={scheduled,announced,verified,rumour}, affected indicators, surprise coding. For LTCG Budget: default scheduled; do not assume government promises a tax cut.

4.2 Non-negotiable time handling

• Store UTC timestamps and display Asia/Kolkata by default.
• Distinguish market observation date, source release date/time, import time, and revisions.
• A historical query as_of=t may use only data with published_at <= t and ingested_at <= t when replaying what this product actually knew; optionally provide a separate ‘source-known’ replay using publication time only. Label the mode.
• Monthly SIP / RBI forward / quarterly export series carry release lags and must not be forward filled as fresh.
• The recent monthly reading remains visible with monthly label, but do not imply that a daily dashboard score has a daily updated monthly value.
• Historical total returns, index membership, earnings consensus snapshots and corporate actions must be point-in-time adjusted or marked unsuitable for backtests.
• All timestamps and values retained across provider replacements; never silently overwrite observations.

4.3 Quality flags

verified, provisional, revised, estimated, stale, unavailable, demo, source_conflict. Exclude demo from production live scores; exclude unavailable and unverified policy rumors from numeric triggers. Missing is null, never zero.

────────

5. Data-provider strategy and indicator registry

Sources below are candidate acquisition routes, not guarantees of free real-time APIs. Validate terms, entitlements, release cadence and provenance before launch. Prefer direct official publisher downloads for released public data; use appropriately licensed market/consensus data for prices, holdings, flows, EPS and fund metrics. Implement file_import CSV for unavailable feeds.

|Cycle   |Indicator ID                         |Unit / frequency         |Suggested primary source               |Feature                 |
|--------|-------------------------------------|-------------------------|---------------------------------------|------------------------|
|FX      |`usd_inr_spot`                       |INR/USD, daily           |RBI reference rate / licensed vendor   |5d, 20d, 60d %, z-score |
|FX      |`fx_gross_reserves_usd`              |USD bn, weekly           |RBI Weekly Statistical Supplement      |4w/12w change           |
|FX      |`rbi_net_forward_usd`                |USD bn, monthly          |RBI forward outstanding reports        |liabilities trend       |
|FX      |`fcnr_deposits_usd`                  |USD bn, monthly          |RBI external deposit statistics        |YoY and MoM             |
|FX      |`fcnr_swap_facility_usd`             |USD bn, event/monthly    |RBI announcements, verified reports    |separate swap stock     |
|FX      |`current_account_pct_gdp`            |%, quarterly             |RBI BoP                                |rolling annual %        |
|FX      |`net_services_exports_usd`           |USD bn, monthly/quarterly|RBI BoP / trade data                   |growth, trend           |
|FX      |`oil_import_cost_proxy`              |USD bn, monthly          |PPAC imports + crude price             |price × volume, estimate|
|Energy  |`brent_usd`                          |USD/bbl, daily           |licensed ICE/EIA/FRED proxy            |20d/60d average         |
|Energy  |`india_crude_import_volume`          |mbpd, monthly            |PPAC / ministry                        |3m avg                  |
|Energy  |`india_cpi_yoy`                      |%, monthly               |MoSPI                                  |3m trend                |
|Energy  |`india_core_cpi_yoy`                 |%, monthly               |licensed/reproducible MoSPI calculation|3m trend                |
|Energy  |`india_repo_rate`                    |%, event                 |RBI                                    |latest decision         |
|Energy  |`india_10y_yield`                    |%, daily                 |CCIL/RBI/licensed                      |20d change (bps)        |
|Energy  |`india_10y_real_proxy`               |%, monthly/daily         |derived w/ inflation expectation source|optional, labeled proxy |
|Flows   |`fpi_equity_net_inr`                 |INR cr, daily            |NSDL/CDSL/depository validated route   |20d aggregate           |
|Flows   |`fpi_debt_net_inr`                   |INR cr, daily            |NSDL/CDSL                              |20d aggregate           |
|Flows   |`dii_equity_net_inr`                 |INR cr, daily            |NSE/BSE exchange stats                 |20d aggregate           |
|Flows   |`sip_contribution_inr`               |INR cr, monthly          |AMFI                                   |YoY + 3m momentum       |
|Flows   |`midcap_mf_net_inr`                  |INR cr, monthly          |AMFI category flows                    |3m average              |
|Flows   |`smallcap_mf_net_inr`                |INR cr, monthly          |AMFI category flows                    |3m average              |
|Flows   |`sip_discontinuation_ratio`          |%, monthly               |AMFI where published                   |trend; optional         |
|Flows   |`mf_cash_ratio`                      |%, monthly               |fund disclosures/aggregator licensed   |optional                |
|Earnings|`nifty50_fwd_pe`                     |multiple, daily/monthly  |licensed consensus/index vendor        |long-history percentile |
|Earnings|`midcap150_pe`                       |multiple, daily          |NSE index factsheets                   |premium to Nifty        |
|Earnings|`smallcap250_pe`                     |multiple, daily          |NSE index factsheets                   |premium to Nifty        |
|Earnings|`nifty_eps_revision_3m`              |%, monthly/daily         |licensed consensus dataset             |EPS revision            |
|Earnings|`sector_eps_revision_3m`             |%, sector/monthly        |licensed consensus                     |breadth                 |
|Earnings|`nifty50_price`                      |points, daily            |NSE/licensed index feed                |drawdown                |
|Earnings|`midcap150_price`                    |points, daily            |NSE/licensed                           |relative return         |
|Earnings|`smallcap250_price`                  |points, daily            |NSE/licensed                           |relative return         |
|Earnings|`market_breadth_pct_above_200dma`    |%, daily                 |licensed exchange constituents         |breadth                 |
|IT      |`india_software_services_exports_usd`|USD bn, annual           |RBI software services survey           |YoY growth              |
|IT      |`india_services_exports_usd`         |USD bn, monthly          |RBI / commerce data                    |quarterly trend         |
|IT      |`it_major_constant_currency_growth`  |%, quarterly             |company results, structured import     |weighted average        |
|IT      |`it_major_headcount_yoy`             |%, quarterly             |company results                        |employment proxy        |
|IT      |`it_major_operating_margin`          |%, quarterly             |company filings                        |YoY change              |
|IT      |`it_major_ai_revenue_share`          |%, quarterly             |disclosed if credible                  |optional, sparse        |
|IT      |`it_deal_tcv`                        |USD bn, quarterly        |company filings                        |backlog proxy, caveated |
|Global  |`us_10y_yield`                       |%, daily                 |U.S. Treasury / FRED                   |20d/60d change          |
|Global  |`dxy`                                |index, daily             |licensed index feed                    |20d momentum            |
|Global  |`us_high_yield_oas`                  |bps, daily               |FRED                                   |credit stress           |
|Global  |`vix`                                |index, daily             |CBOE/licensed                          |risk appetite           |
|Global  |`global_em_fund_flow`                |USD bn, weekly           |EPFR/licensed; optional                |EM-wide positioning     |

Policy overlay: verified RBI monetary announcements, Union Budget LTCG/STT changes, fiscal deficits, major energy trade agreements, tariff changes and material geopolitical disruptions. Policy headlines must not be turned into quantitative signals by unsourced sentiment inference. Add a manually reviewed policy_surprise_score only after published tax law or credible primary-source documentation, and allow a user-entered pre-event expectation to calculate a difference.

5.1 Initial priority set (MVP)

usd_inr_spot, brent_usd, india_10y_yield, us_10y_yield, dxy, fx_gross_reserves_usd, rbi_net_forward_usd, fpi_equity_net_inr, sip_contribution_inr, midcap150_pe, smallcap250_pe, nifty_eps_revision_3m.

If nifty_eps_revision_3m has no licensed source, use a validated manual-import fixture with a MANUAL label; do not substitute price momentum for earnings revisions.

5.2 Source governance

Every source adapter documents API/download URL or human-upload route, coverage, access requirements, legal redistribution restrictions, update cadence, field mapping, revisions and fallback policy. Never scrape paywalled data or present a proxy as the official series. Sources may be disabled without breaking the UI.

────────

6. Feature engineering

Use Decimal for financial amounts/rates at ingestion; floats acceptable for derived analytic features. Divide by zero yields missing, not zero. All features carry input IDs, sample size and effective as-of timestamp.

• change_pct(x, n) = 100 * (x_t / x_{t-n} - 1); for price/index positive only.
• change_bps(yield, n) = 100 * (yield_t - yield_{t-n}) when yields measured as percentage points.
• rolling_mean, rolling_sum, slope with explicit calendar vs trading periods.
• zscore(x, lookback) = (x - mean)/std; require 24+ observations and nonzero standard deviation.
• percentile_rank(x, lookback) calculated from historical values available by as_of; minimum 36 monthly or 252 daily historical samples.
• valuation_premium_mid = midcap150_pe/nifty50_fwd_pe - 1 only if both PE measures are comparable; preferably use aligned forward PEs. If one trailing and one forward, disable premium calculation and show a mismatch warning. Default to midcap150_trailing_pe / nifty50_trailing_pe - 1 with matching basis.
• valuation_premium_small similarly.
• equity_earnings_gap = trailing_3m_index_return - trailing_3m_eps_revision for interpretive chart only, not causal proof.
• net_domestic_absorption = 20d_DII_equity_net + 20d_FPI_equity_net in same INR unit.
• coverage = sum(weights of valid signals)/sum(all configured weights); do not normalize a low-coverage score to look fully certain.
• fx_forward_adjusted_liquidity_proxy = gross_reserves + signed_net_forward_usd only if definitions, signs, maturities and eligible components are documented. Otherwise show reserves and forward position separately without summing. Do not label this simple combination “usable reserves”.
• oil_bill_sensitivity_usd_bn = delta_oil_usd_per_bbl * crude_import_mbpd * 365 / 1000 (gross sensitivity, not CAD forecast).
• fpi_usd_returns = (1 + local_market_return) * (fx_start/fx_end) - 1 for USD/INR quoted INR per USD.
• Cohort-based SIP discontinuation rates and net investor adds are distinct; do not infer either from total SIP contributions.

Missing inputs must propagate and be explained.

────────

7. Risk scoring engine (deterministic, versioned)

7.1 Cycles and baseline weights

|Cycle                       |Weight in overall risk score|
|----------------------------|---------------------------:|
|FX/external liquidity       |25%                         |
|Oil/inflation/domestic rates|20%                         |
|FPI–DII–SIP liquidity       |20%                         |
|Earnings and valuation      |20%                         |
|India IT exports / AI       |10%                         |
|Global yields/dollar/risk   |5%                          |

All cycle risk scores are 0–100, higher = greater stress. Risk is not a return forecast. As an independent display, track direction={improving,stable,deteriorating}, computed from 4w change in score for daily-heavy cycles and a comparable frequency for quarterly cycles.

7.2 Thresholds: proposed initial calibration only

A signal’s normalized risk can be determined by a piecewise linear monotone function through {green_value,amber_value,red_value} mapping to scores {10,50,90}, capped at [0,100]. If high values are supportive, invert direction. For binary events, assign explicit bounded scores, not fake continuity. All thresholds live in YAML, are editable, and must be empirically calibrated on historical data before production alerts.

|Signal                                |Green baseline|Amber threshold     |Red threshold        |Notes                                           |
|--------------------------------------|--------------|--------------------|---------------------|------------------------------------------------|
|USD/INR 20 trading-day % move         |<=0%          |>=+2%               |>=+4%                |rising rate means INR depreciation              |
|Brent 60d average                     |<=$80/bbl     |>=$100              |>=$120               |dollar levels scenario dependent                |
|India 10Y 20d move                    |<=0 bps       |>=+25 bps           |>=+60 bps            |speed matters                                   |
|US 10Y 20d move                       |<=0 bps       |>=+25 bps           |>=+60 bps            |stress only when risk spreads/DXY also rise     |
|DXY 20d % rise                        |<=0%          |>=+2%               |>=+4%                |global USD strength                             |
|FPI 20d net equity flow               |>=0           |<=-₹15k cr          |<=-₹40k cr           |calibrate against market size                   |
|FX gross reserves 12w % change        |>=0%          |<=-3%               |<=-7%                |adjust for valuation effects                    |
|SIP 3m YoY growth                     |>=+12%        |<=+3%               |<=-5%                |not net fund flows                              |
|3m small-cap fund net flows           |positive      |near zero           |persistently negative|exact level empirically calibrated              |
|Nifty 3m EPS revision                 |>=+2%         |<=0%                |<=-5%                |vendor-dependent                                |
|Valuation premium (history percentile)|<=50th        |>=80th              |>=95th               |aligned P/E definitions                         |
|IT export YoY growth                  |>=+8%         |<=+3%               |<0%                  |low-frequency structural indicator              |
|RBI forward liabilities               |declining     |worsening 2 releases|worsening 3+ releases|contextual; cannot infer stress from stock alone|

If no sufficient history exists for percentile ranks or no compatible P/E basis, signal.status=unavailable. Signals with inadequate historical calibration must show provisional_threshold=true.

7.3 Cycle computation

For each cycle, define fixed within-cycle indicator weights in YAML and compute a weighted mean of available normalized signal risk, only if effective coverage >= 70%. Otherwise return cycle score=null, confidence=insufficient, while displaying partial available contributions. Apply 20% max score adjustment for confirmed same-cycle reinforcing conditions if configured, but cap at 100 and show the adjustment distinctly.

For overall score, require: (i) >=75% of total configured signal weight covered, (ii) at least four valid cycles, and (iii) FX, flows and earnings/valuation cycles present. Otherwise overall_score=null, not a falsely precise headline. Retain base cycle weights; do not silently reweight missing cycles for final score.

Regime labels (if overall score present): 0–25 Supportive, >25–45 Watchful, >45–65 Fragile, >65–80 High stress, >80–100 Reflexive stress. These labels are conceptual and subject to calibration; never claim they are validated crisis probabilities.

7.4 Inflection detection (more important than static score)

Each inflection rule defines: required signals, persistence window, score increase, severity, confidence, counter-signals, and resolution hysteresis. An inflection is an accelerating and reinforcing process, not merely a high value.

Illustrative rules:

FX_LOOP_WATCH: at least 3 of: USD/INR rises >=2% in 20 trading days; FPI net outflow over 20d <= -₹15k cr; Brent 60d avg >=$100; reserves 12w drop >=3%; forward liabilities worsening over 2 releases. Require two consecutive daily evaluations; report WATCH. CRITICAL only when at least four of these and currency price/official external buffer signals both contribute, with sustained 5 trading-day confirmation. No claim of FX crisis.

MID_SMALL_LIQUIDITY_SQUEEZE: aligned mid/small valuation premium >=80th percentile; 3m fund net-flow momentum deteriorating; relative mid/small performance < Nifty by >=5% over 60d; earnings revisions <=0. Require 3 of 4 for WATCH; 4 of 4 for WARNING. Add explicit SIP_RISK signal only if actual SIP discontinuation data exists.

EARNINGS_MULTIPLE_SQUEEZE: Nifty EPS 3m revision <= -3%; India 10Y +25bps or US10Y +25bps in 20d; Nifty forward P/E percentile >=65th or P/E compressing rapidly; FPI 20d net negative. Require 3 of 4 for WARNING; adding broad market breadth deterioration (<35% above 200DMA) can raise to CRITICAL after persistence confirmation.

STRUCTURAL_IT_EXPORT_RISK: two consecutive quarters of IT major constant-currency growth below 3%, declining IT margins or employment, plus lower YoY software export growth; WATCH only after >=2 quarters, avoiding daily noise.

BUDGET_POLICY_DISAPPOINTMENT: schedule event and capture user-entered/analyst-validated pre-event expectations; post-event rule only activates when verified Budget text exists and differs from documented expectation. Combine with 5d FPI and market reaction to assess post-event transmission; NEVER auto-assert disappointment from absent reform rumours alone.

GLOBAL_INR_SQUEEZE: US10Y 20d +25bps, DXY 20d +2%, FPI 20d negative, USD/INR 20d +2%; 3 of 4 WATCH, 4 of 4 WARNING after 2 consecutive trading days.

7.5 Alert lifecycle

• INACTIVE -> CANDIDATE -> CONFIRMED/WATCH/WARNING/CRITICAL -> COOLING -> RESOLVED.
• Persistence windows use market days for daily data and publication events for monthly/quarterly data.
• Use hysteresis: resolution only when rule falls below recovery threshold for 5 trading days (configurable), to prevent alert flicker.
• Deduplicate by {rule_id, ruleset_version, market, activation_window}.
• A trigger with missing required series becomes UNKNOWN, never FALSE.
• Show raw observed thresholds, ruleset version, observation timestamps and why a signal did not trigger.

────────

8. Interacting loops graph

Nodes: GLOBAL_YIELDS, DOLLAR, OIL, FX_STRESS, RBI_INTERVENTION, FPI_FLOWS, SIP_DII, VALUATION, EARNINGS, IT_EXPORTS, POLICY_EXPECTATIONS, CREDIT_CONDITIONS.

Directed signed hypotheses (not established causal estimates):

GLOBAL_YIELDS + -> FPI_OUTFLOWS + -> FX_STRESS + -> USD_RETURN_PENALTY + -> FPI_OUTFLOWS
OIL_PRICE + -> IMPORT_DOLLAR_DEMAND + -> FX_STRESS + -> IMPORTED_INFLATION + -> INDIA_YIELDS
INDIA_YIELDS + -> EQUITY_DISCOUNT_RATE + -> VALUATION_COMPRESSION
IT_AI_AUTOMATION + -> LEGACY_IT_PRICING_PRESSURE + -> SERVICES_EXPORT_RISK + -> FX_STRESS
SIP_DII_FLOWS + -> MID_SMALL_VALUATION + -> PAST_RETURNS + -> INVESTOR_CONFIDENCE + -> SIP_DII_FLOWS
POLICY_RELIEF_EXPECTATION + -> EQUITY_DEMAND; NEGATIVE_SURPRISE + -> FPI_SELLING
RBI_FX_SUPPLY - -> NEAR_TERM_FX_STRESS; SWAP_LIABILITIES + -> FUTURE_ROLLOVER_SENSITIVITY

Graph edges require hypothesis, expected sign, lag, confidence label, and notes. Do not depict causal proof from correlations. Edge highlighting requires both related signals active and a configured interaction rule; never imply econometric causality by automatic correlation alone.

────────

9. Historical replay, scenarios and backtesting

9.1 Historical replay

Date picker and stepping controls move as_of across historical observations. Every chart and alert uses data available by that timestamp. Visualize event timelines (Budget, RBI policy decisions, major oil and trade developments). Include a side-by-side mode: as then known vs latest revised data where legitimate.

9.2 Scenario lab (not live alert engine)

Inputs: Brent dollar change, US10Y bps change, India10Y bps change, DXY %, FPI net INR flow, SIP growth %, EPS revision %, software export growth %, RBI intervention assumption. Output: updated hypothetical scores under the configured transformations and simple oil-bill sensitivity. Show fixed assumptions and warn that model does not predict the USD/INR or Nifty level from these inputs.

Policy event selector: LTCG reform passes / partial / no reform / unknown; does not itself assert future government choices. Use analyst-configurable shock assumptions for FPI and valuations, and show a sensitivity table instead of a forecast.

9.3 Research/backtesting

Research module must report precision/recall on user-defined historical event labels, false-positive rate, alert lead time, and stability across calibration splits. Use chronological train/validation splits and walk-forward thresholds. Treat backtest metrics as unreliable if historical vintages, EPS histories or constituent-level point-in-time data are incomplete; show warning prominently.

────────

10. API contracts

Authentication is optional for a single-user local MVP but required for multi-tenant production admin writes. Use OpenAPI, typed payloads and standard errors.

GET /api/v1/health
GET /api/v1/sources/health
GET /api/v1/indicators?cycle=fx&status=verified
GET /api/v1/indicators/{indicator_id}/series?from=...&to=...&as_of=...&vintage_mode=system_known
GET /api/v1/dashboard?as_of=...&ruleset=v1
GET /api/v1/cycles/{cycle_id}?as_of=...&ruleset=v1
GET /api/v1/alerts?status=active&severity=warning
GET /api/v1/alerts/{alert_id}
GET /api/v1/graph?as_of=...
POST /api/v1/scenarios/evaluate
GET /api/v1/replay?as_of=...&vintage_mode=system_known
GET /api/v1/events?from=...&to=...
GET /api/v1/config/rulesets
POST /api/v1/admin/rulesets  # validated + authenticated
POST /api/v1/admin/imports/csv # validated + authenticated
POST /api/v1/admin/ingestion/run # authenticated, rate-limited

10.1 Dashboard response example

{
  "as_of":"2026-10-31T10:00:00+05:30",
  "mode":"demo",
  "ruleset_version":"v1",
  "overall":{"score":null,"regime":"insufficient_data","coverage":0.41},
  "cycles":[{"id":"fx","score":63.0,"coverage":0.85,"direction":"deteriorating","status":"provisional"}],
  "alerts":[{"id":"demo-alert-1","rule_id":"FX_LOOP_WATCH","status":"WATCH","demo":true,"triggered_at":"2026-10-30T18:00:00+05:30"}],
  "source_health":{"stale_count":3,"unavailable_count":2},
  "warnings":["Demo data; no live trading interpretation"]
}

10.2 API safety and integrity

Reject invalid dates, unsupported units, impossible negative values for positive-only price series, conflicting duplicate observations, unverified policy data used as facts, and unauthorized admin requests. Use request IDs, structured errors, pagination and rate limits. Do not reveal paid-data raw records when license forbids redistribution.

────────

11. Refresh schedules and reliability

• Market prices/yields/flows: daily after close (or intraday only if contracted). Use source-specific exchange holidays.
• FX reserves: weekly after RBI release.
• SIP/fund flows/CPI/FX forwards/FCNR: after monthly release.
• Current account / company fundamentals: quarterly/annual by release.
• Policy events: event-driven verified updates, analyst review.
• Recompute features and dependent alerts on ingestion of a new vintage or ruleset change.
• Each adapter must support retries with exponential backoff, ETags/checksums if feasible, idempotence and circuit breakers.
• Source freshness badges reflect expected release cadence, not a universal 24-hour TTL.
• Save immutable raw snapshot metadata and content hash; log ingestion errors and validate units/ranges.
• If a source is stale, make the dashboard degrade gracefully, maintaining readable last-known values with a prominent stale label.

────────

12. Alert delivery and user controls

In-app notification center in MVP. Email/Telegram/Slack may be optional later and require user-provided configuration. No unsolicited messages without opt-in.

Preferences: selected cycles, severity floor, quiet hours in Asia/Kolkata, digest frequency, cooldown, minimum data-quality, configured thresholds, acknowledgement state. Show why an alert fired and why it resolved. Batch duplicate events; avoid notifications for routine data revisions unless a material status change results.

────────

13. UI detail and visual design

• Professional financial-terminal aesthetic but readable; use restrained color and neutral backgrounds.
• Use consistent risk color semantics: green low stress, amber caution, red high stress; always accompany color with text/icon, never color alone.
• Top KPI shows score plus coverage (e.g. 62/100 · 92% coverage · provisional calibration). If missing, show N/A.
• Each chart supports observed vs scenario overlay, real series values vs normalized scores, zoom and tooltips with exact date/source.
• Charts for FX, oil and yields have clear separate axes or separate panels; avoid dual-axis comparisons without explicit labels.
• Chart annotations use verified events only and link to the supporting source.
• Panel footer: Latest observation, Last checked, Source, Methodology, Confidence.
• Accessible ARIA labels, keyboard navigation, reduced-motion support; screen widths 360px through 1920px.
• Ensure the first render works without any third-party credentials in DEMO MODE.

────────

14. Security, privacy, licensing and auditability

• Secrets only in environment or secrets manager; .env.example contains blanks/placeholders, .env gitignored.
• Minimal outbound networking; explicit allowed provider hosts; timeout and retry budgets.
• CSV upload validation: file type, schema, size, encoding, date formats, duplicates and malicious formulas on export.
• Production write endpoints require authentication, RBAC and audit trail.
• Verify vendor licenses before display or redistribution, especially for consensus EPS, index data, EOD exchange data and fund holdings.
• Every score snapshot stores indicator vintage references and rule versions to explain historical outputs.
• Display not-investment-advice note without interrupting ordinary use.

────────

15. Acceptance tests (must automate)

T01: Missing data. Removing a required FX series reduces coverage; no overall score if critical cycles unavailable. No zero imputation.

T02: No look-ahead. A quarterly IT export release published on May 30 must not influence an April 30 replay, even when the measurement period ended March 31.

T03: Revision handling. A revised RBI series produces a new vintage; system_known replay retains old vintage and current view reflects new one.

T04: Inverse FX return. INR Nifty +5%, USD/INR moves 90 to 99 => USD return = 1.05*(90/99)-1 = -4.545...%.

T05: Bond units. India 10Y yield 7.1% to 7.4% => +30 bps, not +0.3 bps or +300 bps.

T06: Oil sensitivity. +$10/bbl with 5.5 mbpd => $20.075bn gross annual cost change; never label it CAD or INR FX forecast.

T07: PE mismatch. Mid-cap trailing PE and Nifty forward PE do not produce valuation premium; display incomparable-basis warning.

T08: Trigger persistence. One-day FX threshold breach remains candidate; two qualifying evaluations create a watch alert; recovery hysteresis prevents flicker.

T09: Stale monthly SIP. After expected release date + grace window, SIP turns stale; no fake daily SIP value or fresh confidence.

T10: Demodata isolation. Demo observations cannot appear in production-scored dashboard, even when live source is missing.

T11: Score audit. Given fixture and ruleset, every cycle score, contributor and overall score match saved golden output.

T12: Config validation. Negative weights, weight sums not 100%, threshold inversions and contradictory rule IDs are rejected.

T13: Policy evidence. Rumor alone cannot classify February Budget as failed LTCG reform; verified text + stored prior expectation required.

T14: Mobile and accessibility. Dashboard works at 375px and 1440px; passes keyboard navigation and automated accessibility smoke checks.

T15: Ingestion idempotency. Re-importing same vendor file doesn’t duplicate observations or fire alerts twice.

T16: Market calendar. No false price staleness alert on weekend/holiday when next trading session has not occurred.

T17: Source failure. Vendor timeout leaves last-known observation visible and labeled stale/partial; backend does not return fabricated data.

T18: Scenario isolation. User changes to hypothetical Brent price modify only scenario result, not observed risk score or persisted market series.

T19: Source provenance. Clicking any number reveals provider, original observation date, published timestamp and whether estimated/provisional.

T20: Deployment. Fresh clone + docker compose up --build + migration/seed loads DEMO dashboard, API docs, and passing health endpoints.

────────

16. Implementation phases and milestones

Phase 1 — Vertical slice

• Monorepo scaffolding, DB migrations, indicator registry, sample data, provenance model.
• UI summary, six panels, 12 core metrics, chart, source-health panel.
• Deterministic base risk-score calculator and one working FX alert.
• Demo mode and tests T01–T06, T10, T20.

Phase 2 — Reliable market data and loops

• Production connectors for permitted official sources; manual CSV alternative for licensed metrics.
• Full six cycle scoring, cross-loop rules, alert lifecycle, graph and metric drilldowns.
• Tests T07–T09, T11, T12, T15–T17, T19.

Phase 3 — Replay and decision support

• Historical vintage replay, scenario lab, policy surprise overlay, benchmark performance, notifications.
• Tests T02, T03, T13, T14, T18 and research validation.

Phase 4 — Calibrate before investment use

• 5–10+ years of legally accessible history where available.
• Review thresholds with documented historical events, false-positive analysis, sensitivity and walk-forward checks.
• Freeze validated ruleset v2; retain experimental v1 with clear provisional indicator.

────────

17. Engineering handoff / exact first Codex task

> Implement **Phase 1** in this repository. Create the FastAPI/Next.js/PostgreSQL application, data registry, migrations and seed fixture, six-cycle overview, score coverage logic, versioned YAML rules, price and time-series charts, FX loop alert, source provenance tooltips and Playwright/Pytest tests. Use mock/demo data only where credentials are unavailable and label the entire page DEMO. Follow the endpoint contracts and schema definitions in this specification. Include README setup commands, `.env.example`, a migration command, and CI test commands. Do not invent source values or credentials. Do not proceed to proprietary data scraping. Explain any deviations in `docs/implementation-decisions.md`.

Operator configuration checklist

☐ Select official provider endpoint(s) and check license/redistribution requirements.
☐ Configure API credentials (if any) via secret store.
☐ Validate INR/USD quote convention and unit conversions.
☐ Confirm all market calendars and publication lags.
☐ Verify forward-position sign conventions before computing any net liquidity proxy.
☐ Align trailing and forward P/E periods before showing a premium.
☐ Configure portfolio-neutral informational thresholds as provisional.
☐ Validate historical data sufficiency before claiming signal calibration.
☐ Record an as-of snapshot and compare to source documents.
☐ Explicitly switch from DEMO to LIVE only when source health checks pass.

────────

18. Known implementation hazards / decisions to document

1. Price support is not the same as verified causality. SIP inflows and rich small-cap valuations can coexist without proving the former caused the latter.
2. SIP contributions are not net investment into small-cap equities. Track separate AMFI category flows and any cash buffer.
3. Gross reserves are not free dollar assets. Forwards, swaps, valuation and liquidity restrictions matter; avoid an unsupported ‘net usable reserves’ number.
4. Financial-account transactions differ from recurring export receipts. FCNR inflows cannot be counted as software-services exports.
5. LTCG policy discussion does not equal a promised reform. Pre-event expectations must be stored as opinions with source and timestamp.
6. AI’s effect on India IT is uncertain. Track gross versus net effects and pricing/margin data; avoid asserting inevitability.
7. Nifty earnings revisions generally require licensed consensus data. Use clearly labeled manual imports when unavailable.
8. High oil and global yields are scenario drivers, not guaranteed equity declines. Valuations can already price in stress.
9. Data frequency mismatch makes naive daily composite scores misleading. Show effective as-of and coverage clearly.
10. Thresholds in this document are starting hypotheses. They are not validated trading signals until appropriately backtested.

────────

Primary product principle: Make reflexive processes observable and falsifiable. The dashboard should show not only what is deteriorating, but what would have to change for a proposed feedback loop to break.