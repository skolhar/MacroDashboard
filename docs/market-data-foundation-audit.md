# Assignment 1 audit — market-data foundation

Audited 1 November 2026 against `origin/main` at `73a6c2978542b360a8e11c6e3e364e5dd6910b76`. Issue [#9](https://github.com/skolhar/MacroDashboard/issues/9) governs product scope; its latest decision makes medium-term macro investment intelligence the goal and removes brokerage, options execution and live trading requirements.

## Existing system

Main has FastAPI, Next.js, PostgreSQL, Alembic through `0004`, six experimental macro cycles, vintage-aware official-release observations, governed two-operator source review, named operator scopes and database-backed staging rate limiting. The existing UI is the Inflection Monitor and External Liquidity Monitor. Phase 1 demonstration data is explicit and isolated. One official U.S. Treasury 10-year source has been ingested in isolated staging; Indian and licensed market feeds remain unavailable. The v2 risk index is not a price-direction model.

## Open work and overlap

| PR | State and relevant content | Integration decision |
| --- | --- | --- |
| [#10](https://github.com/skolhar/MacroDashboard/pull/10) | Open, main-based; adds Nifty, MCX crude and FX `N/A` trend overview to the existing monitor. | Preserve its conservative `N/A` principle. A separate market route linked from the existing monitor will display normalized price history when available. Do not claim Yahoo WTI is MCX crude. |
| [#11](https://github.com/skolhar/MacroDashboard/pull/11) | Open, main-based; standalone synthetic attention-first prototype. | Do not merge or copy synthetic market claims into live research. Keep the existing SmartHedge visual system. |
| [#13](https://github.com/skolhar/MacroDashboard/pull/13) | Open, based on #11; server-side Yahoo chart fetch, price trend/anomaly heuristics and research page. No persistence, provider interface or independent runtime validation. | Reuse the symbol candidates and explicit unavailable/futures caveats. Keep its price-only heuristics out of this foundation; retrieval and persistence belong in the backend. Its direct Next.js Yahoo fetch would duplicate and bypass the provider-neutral layer. |
| [#8](https://github.com/skolhar/MacroDashboard/pull/8) | Open Phase 5 RBI WSS work, main-based; migration revision `0005`. | This assignment branches from current main, not #8. Use a distinct Alembic revision ID. If both PRs merge, add a reviewed merge migration or rebase the later PR so the chain has one head. Do not merge either PR automatically. |

## Gaps and design

There is no persistent market OHLCV table, instrument/provider mapping registry, Yahoo adapter, source-status endpoint or market route on main. Official macro release records require publication and entitlement evidence that Yahoo secondary prices do not provide; market bars will therefore have separate tables and will never enter macro v2 scoring automatically. The new provider protocol will return normalized bars with exchange session date, market/timezone/currency, raw OHLCV, optional adjusted close, fetch timestamp, source URL, and futures rolling caveat. Append-only content hashes preserve changed vendor bars as separate vintages while exact retries remain idempotent. Historical reads select only records retrieved by the requested as-of timestamp.

For the initial research setup, Yahoo/yfinance requires no source API credential. Its own documentation says the Yahoo Finance API is intended for personal use; Yahoo's permission guidance does not grant quote redistribution. Therefore retrieval and persistent storage are restricted to isolated development/staging research, with public production display disabled pending a documented licence. No access-control workarounds, proxy rotation or synthetic fallback will be used. Upstox can later implement the same protocol, subject to coverage and entitlements.
