# Isolated staging deployment and rollback

## Local deployment

1. Copy `.env.staging.example` to a **private file outside the repository**. Generate a unique staging PostgreSQL password and URL; do not reuse production secrets. The Compose file binds only to `127.0.0.1` and uses project `smarthedge-staging` with its own named volumes.
2. Run `docker compose --env-file /path/to/private-staging.env -f docker-compose.staging.yml up -d db`.
3. Run `docker compose --env-file /path/to/private-staging.env -f docker-compose.staging.yml run --rm --build api alembic upgrade head`. This is the **staging database only**. Check `alembic current` reports `0003 (head)`.
4. Run `docker compose --env-file /path/to/private-staging.env -f docker-compose.staging.yml up -d --build api web caddy`. Use `http://127.0.0.1:18080` for the monitor and `http://127.0.0.1:18000/api/v1/health` for API health. Neither port is publicly bound.
5. Provision an expiring scoped credential with `docker compose ... exec api python -m packages.jobs.operators issue <operator-id> --scopes ingestion:run --days 30`. Store the raw token securely; the command shows it once. Use a separate `imports:write` credential for manual data review. Revoke immediately with `python -m packages.jobs.operators revoke <token-hash>`; `list` shows digests, never raw tokens.
6. Run a reviewed Treasury import through the loopback API or start `docker compose --env-file /path/to/private-staging.env -f docker-compose.staging.yml --profile ingestion up -d --build scheduler`. The worker polls every six hours. Keep it stopped until source/entitlement review authorizes ongoing requests.

The staging Caddy route returns 403 for administrative paths. For remote operator work, use an SSH tunnel to port 18000; do not expose that port or put an admin token in a URL. `TRUSTED_PROXY_CIDRS` matches only the isolated Compose network. Logs are separate under the staging Compose project; `docker compose ... logs api scheduler caddy` and `/api/v1/sources/health` show operational failures without returning secrets. API and web healthchecks are in the staging Compose file.

## Rollback and rotation

- Stop web/API/scheduler with `docker compose ... down` **without `-v`** to retain staging PostgreSQL and Caddy volumes. Revert only the staging image/branch, then restart after checking schema compatibility. `0003` is additive; avoid downgrading a database with credential/audit/checkpoint history unless a reviewed backup and rollback plan exists.
- Take a staging database backup before each migration. Restore only into the isolated staging project. Never point this Compose file at a production database.
- Rotate an operator token by issuing a new token for the same identity, updating the secret holder, then revoking the old digest. Rotate staging database credentials with a controlled PostgreSQL credential update and Compose restart. Record changes in the operator runbook, not Git.
- To discard this local staging instance, stop it, export any needed audit records, then remove the **staging project only** with `docker compose ... down -v`. This destroys staging volumes; never use the production Compose project for this action.

## Validation on 31 October 2026

- Fresh isolated PostgreSQL migration reached `0003 (head)`; staging API, web, Caddy and PostgreSQL started with separate volumes. Health returned `environment=staging`, `mode=live` and no secret fields.
- Before ingestion, risk was N/A and data confidence was 0. Staging Caddy returned 403 for GET and POST to an admin path.
- A scoped, one-day staging operator imported 21 October 2026 rows from the official Treasury XML endpoint. Repeating the import inserted 0 observations and reported 21 duplicates. The dashboard then showed one verified source-backed indicator, 6/100 data confidence and **no composite risk score**. This is a real staging ingestion, not merely a parser fixture.
- The staging scheduler completed one further idempotent polling run. The local scheduler was stopped after validation. Production was not contacted, migrated or modified.
