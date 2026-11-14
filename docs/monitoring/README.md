# VILTARA SHOP monitoring

Provider-neutral Prometheus-compatible templates and local validation. This component is independent of production Compose and does not duplicate PR #198 backup/restore scripts or notification-outbox diagnostics.

## Files and local smoke checks

- prometheus.yml.example and blackbox.yml.example: scrape and HTTP/TLS probes.
- rules/alerts.yml: infrastructure alert rules.
- alertmanager.yml.example: non-delivering sink routing; no external receiver configured.
- scripts/: dependency-free static validator and explicit read-only endpoint probe.
- tests/: endpoint-probe safety tests using a localhost fixture.

Python 3.11+; these commands do not contact external services:

    python3 docs/monitoring/scripts/check_monitoring.py --simulate
    python3 -m unittest discover -s docs/monitoring/tests -v

Optional explicit endpoint/TLS checks:

    python3 docs/monitoring/scripts/check_endpoints.py --api https://staging.example.invalid/api/health/ready --miniapp https://staging.example.invalid/ --tls-host staging.example.invalid

Credential-bearing URLs and query parameters named token/secret/password/api_key/auth are rejected. HTTP redirects are not followed. The probe prints only status, latency and days to TLS expiry; it never prints response bodies, headers, paths or query strings. Do not point it at production without separate authorization.

## Signal and privacy contract

The existing FastAPI /api/health/ready endpoint remains the API service-level check. External probes record only HTTP status/latency and TLS expiry. The readiness response includes component details and TON Connect domain configuration; do not persist its body or copy it into labels/logs.

Only aggregate infrastructure metrics and bounded labels such as service, job, severity and instance are permitted. Never expose Telegram IDs, wallet addresses, order/payment/listing identifiers, emails, request paths containing IDs, exception text, secrets, database URLs or command output.

Production bot uses polling and currently has no Docker healthcheck. Container health/restart metrics do not prove polling or message delivery. A bot heartbeat/synthetic Telegram acceptance check remains an owner-controlled live gate; do not create bot API traffic from CI.

## Alert thresholds, deduplication and resolution

Initial configurable thresholds are in rules/alerts.yml:

| Signal | Warning | Critical |
|---|---:|---:|
| Host root filesystem | >80% for 10m | >90% for 5m |
| PostgreSQL persistent volume | >80% for 10m | >90% for 5m |
| Backup freshness | — | last verified success older than 26h for 5m |
| Backup execution | — | latest run failed for 1m |
| TLS remaining validity | <21 days for 15m | <7 days for 5m |
| API readiness | — | failed for 2m |
| Mini App HTTPS | — | failed for 3m |
| PostgreSQL / Redis | — | unavailable for 1m |
| Bot container | — | unhealthy or >=3 restarts in 15m for 2m |

All rules have severity, firing debounce and runbook annotations. Alertmanager groups by alertname/service/severity. group_wait, group_interval and repeat_interval are explicit. Stable names and bounded labels support deduplication. The checked-in receiver is a non-delivering sink. A real receiver must set send_resolved: true; the alert must transition to resolved when the expression clears. Maintenance silences require an expiry and incident reference.

Some signals require deployment-owned private exporters/adapters, not assumed native metrics:
- viltara_postgres_volume_used_ratio: 0..1 used ratio for the persistent PostgreSQL volume.
- viltara_backup_last_success_timestamp_seconds: last verified remote backup timestamp.
- viltara_backup_last_run_success: 1/0 for the latest backup run.
- container_health_status and container_restart_count with bounded container/service labels.

PostgreSQL exporter must use a dedicated least-privilege role; Redis exporter must use ACL-scoped credentials. Exporters and Prometheus must be private/loopback-only. Never expose Docker socket, exporters, metrics, DB or Redis publicly.

## Installation

1. Choose a monitoring host/private network outside the VPS failure domain. Pin approved Prometheus, Alertmanager and exporter images/digests in deployment-owned infrastructure.
2. Mount templates read-only and configure private scrape targets.
3. Deploy node exporter, PostgreSQL/Redis exporters, a restricted container metrics collector and backup metadata exporter. Configure blackbox exporter from blackbox.yml.example.
4. Probe TLS from outside the VPS failure domain.
5. Store credentials and receiver URL/token through a secret manager or protected mode-0600 files. Never commit secrets or pass them in command arguments, image build args, CI logs or dashboards.
6. Keep sink receivers until the owner approves an alert destination and recipient. Then enable a receiver with send_resolved and perform one authorized firing/resolution test.
7. Keep monitoring endpoints private; do not publish Prometheus/exporters/DB/Redis.

## Secret rotation

Rotate a receiver credential in the secret manager, deploy replacement, verify an owner-authorized controlled test, then revoke the old credential. For exporters, create a least-privilege replacement identity, update secret, verify scrape, then revoke the old password. Never print environment values.

## Maintenance, incident response and rollback

- Silence only the affected alert/service for a bounded window with an expiry and incident/ticket reference. Never silence a class or whole service indefinitely.
- Acknowledge and inspect aggregate metrics and redacted logs. Distinguish service outage from exporter/scrape failure.
- Preserve known-good backups. Alert handlers must never restore a database, delete volumes, downgrade migrations or mutate application state automatically.
- Mitigate through the existing human-approved deployment/rollback runbook. Monitoring rollback must not change application/database state.
- Confirm the alert becomes resolved and keep an incident timeline without customer/order/payment details.

## Automated checks vs live acceptance

CI/local checks validate YAML parseability, required rule inventory/fields, severity and threshold values, privacy/secret denylist, alert pending/firing/recovery semantics, and endpoint probe safety through localhost fixtures. They do not prove deployment or real notification delivery.

Owner-only live acceptance remains pending: approve monitoring host/failure domain, private targets/exporters and capacity thresholds; configure secret manager/receiver/on-call; verify real bot heartbeat, remote backup freshness/failure and restore drill, TLS renewal/expiry, and one real firing plus resolved notification. No production VPS, DNS, database, Telegram bot, cloud account or external receiver is accessed here.
