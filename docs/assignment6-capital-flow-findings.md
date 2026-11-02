# Assignment 6 — Capital Flow Reflexivity and Institutional Behavior

## Scope and system boundary

This assignment adds a private, evidence-first capital-flow investigation to the
dashboard. It observes attributable FPI, DII and mutual-fund flow observations
and checks whether domestic institutional purchases offset foreign selling,
whether absorption persists or weakens, and whether household SIP contributions
change with equity returns. It does **not** claim feedback loops, absorption
capacity or future allocation behaviour from flows data alone.

## Implemented components

- **Connector** (`packages/connectors/india_capital_flows.py`): parses exchange/AMFI flow tables into attributable observations. Renamed or reordered reporting columns raise immediately so definition changes are never silently absorbed. Missing daily values are skipped (never zero-filled); gross rows are never summed with net rows.
- **Scoring engine** (`packages/scoring/capital_flow_reflexivity.py`): descriptive offset over matched FPI/DII reporting sessions (unmatched sessions excluded, never zero-filled), persistence split into an on-date detection and a retrospective follow-up assessment, monthly SIP-vs-return co-movement with a fixed lag and a growth-vs-level control, and a spurious-association check that compounds forward returns over complete calendar months and infers no behavioural order from reporting timestamps.
- **Config** (`config/capital_flow.v1.yaml`): versioned thresholds and explicit falsification criteria.
- **API endpoint** (`/api/v1/capital-flows`): private, `research_reader`-authenticated snapshot selecting observations point-in-time via the shared `observations_at` helper (`vintage_mode` selectable; rows dated after the as-of time or ingested after the knowledge cutoff are excluded and reported, never silently selected as if originally known). Returns an explicit unavailable state when no attributable observations are stored; never fabricates flows.
- **Dashboard view** (`apps/web/app/intelligence/capital-flows`): evidence-first page showing offset state, persistence verdict, SIP response, point-in-time exclusions, data freshness, observed-versus-hypothesised separation and limitations, with an explicit `data_unavailable` state when no attributable observations exist.

## Investigation states

- `dii_offset_fpi_selling`: opposite-sign net flows over exactly matched reporting sessions, co-occurrence only; unmatched sessions and gross-turnover rows are counted as exclusions, not absorbed into the signal. The offset amount is the smaller opposing magnitude — `min(dii_net, abs(fpi_net))` — because DII buying beyond the FPI selling magnitude offsets nothing that was sold; the gross opposing magnitude is reported separately, and any remaining unoffset FPI selling or excess DII buying is reported explicitly. The minimum offset threshold gates this matched amount, not the gross magnitude.
- `persistence_sustained` / `persistence_weakening` / `persistence_dissipated`: detection (DII daily average over the sessions observable on the detection date) and follow-up (retrospective comparison using evidence available only afterwards) are reported as separate semantics; follow-up rows ingested after the evaluation as-of time are excluded, so the retrospective assessment is never presented as a signal known on the original date.
- `sip_rising_after_recent_returns` / `sip_falling_after_recent_returns` / `sip_flat_after_recent_returns`: monthly SIP contributions compared against derived index returns from `lag_months` earlier (returns precede contributions); not a household allocation decision. Average month-over-month contribution growth is reported separately from absolute levels because long-run contribution growth can dominate a level comparison, months with missing returns or missing prior SIP are skipped, and conclusions require both rising and falling return observations. Stored index closes are levels, so month-over-month percent returns are derived from month-end closes and index points are never summed as returns.
- `co_occurrence_observed` / `unresolved`: same-session FPI and DII flows are co-occurrence — reporting or retrieval timestamps cannot establish the order in which the investor groups traded, so no behavioural-order claim is made without independently dated actor-response evidence. Forward returns are compounded over complete calendar months whose start is strictly after the evaluation date; incomplete windows are reported as unresolved, never as conclusions.

## Validation results

- Python regression tests (`tests/test_capital_flow_reflexivity.py`): 27 passed. Covering offset detection over matched sessions, threshold rejection, unmatched-session exclusion, gross-row exclusion, point-in-time persistence gating, SIP lag and growth-vs-level reporting, missing-return skipping, limited-direction detection, co-occurrence without order inference, complete-forward-month compounding, incomplete-window handling, late-ingested and future-dated row exclusion, observed-versus-hypothesised separation, mixed column parsing, missing-value skipping and changed-header rejection.
- Full Python suite: 149 passed.
- TypeScript typecheck: passed.
- Playwright: browser binaries were provisioned via `npx playwright install chromium`; the suite ran but requires the dev server on the target CI. The scoring changes are covered by the Python suite and the page typechecks clean.

## Limitations

1. All findings are descriptive co-occurrence. Flows data carries no actor motivation; FPI/DII attribution follows exchange publisher conventions and could change definition without notice.
2. DII is a residual exchange bucket — it mixes insurers, mutual funds, banks and prop desks, so 'domestic institutional buying' is not attributable to any specific actor.
3. Persistence ratios describe observed decay of co-occurrence, not absorption capacity, and the follow-up is explicitly retrospective.
4. SIP response is monthly and lagged; gross instalment flows cannot distinguish changing household behaviour from changing fund-house distribution activity, registration growth or discontinuations.
5. Reporting timestamps (retrieval order) cannot establish the order in which FPI and DII investors traded within a session; a causal actor-response claim would require independently dated actor-response evidence that this data does not carry.
6. Compounded forward returns use derived month-end percent changes; genuine missing months are skipped, so long gaps reduce the usable forward window rather than being bridged.
