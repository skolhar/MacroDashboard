# Phase 2 repository audit and implementation plan

Audited `main` at `2e88b22` before development on `feature/phase2-reflexivity-engine`.

## Existing behavior

- FastAPI exposes the Phase 1 read contracts and calculates a dashboard on demand. `published_at` and `ingested_at` gate system-known observations; `source_known` gates on publication alone.
- SQLAlchemy and Alembic store indicator definitions, numeric observations, raw snapshot metadata, score snapshots, alert events and policy events. Timestamp conversion to UTC is explicit.
- The 12-indicator registry and `v1` YAML provide six baseline cycle weights, thresholds, and an FX rule. The IT cycle has no scored signal, so overall risk is N/A.
- `seed.py` generates deterministic, clearly labeled synthetic data. Next.js shows six panels, a chart, a watchlist, basic source status and one on-demand FX rule. Docker Compose starts PostgreSQL, the API and web; Caddy is an optional production profile.
- Nine pytest tests cover Phase 1 calculations, vintage isolation, API health and demo isolation. A Playwright smoke test checks desktop and mobile. CI builds and typechecks the web app.

## Gaps and risks found

1. Compose embeds a database password and a fallback admin token. API defaults to DEMO; the seed runs on every API start. This is unsafe for an accidentally deployed production instance.
2. No write endpoints, authentication, authorization, rate limits, source adapters, manual import validation, provider licensing gate, ingestion audit log or approved host list exist.
3. `observations_at` excludes demo in live mode but otherwise accepts any quality, including values later classified as conflicts. It does not explicitly mark source replacement or signal range checks.
4. The FX alert is stateless, evaluated from a short date window, has no persisted transitions, hysteresis or market-calendar awareness. Other required inflection rules are absent.
5. Scores lack momentum, acceleration, confirmation and meaningful confidence; `direction` is always `unknown`. The `v1` rules cannot cover all six cycles.
6. The UI has hardcoded DEMO language and one synthetic chart, with no historical alert or replay presentation. The page hides API failure behind a DEMO fallback.
7. The initial migration uses `Base.metadata.create_all`, which cannot express forward-only schema changes. There is no release-safe separation between local and production database configuration.
8. The web image includes no authentication boundary for API writes; Caddy exposes API docs publicly. Production licensing and data provenance require operator review.

## Prioritized checklist

1. **Security and environments:** explicit `APP_ENV`, fail-closed secrets, no production demo seed, authenticated role-gated admin routes, bounded request sizes and rate limits.
2. **Data layer:** additive migration; documented adapter protocol, official Treasury adapter and licensed/manual adapter templates; immutable vintage imports with validation, checksums, source health and calendar-aware freshness.
3. **Scoring:** versioned `v2` rules covering all six cycles; level, momentum, acceleration, confirmation, confidence and coverage; preserve `v1` output for Phase 1 compatibility.
4. **Inflection:** six explainable rules, evaluation persistence, recovery hysteresis and stored transitions with rule version. Replay recomputes from historical as-of values and never writes alert history.
5. **UI/API:** preserve existing routes and visual system; display mode, source quality, six cycles, alert evidence/history and drilldowns. Add replay and admin routes.
6. **Validation:** pytest, typecheck, build, Playwright, local Compose migration and API checks; document unresolved source entitlements and deployment gate.

No production host, secret or database is accessed during this branch's implementation.
