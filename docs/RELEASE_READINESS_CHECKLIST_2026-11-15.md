# VILTARA SHOP — release lead checklist (2026-11-15)

**Decision: BLOCKED — not ready for production or live escrow.** This document records repository evidence only. It does not claim live VPS, Telegram, payment-provider, TON testnet or independent security acceptance.

## 1. Current baseline

- Repository: `AzizIo/Vstore`
- Default branch: `main`
- Current main SHA: `19d50682441c06faa80622d837c4762f2d23cec1`
- Latest code-bearing integration SHA: `7c09523c44bf0193553bd5ae1ef38b661b7a650d`
- The latest commit after that integration is documentation-only (`19d5068`).
- Open PR inventory checked on 2026-11-15: only Draft PR #197 is open.
- Open implementation/release issues include #199, #200, #201, #202, #208, #213 and #214. Their kickoff comments exist, but no GitHub assignees or agent-authored progress reports were present at audit time.
- No production credentials, VPS/SSH, DNS, production DB, Telegram API, payment accounts or TON signing keys were accessed.

## 2. Merged implementation and exact evidence

| PR | Scope now in main | Evidence / boundary |
|---|---|---|
| #198 | Dependency/CI hardening, Compose validation, local PostgreSQL backup and isolated restore-drill scripts, dynamic Alembic head check | Earlier PR and main-push checks recorded in the prior release audit. Does not prove encrypted off-site backup or live restore. |
| #204 | Production operations runbook and static infrastructure guardrails | Earlier Guardrails CI and push CI recorded in the prior release audit. Does not prove live VPS configuration. |
| #209 (incorporating #203) | Payment ledger snapshot/transaction immutability, TRUNCATE/DELETE guards, downgrade protection and isolated migration evidence | Exact combined-head Backend and Frontend/API-backed E2E passed. No live provider or seller payouts. |
| #211 | Provider-neutral Prometheus/Blackbox/Alertmanager templates, 16 alert rules, read-only probes, simulation and native config validation | Monitoring CI passed; no live receiver, private exporters or real alert delivery. |
| #215 | Durable escrow wallet-action records, idempotency/replay conflict protection, reservation serialization, observer evidence gates and PostgreSQL race tests | Backend CI passed (715 tests, Ruff, pip-audit and migration drill); Frontend CI passed. No cryptographic TON finality provider or live broadcaster. |
| #216 | TON escrow lifecycle hardening: terminal bounce protection and deadline enforcement with emulator regressions | TON Contract CI passed; 25 emulator tests passed on the merged contract track. Not an independent audit or live testnet acceptance. |
| #218 | Pinned testnet ABI/BOC, reproducible Acton/Tolk artifact, deterministic StateInit/address derivation and unsigned TON Connect message construction | Exact PR-head Backend CI, Frontend CI/API-backed E2E and TON Contract CI passed. This is not an enabled payment flow. |
| #219 | Escrow ABI/API documentation synchronization | Documentation-only; no additional runtime capability. |

The latest code-bearing main push at `7c09523c44bf0193553bd5ae1ef38b661b7a650d` has successful exact-SHA checks:
- Backend CI: [run 43712693611](https://github.com/AzizIo/Vstore/actions/runs/43712693611)
- Frontend CI: [run 43712693656](https://github.com/AzizIo/Vstore/actions/runs/43712693656)
- TON Escrow Contract CI: [run 43712693618](https://github.com/AzizIo/Vstore/actions/runs/43712693618)

These runs validate code at `7c09523`; they are not checks on the subsequent docs-only `19d5068` commit and do not establish production readiness.

## 3. Current open PR and parallel work

| Item | State observed | Remaining work |
|---|---|---|
| [#197 TON escrow acceptance](https://github.com/AzizIo/Vstore/pull/197) | Open Draft; explicitly NOT testnet-ready or production-ready | Complete immutable deployment snapshot; activate pinned adapter only with replay-safe payload persistence; cryptographic testnet finality provider; finalized trace/getter reconciliation; restartable action/recovery workers; PostgreSQL Order-vs-escrow concurrency evidence; valueless live testnet lifecycle; independent qualified TON/Tolk audit. |
| [#199 payment backend](https://github.com/AzizIo/Vstore/issues/199) | Open; kickoff comment present, no assignee or agent progress report observed | Finish safe payment/provider audit. Do not enable live charges, payouts or seller settlement. |
| [#200 production infrastructure](https://github.com/AzizIo/Vstore/issues/200) | Open; kickoff comment present, no assignee or agent progress report observed | Off-site encrypted backup/restore design, VPS runbook and owner-authorized live acceptance. |
| [#201 frontend / Mini App QA](https://github.com/AzizIo/Vstore/issues/201) | Open; kickoff comment present, no assignee or agent progress report observed | Independent auth/session, payment-state, wallet/network and critical E2E review. |
| [#208 monitoring](https://github.com/AzizIo/Vstore/issues/208) | Open; templates merged, live acceptance outstanding | Private exporters, bot processing heartbeat, approved secret-backed receiver and verified firing/resolved delivery. |
| [#213 backend escrow](https://github.com/AzizIo/Vstore/issues/213) | Open; implementation substantially merged via #215 | Remaining provider/finality/action worker/reconciliation and complete immutable snapshot requirements must be tracked against #197. |
| [#214 contract security](https://github.com/AzizIo/Vstore/issues/214) | Open; implementation substantially merged via #216 | Full terminal financial/NFT/reserve invariant matrix, signed end-to-end settlement fixture, independent qualified audit and owner-approved valueless testnet evidence. |
| [#202 release candidate audit](https://github.com/AzizIo/Vstore/issues/202) | Open | Consolidate evidence, findings and explicit owner gates; do not mark release complete while any critical gate remains open. |

## 4. Technical and operational blockers

1. **TON escrow is not an executable payment service.** Backend route remains fail-closed; unsigned payload construction is not signing or broadcast. No configured cryptographic finality provider independently proves masterchain/shard inclusion and finality. Indexer-only status is insufficient.
2. **Immutable deal snapshot is incomplete.** Persist all oracle/resolver public keys, reserve/refund/transfer economics, query IDs, protocol/network identifiers and exact deployment terms before preparing a transaction.
3. **Payload/action lifecycle is incomplete.** Persist the exact unsigned payload/BOC and bind it to durable idempotent actions; provide restartable workers and safe recovery without repeating settlement.
4. **Chain reconciliation is incomplete.** Reconcile finalized transaction traces and all required contract getters before changing deal state; retain NFT ownership and principal/reserve invariants for every terminal path.
5. **Independent contract review is missing.** Internal code review and emulator tests are not an independent qualified TON/Tolk security audit.
6. **Payment policy and settlement model are unresolved.** No written Telegram ruling for the exact NFT resale flow, approved merchant-of-record/provider model, seller jurisdiction/underwriting or real settlement/refund evidence.
7. **Stars remains test-only.** The isolated test harness is not public checkout. A real test-bot invoice → pre-checkout → successful-payment round trip and refund acceptance still require controlled owner-led verification.
8. **Backup/restore is partial.** Local/manual PostgreSQL backup and disposable restore scripts do not establish encrypted off-host upload, retention/rotation, scheduled execution, remote monitoring or production-like restore.
9. **Monitoring is partial.** Templates and alert simulation do not prove private exporters, bot processing heartbeat or actual delivery to an approved external receiver.
10. **VPS and production cutover are unverified.** Firewall, SSH, TLS, reverse proxy, volumes, database/Redis exposure, secret storage and live migration/restore state require owner-authorized inspection.
11. **Live wallet/NFT acceptance remains separate.** CI and local fixtures do not prove Telegram WebView, BotFather manifest, Tonkeeper, real network switching or live NFT delivery acceptance.

## 5. Release gates

| Gate | Status | Required evidence |
|---|---|---|
| Backend/frontend/contract repository CI | **PASS on code-bearing main SHA 7c09523** | Exact-SHA Backend, Frontend and TON Contract CI runs listed above. |
| Python and npm dependency audit | **PASS in recorded CI** | pip-audit/npm audit and lockfile checks on merged implementation heads. |
| PostgreSQL migration and concurrency coverage | **PASS for merged tested scope; escrow acceptance remains open** | Migration upgrade/downgrade drills and Order-vs-escrow race tests on #215. |
| Frontend/API-backed E2E | **PASS in recorded CI** | Exact PR #218 frontend/API-backed E2E checks. |
| TON artifact reproducibility | **PASS for pinned testnet artifact** | ABI/BOC digests, Acton build and deterministic StateInit/address checks. |
| TON finality provider and restartable live action lifecycle | **BLOCKED** | Independent cryptographic inclusion/finality proof, worker/recovery and finalized trace/getter reconciliation. |
| Full contract adversarial lifecycle coverage | **PARTIAL / BLOCKED** | Full signed settlement/refund, dispute, expiry, bounce/action-failure and principal/NFT/reserve invariant matrix. |
| Independent TON/Tolk audit | **BLOCKED** | Written report by qualified reviewer independent of implementation. |
| Valueless TON testnet lifecycle | **NOT RUN / OWNER-GATED** | Explicit owner approval, disposable wallets/assets and transaction/trace/getter/ownership evidence. |
| Telegram Stars live test cycle | **NOT VERIFIED** | Dedicated test bot and disposable DB invoice/pre-checkout/payment/refund acceptance. |
| Telegram policy and legal/provider model | **BLOCKED** | Written platform guidance and approved legal/provider/settlement decision. |
| Encrypted off-site backup and real restore | **PARTIAL / NOT VERIFIED LIVE** | Encryption, remote upload, retention, lock/monitoring and production-like restore drill. |
| Monitoring and real alerts | **PARTIAL / NOT VERIFIED LIVE** | Private exporters, bot processing heartbeat and real firing/resolved receiver delivery. |
| VPS hardening and production cutover | **NOT VERIFIED LIVE** | Owner-authorized inspection and reviewed deployment/rollback evidence. |
| Production migration/deployment/secrets | **NOT RUN** | No production operation performed or approved. |

## 6. Required owner decisions and approvals

- Obtain and preserve written Telegram guidance for the exact TON NFT secondary-sale flow (Issue #155).
- Confirm legal entity, supported countries, merchant-of-record, refund/dispute obligations and an approved provider/settlement model.
- Authorize a controlled Telegram test-bot invoice/payment/refund acceptance using test accounts and disposable storage.
- Approve disposable TON testnet wallets and valueless NFT lifecycle testing only after the contract/security prerequisites are satisfied.
- Arrange an independent qualified TON/Tolk reviewer; internal self-review is not sufficient.
- Authorize any live VPS/DNS/production database inspection separately. No production credentials or private keys should be shared in chat or committed.
- Approve production cutover, migrations and secret configuration only after backup/restore and rollback evidence is reviewed.

## 7. Safety decision

**BLOCKED — NOT READY FOR PRODUCTION, LIVE PAYMENTS OR LIVE ESCROW.**

The repository has a substantially stronger marketplace, payment-ledger safety, monitoring-template and TON artifact baseline. The merged escrow work currently supports reproducible unsigned message construction, not live settlement. Keep production checkout, custody, automated payouts, mainnet signing and real-value escrow disabled.

No production credentials, VPS, DNS, production database, Telegram/payment account or signing keys were accessed. No production deployment/migration, live payment/refund, seller payout, TON transfer or mainnet signing was performed.
