# Assignment 4: Indian macro research acquisition and normalization

## Scope and architecture

This is a private exploratory layer on top of merged Assignment 3. The public six-cycle monitor, approved RBI release imports, Yahoo market adapter and cycle-intelligence catalog are unchanged. Raw World Bank observations are stored as `ResearchEvidence`, separate from governed `Observation` releases and synthetic demo rows. The acquisition job records `IngestionRun` success/failure; a repeated identical value is skipped, while a changed value for the same period becomes a new immutable revision. No new database table or migration is needed; the existing `discovery_1` schema is reused.

The focused registry has **11 India indicators** across banking, external, inflation and activity. Four annual World Development Indicators (private credit/GDP, broad money/GDP, real GDP growth and household consumption growth) and seven monthly Global Economic Monitor indicators (CPI index, industrial production, monthly-average official exchange rate, total reserves, merchandise imports, merchandise exports and reserves import cover) are fetched by two source-specific adapters in `packages/connectors/world_bank.py`. The [World Bank Indicators API](https://datahelpdesk.worldbank.org/knowledgebase/articles/898581) supports bounded JSON queries without credentials. [GEM catalogue metadata](https://datacatalog.worldbank.org/infrastructure-data/search/dataset/0037798/global-economic-monitor) identifies public access and CC BY 4.0. [World Bank data terms](https://data.worldbank.org/summary-terms-of-use) require attribution and warn that some third-party indicators have separate terms. SmartHedge keeps this data private pending indicator-level rights and definition review. The API's dataset `lastupdated` date is **not** treated as each observation's publication timestamp; `published_at` remains null and retrieval time bounds system-known history.

### Run in isolated development or staging

Set `APP_ENV=development` or `staging`, `DEMO_MODE=false` and a database URL for an **independent** database. Then:

```sh
alembic upgrade head
python -m packages.jobs.wdi_research --dataset both --start-year 2000 --end-year 2026
```

The WDI request is bounded to 1960 onward and at most 70 years; GEM defaults to 2018 onward and at most 10 years. Requests use one fixed World Bank host, a 5 MB response limit, finite-value validation, bounded timeout and at most three retries with backoff for transient failures. Empty data is reported `unavailable`; errors record a failed run and do not substitute synthetic values. A scheduled private job can run this command periodically; do not schedule it in demo or production. The public release-review and two-operator approval controls remain intact for verified/public RBI and other Indian data.

## Economic transformations

`config/economic_transformations.v1.yaml` declares an indicator-specific primary transformation, cadence, unit, baseline length, persistence length and provisional robust-deviation threshold. `config/discovery.v2.yaml` adds cross-sector questions while leaving `discovery.v1.yaml` for historical snapshots. Raw values are retained in every transformed observation and input IDs/revisions are included. Frozen discovery snapshots store **both** rule files and the exact result, including transformed values.

The pure transformation functions support raw value, year-on-year and month-on-month percentage changes, rolling growth, first difference, growth-rate change, seasonally comparable difference, rolling sum, rolling historical deviation, rolling volatility, momentum, acceleration and same-period spread. Percent growth is unavailable when the reference or current level is nonpositive. Differences retain zero and negative values. Missing reference periods are never interpolated. Mixed frequencies cannot form one persistence window or cross-indicator candidate. Monthly index levels use YoY, monthly FX/reserves use MoM, annual already-normalized growth rates use percentage-point differences, and annual credit/GDP and money/GDP ratios use percentage-point differences. A rise in a structurally growing level is therefore not directly called anomalous.

For the configured monthly CPI/IIP/trade YoY series, a prior-year level more than 10% below its two-year prior level marks a possible base effect. Such a persistent-looking result is labelled `BASE_EFFECT_REVIEW` and cannot create a causal candidate. This is a conservative screening rule, not a proof that the economic change was ordinary. Freshness windows, missing consecutive releases, conflicts and all thresholds remain provisional. Market prices are secondary confirmation and cannot independently prove an economic mechanism.

## Historical and access semantics

`GET /api/v1/research/discovery` now accepts `episode_end` separately from a timezone-aware `as_of`. `as_of` is the knowledge cutoff. With `episode_end`, the engine uses only observation periods through that date but can inspect data retrieved by the later knowledge cutoff; it labels the result `retrospective_current_vintage`. This **does not** claim that the present-vintage WDI/GEM values or transformations were known during the historical episode. Without `episode_end`, system-known excludes later retrievals. Source-known only uses independently stated publication timestamps; when missing, it falls back to retrieval time. Historical rule content and input revisions remain frozen in a `DiscoverySnapshot`. No threshold is presented as an investment probability.

`GET /api/v1/research/coverage` requires `research:read` and returns source-run health, each indicator's latest raw/transformed observation, frequency, observed span, missing periods, freshness, and anomaly usability. It also labels research questions investigable, incomplete or unavailable and lists blocked direct sources. The private `/intelligence/discovery` page displays this coverage with a visible source/quality caveat and links to supporting observations. It remains behind the existing private UI authentication and is disabled by the API in demo and production.

## Direct-source gaps

| Source | Current decision |
| --- | --- |
| RBI WSS banking liquidity, credit, deposits, money, reserves and yields | The existing WSS reserves parser is governed-release only. The WSS portal presented a CAPTCHA in the prior source audit; no bypass is attempted. Direct definition, historical release and access review remains necessary. [RBI DBIE FAQ](https://dbieold.rbi.org.in/DBIE/doc/Frequently%20Asked%20Questions%20-%20DBIE.pdf) permits research use with attribution, but public redistribution is a separate decision. |
| MoSPI CPI and IIP | [Official CPI OpenAPI](https://esankhyiki.mospi.gov.in/layout/swagger_user_cpi.yaml) and [IIP OpenAPI](https://esankhyiki.mospi.gov.in/layout/swagger_user_iip.yaml) advertise bearer-token security. No token is available; no attempt to bypass it was made. GEM is explicitly a secondary interim source. |
| AMFI SIP and fund flows | [AMFI terms](https://www.amfiindia.com/terms-of-use) restrict site use to personal, noncommercial purposes absent written agreement. No automated AMFI ingestion or storage was added. |
| NSDL FPI, NSE DII/breadth and FBIL reference fixing | Access, definitions and permitted reuse remain unresolved under the earlier [acquisition audit](phase4-acquisition-audit.md). The GEM monthly-average exchange rate is not a tradable USD/INR spot quote or the FBIL fixing. |

The next research step is to obtain permitted official monthly/weekly banking, FPI and domestic-flow observations with independently evidenced publication dates. These are needed to test actor responses and feedback rather than infer them from World Bank aggregates alone.
