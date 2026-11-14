# VILTARA SHOP — production readiness audit (2026-11-15)

## Scope and baseline

- Repository: AzizIo/Vstore
- Audited branch: main
- Baseline SHA: 2138d2b69c86507f05cec7ee768b4cc11ad00e47
- Default branch: main
- Open PR inventory: PR #197 only; it is a draft TON Escrow WIP and must not be merged as a production release change.
- Audit branch: chore/viltara-production-readiness-sprint

This is a source/configuration audit, not a live production penetration test or VPS inspection. No production credentials, servers, databases, bot tokens, DNS, TLS, or payment accounts were accessed or modified.

## Baseline CI evidence

At the audited SHA, GitHub Actions reported:
- Backend CI: success — https://github.com/AzizIo/Vstore/actions/runs/43639542590
- Frontend CI: success — https://github.com/AzizIo/Vstore/actions/runs/43639542638

The latest main commit description reports 692 backend tests passed and frontend/API-backed E2E checks. These checks do not constitute a verified production deployment, backup restore drill, live Telegram launch, or production payment acceptance.

## P0 — release blockers

No source-level P0 was confirmed in the inspected auth, order, payment, notification, health, and production Compose paths. This does not rule out a P0: dependency vulnerability alerts and live infrastructure were not accessible through the current repository inspection interface.

Mandatory release gates still fail closed until the P1 evidence below is completed.

## P1 — required before production launch

| Finding | Evidence / impact | Required action |
|---|---|---|
| Frontend dependency graph is not reproducible | No npm lockfile exists in main; CI and production Dockerfile use npm install with semver ranges | Generate and commit a reviewed package-lock.json; switch CI and production image to npm ci; rerun frontend tests/build/E2E |
| Backup/restore was documentation-only | Production Compose provides persistent PostgreSQL storage, but does not schedule backups or verify restore | Use the backup and isolated restore-drill scripts added in this sprint; schedule encrypted off-host retention on the VPS and perform a real restore drill |
| Monitoring and alerting are external | Compose healthchecks cover DB, Redis, API and Mini App; no external uptime/alerting or disk/volume monitoring is configured in-repo | Configure external checks and alerts for API readiness, Mini App, bot process, PostgreSQL storage, backup freshness and restore failures |
| Telegram notification delivery is at-least-once | Outbox uses row locks, claim tokens and retry leases; a crash after Telegram accepts a message but before DB acknowledgement can result in a duplicate | Keep message IDs/dedupe keys in logs and add operator reconciliation; do not claim exactly-once Telegram delivery |
| Bot runtime is polling-based and single-instance | Production bot is an opt-in Compose profile and uses polling; duplicate polling workers for one token conflict | Enforce one bot replica per token and monitor bot container health/restarts |
| Dependency security status is unverified | Dependabot/code-scanning alert endpoints were not available to this audit session | Owner must review GitHub Security alerts and run dependency audit before release |
| Backup protection/retention is not automated | Existing docs explicitly leave off-host backup, encryption, retention and restore drills to the operator | Configure encryption, off-host storage, retention and alerting; never keep the only backup on the VPS |

## Verified safety boundaries in source

- Telegram Mini App initData is HMAC-SHA256 verified, rejects duplicate fields, checks auth_date, and validates user ID/name types.
- JWT access tokens use HS256 with an explicit configured secret and expiry; dependencies resolve the subject to a current database user and enforce blocked-account rules.
- Order reservation uses database row locks and checks current NFT ownership outside the transaction before revalidating under locks.
- Telegram Stars checkout is guarded by a dedicated test flag, a separate test bot token, and non-production environment checks. Production Compose does not pass the test Stars settings.
- Refunds have durable per-charge records, leases and ambiguous-outcome reconciliation; the refund adapter is guarded for the dedicated test bot.
- Notification outbox records have dedupe keys, claim tokens, leases and bounded retry behavior.
- Production Compose isolates DB/Redis/API ports, binds the Mini App only to loopback, requires explicit production variables and an external PostgreSQL volume, and does not run migrations automatically.
- Escrow API routes are mounted only when TON_CONNECT_NETWORK=testnet; production Compose validation requires mainnet. Production checkout/refund/escrow is not enabled by this audit.

## P2 — defer after initial release

- Improve notification observability and support tooling beyond structured logs and outbox diagnostics.
- Add richer metrics dashboards and SLO reporting after external alerting is in place.
- Consolidate operational documentation and reduce old/obsolete feature branches after checking ownership.
- Revisit optional escrow functionality only under a separate security-reviewed release plan.

## Sprint changes

- scripts/production_backup.sh: writes a mode-0600 custom-format PostgreSQL dump, validates the archive with pg_restore --list, then writes a SHA-256 sidecar.
- scripts/production_restore_drill.sh: restores the supplied archive into a fresh throwaway database, checks core schema tables, and drops the throwaway database on exit. It never restores over the configured production DB.
- Production Compose CI now validates shell syntax and exercises backup plus isolated restore against an ephemeral PostgreSQL 17 service.

## Remaining owner actions

1. Review GitHub Security/Dependabot alerts and resolve all critical/high findings.
2. Generate and commit the npm lockfile; change frontend CI and Docker build to npm ci.
3. Configure encrypted off-host backup retention and run the restore drill on a production-like copy.
4. Configure external uptime, bot, disk, backup-freshness and restore-failure alerts.
5. Verify actual VPS reverse proxy/TLS/firewall and exact production volume/database before cutover.
6. Complete live Telegram Mini App launch, seller/buyer notifications and order cancellation acceptance with test users.
7. Keep Stars test bot, test payments, escrow and signing unavailable in production unless separately approved.

## Release decision

NOT PRODUCTION-READY YET. The audited main SHA has green Backend and Frontend CI and substantial application safety controls. The missing reproducible frontend dependency lock, operational backup/restore proof, external monitoring, and security-alert review are release gates. No production deployment or main merge was performed by this sprint branch.