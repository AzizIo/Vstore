# VILTARA SHOP — release lead checklist (2026-11-15)

**Decision: BLOCKED — not ready for production.** This checklist is an independent repository/PR/CI review. It is not a live VPS, Telegram, payment-provider, or TON testnet acceptance report.

## 1. Baseline

- Repository: `AzizIo/Vstore`
- Default branch: `main`
- Audited main SHA: `2138d2b69c86507f05cec7ee768b4cc11ad00e47`
- All three active implementation PRs below were created from this same baseline. No merge was performed during this audit.
- Production credentials, VPS/SSH, DNS, production database, Telegram bot, payment accounts and TON signing keys were not accessed.

## 2. Active PR inventory and evidence

| PR | Owner / scope | Head SHA | State | CI evidence | Release assessment |
|---|---|---|---|---|---|
| [#198](https://github.com/AzizIo/Vstore/pull/198) | Release/infra readiness: CI, npm lock, dependency audits, backup/restore scripts, production Compose | `8cca15b121d42a04753e7628fb562a889da4c9fd` | Draft | Backend CI [43642121885](https://github.com/AzizIo/Vstore/actions/runs/43642121885), Frontend CI [43642121795](https://github.com/AzizIo/Vstore/actions/runs/43642121795), Production Compose [43642121752](https://github.com/AzizIo/Vstore/actions/runs/43642121752): **success** | CI slice passes. External backup, monitoring, VPS and live Telegram gates remain open. |
| [#203](https://github.com/AzizIo/Vstore/pull/203) | Payments backend: payment evidence immutability and TRUNCATE guards | `b892f4af7b34c7e89d18902f2c7cdc14f6069ff6` | Draft | Backend CI [43643311896](https://github.com/AzizIo/Vstore/actions/runs/43643311896) and Frontend CI [43643311546](https://github.com/AzizIo/Vstore/actions/runs/43643311546): **in progress at audit snapshot** | Do not accept until final CI and PostgreSQL integration evidence are green; see integration findings below. |
| [#197](https://github.com/AzizIo/Vstore/pull/197) | TON escrow testnet readiness / shared listing reservation | `557ba5226c7b46b02359324bd79e7d52b946b83f` | Draft | TON Escrow Contract CI [43640445929](https://github.com/AzizIo/Vstore/actions/runs/43640445929), Backend CI [43640445928](https://github.com/AzizIo/Vstore/actions/runs/43640445928), Frontend CI [43640445926](https://github.com/AzizIo/Vstore/actions/runs/43640445926): **success** | CI is not live testnet acceptance. PR body still lists ABI/wrapper/BoC, adapter, finality, lifecycle, concurrency and independent contract-review work as incomplete. Keep signing disabled. |

The current open-PR inventory also includes #197, #198 and #203. The audit text currently present in PR #198 says “PR #197 only”; that inventory is stale and must be refreshed before it is treated as the latest audit.

## 3. Parallel-agent status

| Issue | Current evidence | Status |
|---|---|---|
| [#199 Payments Backend](https://github.com/AzizIo/Vstore/issues/199) | Issue comment links Draft PR #203. The PR adds migration `0015_payment_ledger_guards`, PostgreSQL tests and payment security documentation. | In review; CI was still running at this snapshot. |
| [#200 Production Infrastructure](https://github.com/AzizIo/Vstore/issues/200) | No issue progress comment and no dedicated PR found in the open-PR inventory. | Not delivered / not verified. |
| [#201 Frontend, Mini App, E2E](https://github.com/AzizIo/Vstore/issues/201) | No issue progress comment and no dedicated PR found in the open-PR inventory. | Not delivered / not verified. |

PR #198 already owns the current backup/restore scripts and several shared workflow/dependency files. The infrastructure agent must extend/review those changes rather than create a competing copy. The frontend agent must not independently rewrite the lockfile, Dockerfiles or shared CI changes in PR #198.

## 4. File-overlap and integration matrix

| Workstream | Files / zones | Overlap or sequencing requirement |
|---|---|---|
| PR #198 | `.github/workflows/backend.yml`, `.github/workflows/frontend.yml`, `.github/workflows/production-compose.yml`, `backend/pyproject.toml`, frontend package/lock/Docker files, production backup scripts, deployment/audit docs | Shared CI, dependency and infra surface. Any later agent change must preserve and revalidate this branch's behavior. |
| PR #203 | `backend/migrations/versions/0015_payment_ledger_guards.py`, its PostgreSQL integration test, payment security audit doc | No direct changed-path collision with #198, but it creates a real CI integration conflict: #198's backend workflow line 152 asserts the Alembic version is exactly `e20261114_ton_escrow`. After migration #203 is merged, the current migration head becomes `0015_payment_ledger_guards`, so that assertion will fail. Replace the hard-coded revision check with a comparison against the repository's dynamically resolved Alembic head before integrating both PRs. |
| PR #197 | `backend/app/api/escrow.py`, `backend/app/escrow/reservation.py`, escrow tests, contract artifact notes and testnet runbook | No direct changed-path collision with #198/#203. Keep escrow as a separate testnet-only gate; do not treat it as part of a production payment release. |
| Issue #200 | Production Compose, scripts and operations docs | Coordinate explicitly with #198 because backup/restore scripts and production validation workflow already exist there. |
| Issue #201 | Frontend application/tests/e2e | Coordinate with #198's frontend dependency and build changes. Re-run frontend unit/build/Playwright/API-backed E2E on the final combined SHA. |

### Required review findings

1. **PR #198 migration check is not integration-safe.** The pinned revision at `.github/workflows/backend.yml:152` must follow the actual Alembic head. Do not merge #198 and #203 together with the current hard-coded assertion.
2. **PR #203 test coverage is narrower than its migration guard.** The migration creates TRUNCATE guards on `payment_intents`, `payment_transactions`, `payment_events` and `payment_refunds`, while the added test explicitly attempts TRUNCATE only on `payment_events`. Add PostgreSQL assertions for all four tables before calling this guard fully covered.
3. **PR #198 backup script is a local backup primitive, not an off-site backup system.** It does not yet encrypt or upload backups, enforce retention, or lock concurrent runs. Its second-resolution filename can collide during parallel invocations; use a lock and collision-safe naming before relying on it operationally. The checksum sidecar should be published atomically with the dump.
4. **PR #198 restore drill verifies only a small core-schema presence check.** It does not prove application-level data/business invariants or a production-like restore destination. The current successful CI drill uses a disposable PostgreSQL fixture only.
5. **PR #152 is stale.** Its progress text still says PR #173 contains the unmerged refund worker. PR #173 was closed without merge; PR #179 was merged and migration 0013 is on main. Update #152 so future release reviews do not mistake the refund worker's merge state. The live Telegram test invoice/payment cycle is still not proven.
6. **PR #198's source audit must not be read as live verification.** It correctly lists VPS, off-host backup, external monitoring and live Telegram work as owner actions; none is verified by the repository CI.

## 5. Release gate checklist

| Gate | Status | Evidence / remaining work |
|---|---|---|
| Main baseline backend/frontend CI | **PASS** | Baseline run IDs are recorded in the PR #198 audit. |
| PR #198 backend, frontend, production Compose CI | **PASS** | All three workflows succeeded on exact head `8cca15b...`; not a merge or live-host test. |
| Reproducible frontend install, unit/build/Playwright and API-backed E2E | **PASS on PR #198 head** | npm lockfile, `npm ci`, npm audit, unit/build/Playwright and disposable PostgreSQL/Redis API-backed journey succeeded. Must rerun after integration. |
| Python dependency audit | **PASS on PR #198 head** | `pip-audit --strict` step succeeded in Backend CI. GitHub Security/Dependabot alert inventory is still not independently reviewed. |
| Payment ledger/refund code on main | **PARTIAL** | Test-only Stars integration and durable refund workflow are present. PR #203 hardening is pending CI/review. No live charge or refund has been performed. |
| Telegram Stars live test acceptance | **NOT VERIFIED** | Issue #152 still requires a real dedicated test-bot invoice → pre-checkout → successful-payment round trip against disposable PostgreSQL. |
| Telegram policy approval for public paid checkout | **BLOCKED** | [Issue #155](https://github.com/AzizIo/Vstore/issues/155) is open and has no recorded written Telegram response. Keep public paid checkout disabled. |
| Provider / seller settlement model | **BLOCKED** | Seller entity/status, seller and buyer jurisdictions, merchant-of-record, payout model and provider underwriting facts are not established in the repository. |
| TON escrow contract / testnet | **BLOCKED** | PR #197 is Draft. CI success does not satisfy live testnet lifecycle, independent finality, complete ABI-backed integration or independent contract review. Mainnet signing and real escrow remain disabled. |
| Backup/restore | **PARTIAL** | PR #198 CI validates dump/restore against disposable PostgreSQL. Encrypted off-host copies, retention, locking, monitoring and a production-like restore drill remain open. |
| External monitoring/alerting | **NOT VERIFIED** | No external uptime, bot, disk, backup freshness or restore-failure alerting evidence. |
| VPS TLS/firewall/volumes/reverse proxy | **NOT VERIFIED** | Source/config review only; no authorized live VPS inspection was performed. |
| Production migration / deploy / secrets | **NOT RUN** | No production migration, deploy, payment credentials or VPS changes are authorized by Issue #202. |

## 6. Required next actions

1. Payments owner: finish PR #203 CI; add TRUNCATE tests for all four protected tables; resolve schema-owner review.
2. Release/infra owner: fix the hard-coded Alembic head assertion in PR #198 and refresh its open-PR inventory. Coordinate the final workflow with PR #203 before either is considered integrated.
3. Infrastructure owner: deliver a focused PR for encrypted off-site backup design/automation, concurrency locking, retention, safe restore validation, monitoring and VPS runbook. Do not overwrite PR #198's scripts.
4. Frontend/QA owner: deliver the dedicated #201 PR with Telegram initData trust-boundary review, payment-state UI review, TonConnect network guard, and critical API-backed E2E evidence. Coordinate package/lock/Docker/CI changes with #198.
5. Update Issue #152 to reflect merged PR #179 and migration 0013, while keeping the real Telegram test cycle explicitly open.
6. Obtain written Telegram policy guidance in #155 and the owner/legal/provider decisions before considering any public paid checkout.
7. Complete live operational acceptance (encrypted off-site backup + restore drill, external monitoring, VPS TLS/firewall/volume checks and Telegram test-user journey) before a production decision.
8. Rebase/revalidate each PR after each integration step; require all checks on the final combined SHA. No production merge/deploy or real-money action is implied.

## 7. Release decision

**BLOCKED — NOT READY FOR PRODUCTION.** The green checks on #198 and #197 are scoped CI evidence, not a verified integrated release candidate. PR #203 is not yet green at this audit snapshot; #200 and #201 have not produced reviewable PRs; migration sequencing has a confirmed CI conflict; critical live operational, Telegram policy and TON escrow gates remain open.

No merge, deployment, production database mutation, live payment/refund, seller payout or mainnet signing was performed.
