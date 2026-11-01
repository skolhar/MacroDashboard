# Assignment 5 actual-source actor-response investigation

Run on **1 November 2026 UTC** with `PYTHONPATH=. python scripts/actor_response_demo.py`. This script made actual read-only API requests to the [RBI Innovation Hub DBIE mirror](https://dev.dbie.rbihub.in/docs/using-the-site), imported into **disposable in-memory SQLite**, and evaluated current-vintage retrospective episodes. No synthetic observation entered this run. The mirror is secondary and experimental; original RBI publication times, vintage histories and public redistribution rights remain unverified.

| Mirrored RBI table | Actual non-null records since 2018 | Latest period retrieved | Definition |
| --- | ---: | --- | --- |
| [Scheduled commercial bank aggregates](https://data-api.dbie.rbihub.in/api/tables/financial_sector/r901_scheduled_commercial_banks_select_aggregates) | 532 across credit and deposits | 15 October 2026 | Fortnightly ₹ crore outstanding stocks; July 2023 merger and December 2025 reporting change matter |
| [Liquidity operations](https://data-api.dbie.rbihub.in/api/tables/financial_markets/r702_liquidity_operations_by_rbi) | 3,010 | 25 October 2026 | Daily signed ₹ crore net injection (+) / absorption (−), not an identified policy motive |
| [Weekly gross reserves](https://data-api.dbie.rbihub.in/api/tables/external_sector/r1_foreign_exchange_reserves_weekly) | 460 | 23 October 2026 | US$ millions; valuation effects prevent an intervention inference |

The 4,002 actual records are **successfully fetched and imported only into the disposable research run**. They are not verified original RBI publisher vintages and were not imported into shared staging or production. A repeated identical import is skipped in automated tests; changed values create distinct immutable research revisions. Original release publication dates are null, so a 2025 episode evaluated with these rows is **retrospective current-vintage research**, not what SmartHedge knew in 2025.

## Historical questions

| Episode end | Observed sequence | Decision |
| --- | --- | --- |
| 31 December 2022 | Available bank data do not establish the configured transition from two nonpositive funding-gap reports to two positive reports. | `INSUFFICIENT_EVIDENCE`; a positive gap by itself cannot identify a new actor response. |
| 30 June 2025 | Credit YoY growth exceeded deposit YoY growth by **1.329 percentage points** on 27 December 2024 and **0.616 points** on 10 January 2025. Five later reported RBI operation days (20 January–2 February) summed to **−137,716 ₹ crore-days**, net absorption. The next bank reports on 7 and 21 February still showed positive gaps of **0.699** and **0.660 points**. | `CONTRADICTORY_EVIDENCE` for the proposed RBI *injection* response; the bank gap did not close in the two configured follow-ups. This does not establish why RBI absorbed liquidity. |
| 31 October 2026 | The last qualifying onset is the older 2024–25 episode. Recent raw bank levels exist, but YoY comparisons cross the December 2025 fortnight-definition change. | `HISTORICAL_ONLY`; no current feedback-loop candidate is emitted. |

The 2025 assessment is supported by 29 distinct source-observation IDs/revisions across current and prior-year bank levels, five RBI operation days and two follow-up bank reports. The economic interpretation remains weaker than the factual sequence: RBI operations could reflect government cash balances, seasonal liquidity, policy implementation or unrelated factors. No borrower-demand or bank funding-cost response was independently observed. There is no confirmed reinforcing loop or present-day inflection signal.

The specific hypotheses to investigate next are whether bank funding costs changed after credit/deposit divergence, whether RBI publications attributed operations to that funding pressure, and whether independent borrower-demand releases show a lending response. The proposed mechanism would weaken if the bank gap closed before any relevant RBI action, if operation motives were unrelated, or if credit growth failed to respond. No directional market forecast or numerical cycle weight follows from this investigation.

With only the mirror rows in the disposable run, the private coverage endpoint listed **15 configured indicators** (the prior 11 plus four mirror series); two current transforms were usable, while bank-credit and deposit YoY transforms were stale because they cannot cross the documented 2025 definition break. The original 11 WDI/GEM observations were not fetched in this particular script. FPI, DII, mutual-fund and SIP actor behavior remains unavailable in this run. See [methodology](assignment5-actor-response.md) for source and persistence rules.
