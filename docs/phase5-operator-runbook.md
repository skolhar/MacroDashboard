# RBI WSS gross reserves operator runbook

Use isolated staging and named operator credentials. Do not run this workflow against production without separate deployment and data approvals.

1. Obtain the original RBI WSS HTML or text-layer PDF without altering its bytes. Retain its official URL, independent publication notice, exact timestamp and entitlement instrument. The WSS portal may require human access; do not automate around access controls.
2. Set `SOURCE_ARCHIVE_ROOT` to an isolated absolute path backed by a persistent volume. `SOURCE_ARCHIVE_MAX_BYTES` defaults to 4,000,000 and accepts 750,000–8,000,000 bytes. The API streams uploads with a hard bound; files are content-addressed, created atomically with no overwrite and read with `O_NOFOLLOW` and SHA-256 verification. Budget a minimum of twice the maximum original-file size per concurrent upload while temporary files exist.
3. Generate a normalized extract without touching the database:

   ```sh
   python -m scripts.prepare_rbi_wss_release original.pdf \
     --source-url https://www.rbi.org.in/RELEASE-URL \
     --publication-evidence-url https://www.rbi.org.in/INDEPENDENT-NOTICE \
     --published-at 2024-04-12T13:00:00+05:30 \
     --entitlement-basis written-permission \
     --definition-version rbi-wss-gross-reserves-v1 \
     --vintage-id ORIGINAL-RELEASE-ID --extract extract.csv
   ```

   The timestamp and URLs above are **command placeholders**, not claims about an actual RBI release. The command refuses to replace an existing extract and prints source and extract hashes for byte matching. Review every component and the original table manually. Mark an amended release as `--quality revised` with a new vintage ID and its own publication evidence.
4. An operator with `imports:write` uploads the unmodified original via `POST /api/v1/admin/releases/archive`, then submits `POST /api/v1/admin/releases/reviews` with archive reference, both hashes, exact publication evidence and note, entitlement basis/reference, and definition version. A different operator with `releases:approve` downloads the archived original, verifies publisher authenticity, timestamp, source definition and rights, and approves. Hash matching alone is insufficient.
5. The importer sends original bytes and extract through `POST /api/v1/admin/imports/release` with the approved review ID. The server re-reads the archived bytes, reparses the original, checks the first USD-million total and week against the extract, and inserts both normalized observation and component row. Duplicate retries are idempotent; a changed original or value under the same vintage is rejected. Check the response `inserted`, `duplicate`, `revisions`, run ID and source hash.
6. Check `/api/v1/external-liquidity`, the reserves series and the gap report in staging. Confirm source-known versus system-known replay around publication and ingestion times. If other required signals are missing, the external-liquidity composite must remain N/A. Never label a gross-reserve change as intervention.

## Backup, retention and recovery

Back up the archive volume **and** PostgreSQL review/observation data as one recoverable set after each approved import; keep encrypted access-controlled copies outside the staging host. Document the retention period required by the rights instrument before importing. Do not delete or alter an archived original while any review or observation references it. Test restoring to a separate isolated environment, verify each stored SHA-256, and compare release-review links before resuming imports. SHA-256 detects changed bytes but does not prove publisher identity or licence rights. A missing/corrupt original blocks review and import; restore from a verified backup, never substitute a modern revised file for a historical vintage.
