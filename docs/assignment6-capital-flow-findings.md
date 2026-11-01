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
- **Scoring engine** (`packages/scoring/capital_flow_reflexivity.py`): descriptive offset (FPI sell + DII buy co-occurrence), persistence/absorption decay, monthly SIP-vs-return co-movement, and a spurious-association check that requires strict temporal order before any response claim.
- **Config** (`config/capital_flow.v1.yaml`): versioned thresholds and explicit falsification criteria.
- **Dashboard view** (`apps/web/app/intelligence/capital-flows`): evidence-first page showing offset state, persistence verdict, SIP response and limitations, with an explicit `data_unavailable` state when no attributable observations exist.
- **API endpoint** (`/api/v1/capital-flows`): returns the investigation snapshot or an explicit unavailable state; never fabricates flows.

## Investigation states

- `dii_offset_fpi_selling`: opposite-sign net flows over a 5-session window, co-occurrence only.
- `persistence_sustained` / `persistence_weakening` / `persistence_dissipated`: daily-average DII buying in the tail window vs the detection window (strictly forward-looking; no look-ahead).
- `sip_rising_with_subsequent_returns` / `sip_falling_with_subsequent_returns`: monthly SIP co-movement against subsequent returns, lagged; not a household allocation decision.
- `not_a_response` / `unresolved`: reported when DII is observed before FPI (order undetermined) or when no forward return window exists — these are never promoted to causal claims.

## Validation results

- Python regression tests (`tests/test_capital_flow_reflexivity.py`): 12 passed. Covering offset detection, threshold rejection, persistence decay, insufficient history, SIP response, spurious-association order checks, missing-session pairing, forward-window requirements, mixed column parsing, missing-value skipping and changed-header rejection.
- Full Python suite: 134 passed.
- TypeScript typecheck: passed.
- Web build: passed.
- Playwright: browser binaries missing in the validation environment (`chromium_headless_shell-1194`); the test runner's own install command did not fetch the required revision in this sandbox. This is an environment provisioning issue, not a code failure; the pre-existing test suite was unaffected by these changes.

## Limitations

1. All findings are descriptive co-occurrence. Flows data carries no actor motivation; FPI/DII attribution follows exchange publisher conventions and could change definition without notice.
2. DII is a residual exchange bucket — it mixes insurers, mutual funds, banks and prop desks, so 'domestic institutional buying' is not attributable to any specific actor.
3. Persistence ratios describe observed decay of co-occurrence, not absorption capacity.
4. SIP response is monthly and lagged; it cannot distinguish changing household behaviour from changing fund-house distribution activity.
5. The Playwright validation could not be completed in the current environment due to missing browser binaries; rerun `npx playwright install chromium` on the target CI before merging.
