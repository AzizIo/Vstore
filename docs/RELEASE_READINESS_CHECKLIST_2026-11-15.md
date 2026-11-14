# VILTARA SHOP — release lead checklist (2026-11-15)

**Decision: BLOCKED — not ready for production.** This is a repository/CI evidence review. It is not live VPS, Telegram policy, payment-provider, or TON testnet acceptance.

## 1. Current baseline

- Repository: `AzizIo/Vstore`
- Default branch: `main`
- Main SHA after the payment integration merge: `ef3d280f52cd03a1c6ead4e60527b4fd0badd078`
- Production credentials, VPS/SSH, DNS, production DB, Telegram API, payment accounts and TON signing keys were not accessed.

## 2. Merged implementation

| PR | Merge commit | Delivered scope | Evidence |
|---|---|---|---|
| [#198](https://github.com/AzizIo/Vstore/pull/198) | `96d7d7ac0cf3ff2589a0e1f50a3196c8603235af` | Lockfile/dependency CI hardening, npm/pip audits, production Compose validation, local PostgreSQL backup and isolated restore-drill scripts, dynamic Alembic head check | Original PR CI: [Backend](https://github.com/AzizIo/Vstore/actions/runs/43643690794), [Frontend](https://github.com/AzizIo/Vstore/actions/runs/43643690753), [Compose](https://github.com/AzizIo/Vstore/actions/runs/43643690738). Push-to-main verification: [Backend](https://github.com/AzizIo/Vstore/actions/runs/43647498512), [Frontend](https://github.com/AzizIo/Vstore/actions/runs/43647498549), [Compose](https://github.com/AzizIo/Vstore/actions/runs/43647498517). |
| [#204](https://github.com/AzizIo/Vstore/pull/204) | `1ccaaeb2a2f955f029276b22b111580c02ccbc11` | Production operations runbook and static infrastructure guardrails | [Guardrails CI](https://github.com/AzizIo/Vstore/actions/runs/43643388858); [push CI](https://github.com/AzizIo/Vstore/actions/runs/43647523603). |
| [#211](https://github.com/AzizIo/Vstore/pull/211) | `d93056531373fa178a1047cf187eaa2fb0b7b8f9` | 16 Prometheus alert rules, provider-neutral configs, safe endpoint probes, alert-state simulation, native `promtool`/`amtool` validators with pinned and SHA-256-verified releases | [Monitoring PR CI](https://github.com/AzizIo/Vstore/actions/runs/43647093265); [push CI](https://github.com/AzizIo/Vstore/actions/runs/43647552312). |
| [#210](https://github.com/AzizIo/Vstore/pull/210) | `33d94628819cb3b3d4c61565e4af06c95b2a53c8` | Frozen TON escrow ABI provenance and fail-closed artifact/build verifier; generated code/BOC digest checks | [TON artifact CI](https://github.com/AzizIo/Vstore/actions/runs/43646458754); [push CI](https://github.com/AzizIo/Vstore/actions/runs/43647588989). Does not complete escrow lifecycle or make signing safe. |
| [#209](https://github.com/AzizIo/Vstore/pull/209), incorporating [#203](https://github.com/AzizIo/Vstore/pull/203) | `ef3d280f52cd03a1c6ead4e60527b4fd0badd078` | Payment snapshot/transaction immutability, TRUNCATE guards, PostgreSQL refund row DELETE guard, downgrade protection, retained evidence fixtures and isolated migration history tests | Combined head `7447e052ee896567a455a17eadea3ab7f42b0267`: [Backend](https://github.com/AzizIo/Vstore/actions/runs/43647950625), [Frontend + API-backed E2E](https://github.com/AzizIo/Vstore/actions/runs/43647950616) — all jobs passed with `pip-audit`, `npm audit`, clean `npm ci`, migration upgrade, PostgreSQL tests, Playwright and API-backed checks. |

PR #203 is now closed/merged as part of the combined #209 merge; its ledger migration is in the same final history. No standalone payment PR remains open.

## 3. Current open PRs and parallel work

| PR / issue | State | Remaining acceptance |
|---|---|---|
| [#197 TON escrow](https://github.com/AzizIo/Vstore/pull/197) | Draft; not merged | ABI-backed backend adapter, full StateInit/address/BOC generation, durable idempotent wallet actions, independent finality proof, getter/trace reconciliation, PostgreSQL order-vs-escrow reservation concurrency, live valueless testnet lifecycle evidence and independent contract review. Keep signing disabled. |
| [#205 release checklist](https://github.com/AzizIo/Vstore/pull/205) | This audit update | Tracks merged baseline and all outstanding release gates. |
| [#201 Frontend/QA](https://github.com/AzizIo/Vstore/issues/201) | No dedicated reviewable implementation PR found in the current open PR inventory | Telegram initData trust-boundary review, UI payment-state review, TonConnect network guard and critical product E2E acceptance not independently delivered as a dedicated PR. |

Issue [#207](https://github.com/AzizIo/Vstore/issues/207) refund-evidence retention is implemented by merged #209. Issue [#199](https://github.com/AzizIo/Vstore/issues/199) broader payment-provider/seller settlement decisions remain open. Infrastructure issues [#200](https://github.com/AzizIo/Vstore/issues/200) and [#208](https://github.com/AzizIo/Vstore/issues/208) remain open for live owner acceptance.

## 4. Independent technical findings and limits

1. **Payment ledger:** migration `0015_payment_ledger_guards` protects financial snapshots and TRUNCATE operations; migration `0016_refund_evidence` blocks row-level DELETE from `payment_refunds`. Lifecycle/lease/reconciliation fields remain mutable by design. Test fixtures never delete ledger rows or disable guards; they retain rows in disposable CI databases, move unfinished test refunds to `manual_review`, cancel fixture orders and release listings. Migration downgrade/legacy-upgrade tests run in uniquely named disposable PostgreSQL databases.
2. **Payment-provider and policy gates:** repository CI does not establish seller legal entity/status, seller/buyer countries, merchant of record, underwriting, settlement model or written Telegram policy classification. There is no live charge, refund, payout or seller settlement evidence. Keep public paid checkout disabled while [Issue #155](https://github.com/AzizIo/Vstore/issues/155) has no written Telegram ruling.
3. **Backup/restore:** merged scripts provide a local/manual PostgreSQL dump and disposable restore drill. They do not implement encrypted off-host upload, retention/rotation, scheduled backups, remote metadata monitoring or a real production-like VPS restore. Their CI is not evidence of recovery from the live service.
4. **Monitoring:** merged templates contain 16 alert rules and native config validation. No private production exporters/adapters, approved secret-backed receiver or real firing/resolved notification delivery has been configured or tested. Container/restart metrics do not prove the bot polling loop is processing updates.
5. **VPS hardening:** merged runbook/static guardrails do not prove live firewall, SSH, TLS, reverse proxy, volume, disk, secret-store or production network state. No live VPS inspection was performed.
6. **TON escrow:** the merged #210 verifier makes artifact provenance reproducible and checks code/BOC digests. It does not implement the remaining #197 adapter, address derivation/complete StateInit, finality, wallet action idempotency, live testnet lifecycle or independent security audit. No mainnet signing or real escrow.

## 5. Release gate checklist

| Gate | Status | Evidence / remaining work |
|---|---|---|
| Repository backend/frontend hardening | **PASS on merged PRs** | #198 and #209 CI success on exact PR heads; a fresh main push validation for #209 is tracked below. |
| Python dependency audit | **PASS** | `pip-audit` succeeded on final combined PR #209 head. |
| Frontend dependency/install audit | **PASS** | `npm ci`, committed lockfile validation and `npm audit` succeeded on final combined PR #209 head. |
| PostgreSQL migration/payment evidence | **PASS in CI** | Combined Backend CI passed migration upgrade, PostgreSQL guards, refund retention and full backend tests on #209 head. |
| Frontend/API journeys | **PASS in CI** | Frontend Playwright and separate API-backed Playwright/PostgreSQL/Redis journey passed on #209 head. |
| Main push validation after #209 merge | **PENDING at audit refresh** | [Backend](https://github.com/AzizIo/Vstore/actions/runs/43648129456) and [Frontend/API E2E](https://github.com/AzizIo/Vstore/actions/runs/43648129496) started on exact main SHA `ef3d280...`; refresh before any production decision. |
| Telegram Stars live test invoice/payment cycle | **NOT VERIFIED** | Dedicated test bot real invoice → pre-checkout → successful-payment round trip against disposable DB still needs explicit safe acceptance. |
| Written Telegram policy ruling | **BLOCKED** | Issue #155 has no written response. Public paid checkout stays disabled. |
| Provider/seller settlement/legal model | **BLOCKED** | Legal entity, jurisdictions, merchant-of-record, seller payouts and provider underwriting facts unresolved. |
| TON escrow testnet acceptance | **BLOCKED** | PR #197 remains Draft; full lifecycle, finality, concurrency and independent review open. Mainnet signing remains disabled. |
| Encrypted off-site backup and real restore | **PARTIAL / NOT VERIFIED LIVE** | Need remote encryption/upload, retention, locking, monitoring and production-like restore drill. |
| External monitoring and real alerts | **PARTIAL / NOT VERIFIED LIVE** | Need private exporters, bot processing heartbeat, approved secret receiver and actual firing/resolved delivery cycle. |
| VPS TLS/firewall/volumes/reverse proxy | **NOT VERIFIED LIVE** | Owner-authorized inspection required. |
| Production migration/deployment/secrets | **NOT RUN** | No production operations were performed. |

## 6. Required owner actions before production

1. Obtain and preserve written Telegram guidance for the exact TON NFT secondary-sale flow in Issue #155.
2. Confirm legal entity, country coverage, merchant-of-record, refund/dispute obligations and a permitted provider/settlement model.
3. Perform a dedicated real Telegram test-bot invoice/payment acceptance using valueless/test accounts and disposable storage.
4. Configure encrypted off-site backup storage, retention/rotation, collision-safe locking, alerting and complete a production-like restore drill.
5. Install private metrics exporters/adapters, prove bot polling/message-processing heartbeat, configure an approved secret-backed Alertmanager receiver and verify a real alert/recovery cycle.
6. Inspect VPS firewall, SSH, TLS, reverse proxy, storage volumes, database/Redis isolation and permissions with explicit owner authorization.
7. Finish #197 testnet adapter, state/address, idempotency, finality and concurrency work; obtain independent TON/Tolk contract review before any signing enablement.
8. Deliver the dedicated #201 frontend/QA review and test evidence if the product still requires that scope.

## 7. Safety and decision

**BLOCKED — NOT READY FOR PRODUCTION.** Repository hardening and CI work have been merged, including monitoring templates, payment ledger protections and TON artifact verification. That does not constitute live operational, legal/platform, testnet or production acceptance.

No production credentials, VPS, DNS, production database, Telegram/payment account or signing keys were accessed. No deployment, production migration, live payment/refund, seller payout, TON transfer or mainnet signing was performed.
