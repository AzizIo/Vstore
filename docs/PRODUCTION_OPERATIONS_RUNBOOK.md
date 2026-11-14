# Production operations and recovery runbook

**Scope:** static repository configuration only. The VPS, DNS, TLS endpoint, live database, Telegram, and remote backup account have not been inspected or changed. Complete the live checklist before declaring production ready.

## Release gate

- [ ] Confirm reviewed deployment commit/image digests and preserve the previous image.
- [ ] Confirm the exact external PostgreSQL volume name and PostgreSQL major version. Never attach one data directory to two running servers.
- [ ] Verify TLS terminates at the reverse proxy and forwards only to the Mini App loopback listener. Port 8081 must not be public.
- [ ] Verify firewall rules for IPv4 and IPv6: allow only required public ports (normally 80/443); restrict SSH to an administrator allowlist or VPN. Do not expose 5432, 6379 or 8000.
- [ ] Configure encrypted off-host backups and prove restoration into an isolated database.
- [ ] Configure alert delivery and test a real notification.
- [ ] Run the external read-only preflight and Telegram/Tonkeeper acceptance separately.

## Exposure and data map

| Component | Intended exposure | Persistent state |
|---|---|---|
| Nginx Mini App | Host loopback only; public access through TLS reverse proxy | Static image contents |
| FastAPI API | Compose network only; proxied by Nginx | PostgreSQL |
| PostgreSQL | Compose network only; explicit external named Docker volume | Application records, listings, orders and moderation history |
| Redis | Compose network only; no host port | Treat as disposable cache/coordination state unless code review proves otherwise |
| Optional bot | Outbound Telegram API/polling; Compose network | Durable notifications and business state in PostgreSQL |
| Backups | Encrypted off-host destination | PostgreSQL custom-format archives and checksum metadata |

The external Docker volume is deliberate: Compose must not silently create a new empty volume if the configured name is wrong. Never run docker compose down -v or prune/remove the production volume during deploy/rollback.

## Backup design (credentials intentionally not supplied)

Use a dedicated backup identity and an off-host object-storage destination with versioning/object lock where available. Encrypt on the VPS **before upload** using age recipient-based encryption. A public recipient may be deployment config; the private decryption identity must be held separately, ideally offline. Never upload plaintext dumps.

Suggested initial policy, subject to owner approval:
- Daily encrypted full PostgreSQL dump; retain 7 daily, 5 weekly and 12 monthly recovery points.
- Keep at least one protected copy in a different account or failure domain from the VPS.
- Separate upload-only credentials from read/delete administration credentials; scope access to the backup prefix.
- Store a SHA-256 sidecar per encrypted object. Verify the downloaded ciphertext checksum before decryption, then verify the archive using pg_restore --list.
- Alert if the latest successful remote backup is older than 26 hours, an upload/checksum fails, or retention configuration drifts.
- Rotate upload credentials periodically and after suspected compromise. For encryption-key rotation, add a new recipient during an overlap period, verify a test restore with the new key, then retire the old key only after retained objects remain recoverable.
- Do not claim backups are usable until an isolated restore drill succeeds.

Do not automate upload until the owner chooses the provider, remote name, retention enforcement and credential mechanism. Safe automation must use a lock, restrictive umask, temporary files cleaned by traps, archive validation, encryption before transfer, checksum verification, secret-free logs and a remote temporary object published only after verification. A failed upload must not replace the last known-good remote object. Do not invent access keys or place them in repository examples.

## Restore runbook

1. Declare an incident/recovery owner and identify the recovery point. Preserve logs and the original database volume.
2. Download the encrypted archive to a restricted temporary directory. Verify SHA-256 before decryption. Never print secrets or decrypted rows.
3. Decrypt with umask 077 and file mode 600. Verify the PostgreSQL custom-format archive with pg_restore --list.
4. Create a **new, uniquely named disposable PostgreSQL database/container/volume** using a compatible major version. Do not point connection variables at production or use its database name.
5. Restore only into that disposable target. Never run pg_restore --clean against production.
6. Check required tables/schema, current Alembic revision, foreign-key integrity, order/listing references and documented business invariants. Compare row counts or aggregates without dumping personal data.
7. Record archive checksum, source timestamp, PostgreSQL version, migration revision and results. Drop the temporary database and remove plaintext files even on failure.
8. Production recovery is a separate, human-approved operation with a reviewed plan and verified backup. A drill must never automatically restore over production.

## Deployment and rollback

### Preflight
- Require green CI for backend, frontend, API-backed E2E, dependency audits, Compose/Nginx validation, migration upgrade and backup/restore drill on the exact reviewed SHA.
- Inspect git status, image tags/digests, required environment-variable presence (never print values), disk space, current containers and the exact database volume mount.
- Verify a recent encrypted off-host backup and successful restore drill.
- Review Alembic revisions between current and target head. Identify destructive/non-backward-compatible migrations and write a recovery plan before deployment.
- Validate configuration without starting services using docker compose -f docker-compose.production.yml config -q.

### Deploy
1. Build/pull the exact reviewed commit and preserve the previous image digest.
2. Take and verify a backup before any destructive migration.
3. Start dependencies and wait for health checks.
4. Run migrations as a one-off API container only after human approval: docker compose -f docker-compose.production.yml run --rm api alembic upgrade head.
5. Start API and Mini App. Start the optional bot profile only after verifying the production token and that exactly one polling worker will run.
6. Verify container health, curl -fsS http://127.0.0.1:8081/api/health/ready, public HTTPS/API readiness, Mini App HTML, manifest and icon. Smoke-test with a designated account and check logs for credential leakage.
7. Monitor errors, restarts, DB connections, disk and backup alerts. Record commit, image digests, migration revision and outcome.

### Rollback boundaries
- Application-only rollback is allowed only while the schema remains backward compatible.
- Reverting an image does not reverse a database migration. Do not automatically downgrade or restore production.
- For incompatible/destructive migrations, stop rollout and follow the pre-approved forward-fix or human-led recovery plan.
- Never run docker compose down -v, delete the external PostgreSQL volume, or use a development/Preview database as a rollback shortcut.

## Monitoring and alerting

Use an external monitor outside the VPS failure domain and route alerts to an owner-controlled destination. Tokens and notification URLs belong in secret storage, never this repository.

| Signal | Check | Alert |
|---|---|---|
| API readiness | HTTPS GET /api/health/ready | 2–3 consecutive failures |
| Mini App | HTTPS GET / and expected status/content | unavailable for 2–3 minutes |
| TLS expiry | External certificate probe | warning at 21 days; critical at 7 |
| Bot | Restart count plus bot-specific heartbeat/synthetic check | missed heartbeat or repeated restarts |
| PostgreSQL | pg_isready, connection count, volume usage | unavailable; connections near limit; disk >80% warning / >90% critical |
| VPS disk/inodes | Provider monitor or system exporter | >80% warning / >90% critical |
| Redis | redis-cli ping, memory and evictions | unavailable or unexpected memory pressure |
| Backup freshness | Remote object timestamp and checksum metadata | no verified remote backup within 26 hours |
| Backup job | Exit status and upload/checksum result | any failure |
| Restore drill | Isolated restore and schema/migration checks | failure or missed scheduled run |

Use least-privilege read-only monitoring credentials. Do not expose Prometheus, exporters, Docker socket, database metrics or Redis publicly. Restrict exporters to private networking or loopback. Rotate logs and redact authorization headers, bot tokens, database URLs and personal data.

## VPS hardening checklist

- [ ] Default-deny inbound firewall; allow 80/443 and tightly allowlisted/VPN SSH only; verify IPv4 and IPv6.
- [ ] SSH keys only, root login disabled where practical, password authentication disabled, restricted users and MFA/VPN for administration.
- [ ] TLS auto-renewal and expiry alerts; reverse proxy preserves Host and sets a trusted HTTPS forwarded-proto value. Do not trust arbitrary client-supplied forwarded headers.
- [ ] Add HSTS only after HTTPS is verified for all relevant subdomains. Test CSP against Telegram Mini App/TON Connect before enabling it. Keep nosniff and a suitable referrer policy.
- [ ] Rate-limit sensitive/public API routes at the edge; set request/body/time limits and upstream timeouts.
- [ ] DB and Redis private only; no Docker socket mount; avoid privileged containers; pin image versions/digests where feasible.
- [ ] Restrictive .env permissions; secrets absent from Git, build args, image layers, logs, CI artifacts and shell history. Build arguments are not secret storage.
- [ ] Non-root application processes where supported, minimal file permissions, patched base images and unattended security updates with a reboot policy.
- [ ] Container log rotation, disk/inode monitoring, time sync, incident contact and tested recovery procedure.
- [ ] Review GitHub dependency/security alerts and image vulnerabilities independently; CI audit success is not proof of zero vulnerabilities.

## Static review findings and limitations

- Production Compose binds the Mini App host port to loopback and does not publish API/PostgreSQL/Redis ports. PostgreSQL uses an explicitly named external volume.
- API has a readiness healthcheck and DB/Redis health dependencies. The optional bot currently has no container healthcheck; Docker health alone cannot prove polling or notification delivery. Add an external heartbeat or bot-specific synthetic check.
- Nginx hides its version and sets nosniff/referrer policy, but no CSP/HSTS. TLS is expected at an external reverse proxy; verify the actual proxy and forwarded-header trust chain on the VPS.
- Compose requires explicit production variables and sets TON mainnet by configuration. Repository checks cannot prove the live .env values.
- No live ports, firewall, TLS certificate, disk, database volume, Telegram bot or backup destination was accessed in this task.

## Owner decisions needed before backup automation

Choose the remote provider/name/prefix, retention/versioning policy, age recipient and offline identity custody, scoped upload credentials via secret manager, alert destination, recovery-point objective (RPO), recovery-time objective (RTO), and an approved maintenance window for restore drills. Never send credentials in chat.
