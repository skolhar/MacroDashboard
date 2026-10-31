# External Liquidity Monitor methodology

The new screen uses the unchanged v2 six-cycle scoring architecture. The displayed FX cycle score and coverage are computed by the existing engine. Forward positions, FPI debt, yields, Brent and domestic fund flows are contextual on this screen; their appearance does not silently change FX weights. Thresholds remain provisional. A 0–100 score is a risk index, not a probability or trading recommendation. The Data Confidence Score is an operational coverage/quality index, not statistical certainty.

The evidence classification uses eligible, fresh `scored_feature` values only. `NULL` means unknown, never a negative signal or recovery. The provisional conditions are USD/INR 20-session depreciation ≥2%, FPI equity 20-session net flow ≤−₹15,000 crore, gross reserve 12-observation change ≤−3%, and Brent 60-session average ≥$100/bbl. Each is read from the existing v2 rule context; the classification is separate from alert-state persistence.

| Classification | Required evidence | Interpretation |
| --- | --- | --- |
| `INSUFFICIENT_EVIDENCE` | FX momentum unknown | No assessment. |
| `NO_CONFIRMED_FX_PRESSURE` | FX threshold not met | Other signals remain contextual. |
| `AWAITING_FOREIGN_FLOW_EVIDENCE` | FX threshold met, FPI unknown | No financing conclusion; missing is never counted as counter-evidence. |
| `DEPRECIATION_WITH_COUNTER_FLOW_EVIDENCE` | FX threshold met, observed FPI flow does not meet selling threshold | Observed counter-evidence; managed adjustment remains possible. |
| `FINANCING_PRESSURE_AWAITING_LIQUIDITY_EVIDENCE` | FX and FPI selling met, reserve or oil evidence missing | Coincident financing pressure with unresolved liquidity confirmation. |
| `FINANCING_PRESSURE_WITH_COUNTER_LIQUIDITY_EVIDENCE` | FX and FPI selling met, both reserve and oil conditions observed and unmet | Explicit counter-evidence to the provisional liquidity-loop condition. |
| `REINFORCING_STRESS_WATCH` | FX, FPI selling, and reserve decline **or** elevated oil met | Provisional cross-signal watch; coincidence is not causality. |

Investor expectations and RBI intervention motives cannot be inferred from these observations alone; the UI marks expectations evidence unavailable. Gross reserves include valuation effects and are not netted against forward positions. A forward-adjusted reserve scenario requires validated asset/liability signs, reporting maturities, gross-versus-net scope and valuation treatment. Until then the forward metric is context only and excluded from imports through the Phase 3A package parser.

The `usd_inr_spot` identifier is retained for Phase 1 compatibility. When its provider is RBI, the v2 API and UI label it **USD/INR published RBI reference rate**, with `rate_kind=published_reference_rate`. It is not a continuous executable spot quote. The v2 `change_pct_20` transform compares published values 20 verified Indian business sessions apart. A missing session, stale fixing, or switch between RBI and another provider makes the feature unavailable. The existing 2%/4% risk bands and 2% alert condition are **provisional on this published-reference series**, not calibrated trading thresholds; no threshold was retuned using historical outcomes.

The alert panel shows the existing `RUPEE_STRESS` lifecycle, including supporting and counter evidence, plus invalidation conditions. The narrative classification never creates or confirms an alert and never invents a score. Charts show only eligible verified/revised observations in live/staging, or explicitly labelled synthetic observations in demo. The source timestamp and provider are available on each plotted point.
