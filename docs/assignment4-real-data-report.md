# Assignment 4 actual-source research demonstration

Run on **1 November 2026 UTC** using `PYTHONPATH=. python scripts/indian_research_demo.py`. The script makes actual read-only requests to [World Bank WDI source 2](https://api.worldbank.org/v2/country/IND/indicator/FS.AST.PRVT.GD.ZS?format=json&source=2) and [GEM source 15](https://api.worldbank.org/v2/country/IND/indicator/CPTOTNSXN?format=json&source=15), imports into an in-memory private research database, transforms the values, evaluates three historical episodes, prints JSON and discards the database. Original publication timestamps are not available from those API responses. Results are `retrospective_current_vintage`, not historically published SmartHedge assessments. No synthetic value appears in this run.

| Area | Actual retrieved coverage | Latest observed period in the run |
| --- | --- | --- |
| WDI banking/activity | 100 non-null observations across 4 annual series, 2000–2025; broad money ends 2021 | Private credit/GDP, GDP growth and consumption growth: 2025; broad money/GDP: 2021 |
| GEM inflation/activity/external | 721 non-null observations across 7 monthly series, January 2018 onward | Monthly-average FX: August 2026; CPI, reserves, imports, exports and import cover: July 2026; IIP: June 2026 |

The WDI and GEM importers recorded 100 and 721 inserts respectively. A separate isolated retry of the earlier WDI subset inserted **zero** and recognized every identical value as a duplicate; synthetic regression tests cover revised values for the same period. At the 1 November 2026 cutoff, **4 of 11** configured indicators were usable, **7 stale** by their cadence windows, and **zero cross-indicator questions** had two currently usable inputs. Missing or stale data was not treated as stability.

## Pattern assessment

| Retrospective episode | Economic transformation and actual finding | Decision |
| --- | --- | --- |
| May 2021 | YoY GEM exports, imports and IIP show large consecutive deviations from the earlier 24-month transformed baseline. Their 2020 reference levels had fallen sharply. | `BASE_EFFECT_REVIEW`; the trade/production rebound is held as a plausible reopening/base effect. It does not create a reflexivity hypothesis. |
| June 2025 | GEM CPI index YoY change for June 2025 is **2.3054%** in the retrieved vintage. Three monthly inflation observations meet the provisional below-baseline persistence rule. | Persistent **low inflation** research signal, not evidence of a macro feedback loop. Requires official CPI definitions, contemporaneous publication data and activity/credit response. |
| July 2026 | GEM merchandise exports YoY growth for July 2026 is **33.1105%** in the retrieved vintage. Three monthly values meet the above-baseline persistence rule. | Persistent export-growth research signal. Its composition, price effects and revisions need review; no valuation or currency conclusion follows. |

Configured relationships checked FX/reserves, inflation/IIP, imports/exports and the older FPI/DII and bank-liquidity/credit questions. **No current or sampled retrospective pair passed both persistence and alignment conditions. Zero provisional cross-indicator hypotheses were emitted.** This is an explicit insufficient-evidence result for the requested chain after the persistent-anomaly stage. The candidate templates remain research questions and cannot be promoted automatically. A later assignment needs actual FPI, domestic-flow, bank-credit and policy observations to test economic actors and feedback.

Competing explanations for the observed single-series patterns include base effects, source-definition changes, merchandise-price composition, annual/monthly aggregation, policy shifts and later revisions. Confirmation requires dated independent releases and evidence that actors changed behavior in response; falsification includes reversal of the observed pattern or a source-definition/valuation explanation accounting for it. These are conditions for investigation, not market predictions. The indicator-specific thresholds are provisional and were **not** optimized to force a candidate from the observed history.

World Bank metadata dates are dataset updates, not original publication dates for each period. GEM total-reserves units are left `source_units_unverified`; its percentage transformation is dimensionless, but gross-versus-net reserve definitions still need independent validation. The GEM exchange rate is a **monthly average**, not a continuous tradeable spot rate or FBIL fixing. WDI bank credit is a percent-of-GDP ratio, not RBI fortnightly bank-credit growth. Private research use does not alter public approved-release entitlement gates.

## Validation boundary

The live WDI/GEM requests and private research UI were exercised only with disposable local databases. The read-scoped browser smoke rendered the 11-indicator coverage panel on desktop and mobile; the existing public and demo pages were tested separately against an isolated synthetic database. Automated provider and anomaly tests use explicitly synthetic fixtures. SQLite and disposable PostgreSQL migrations reached the existing `discovery_1` head; no new schema migration is needed. This run did not ingest into a shared staging or production database and did not establish an actual economic feedback mechanism.
