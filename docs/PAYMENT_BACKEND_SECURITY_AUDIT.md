# Payment backend security audit — Issue #199

**Baseline:** `main` at `2138d2b69c86507f05cec7ee768b4cc11ad00e47`  
**Scope:** backend payment/refund evidence only. This is an implementation audit, not legal advice or approval for live sales.

## Current payment flow (source map)

| Stage | Current implementation | Trust boundary |
|---|---|---|
| Order reservation | `backend/app/orders/service.py`; `Order` snapshots buyer, seller, amount and currency | Reservation is not payment; order state remains the delivery lifecycle |
| Stars intent | `backend/app/orders/payment_service.py:create_stars_payment_intent`; `backend/app/db/payments.py:PaymentIntent` | Locks order, checks buyer ownership, XTR currency, amount and expiry; unique order and invoice payload |
| Invoice transport | `backend/app/orders/telegram_stars_test.py`; `backend/app/payments_bot_handlers.py` | Dedicated Telegram test bot only; no production invoice transport |
| Pre-checkout | `validate_stars_pre_checkout` | Compares persisted invoice, payer, amount, currency and live order state |
| Successful payment | `record_stars_success` | Persists charge evidence under order → intent locks; first valid charge marks the intent paid; extra, late or mismatched charges enter refund-pending |
| Event journal | `PaymentEvent` in `backend/app/db/payments.py`; migration `0012_telegram_stars_payments` | Unique provider/event key and PostgreSQL append-only UPDATE/DELETE trigger |
| Refund queue | `queue_stars_refund`; `PaymentRefund`; migration `0013_payment_refund_workflow` | One durable refund job per captured charge; unique transaction key |
| Refund execution | `backend/app/orders/refund_worker.py` | PostgreSQL SKIP LOCKED claims and leases; provider I/O outside DB transactions; only dedicated test Bot API namespace |
| Refund reconciliation | `TelegramStarsRefundProvider.lookup_refund` | Unknown/incomplete transaction history never proves non-refund and never authorizes a blind second refund |
| Delivery | `backend/app/orders/service.py:prepare_delivery` and TON observer | Payment confirmation does not complete or prove NFT delivery |

## Security observations and changes in this branch

1. Payment intent and transaction rows contain mutable lifecycle fields, but their identifying financial evidence must not be editable after capture.
2. Refund workflow rows are durable audit/reconciliation evidence, not disposable queue entries. They may transition through queued/processing/retry/reconciliation/succeeded/manual-review states, but ordinary row-level DELETE is forbidden by PostgreSQL. Tests must retain ledger evidence and FK parents for the lifetime of a disposable test database; they mark remaining test refund jobs for manual review and let CI destroy the disposable database at job teardown. No fixture disables append-only triggers or deletes payment evidence.
3. Migration `0015_payment_ledger_guards` adds PostgreSQL guards:
   - intent order/provider/amount/currency/payer/payload/expiry/creation snapshot cannot change;
   - transaction intent/provider/charge IDs/amount/currency/payer/capture timestamp/creation snapshot cannot change;
   - TRUNCATE triggers are installed for intents, transactions, events and refund workflow rows. These triggers are separate from row-level DELETE policy: payment events are append-only; transaction/intent deletion is constrained when referenced by dependent rows; ordinary DELETE of a payment_refunds workflow row is not blocked by this migration and remains an explicit retention-policy decision;
   - legitimate status, lease, retry and reconciliation fields remain mutable through the state machine.
4. Migration `0015_payment_ledger_guards` is followed by `0016_refund_evidence_delete_guard`, which installs `trg_payment_refunds_no_delete` and a dedicated rejecting trigger function. Its downgrade drops only the trigger/function and never deletes or rewrites existing refund records; as with any downgrade, removal of the guard weakens future protection and requires an explicit maintenance decision.

## Webhook / replay boundary

The current Stars test runner uses Telegram long polling through the dedicated test Bot API namespace; there is no public payment webhook route in this application. Therefore webhook signature verification is not an active request path today. Do not invent a webhook endpoint merely to claim signature coverage.

If a webhook transport is introduced later, it must:
- require Telegram's `X-Telegram-Bot-Api-Secret-Token` and compare it in constant time;
- reject absent or incorrect secrets before parsing/processing the update;
- bind the successful payment to the persisted invoice payload, order, payer, exact XTR amount and currency;
- use Telegram update identity plus the unique Telegram/provider charge IDs for replay protection;
- never log the bot token, webhook secret, raw update, invoice payload or other bearer-like values.

The current polling path uses the dedicated test bot token as transport authentication. The ledger deduplicates provider events/charges with unique database constraints. No production bot token or webhook secret is introduced.

## Provider selection gate — not approved

The repository describes a peer-to-peer marketplace for TEP-62 TON NFTs. It does not establish the seller's legal entity/status, seller country, buyer country distribution, or the jurisdictions in which sales and payouts would be offered. Those facts are mandatory before selecting a live provider.

| Candidate | Fit / constraints | Current decision |
|---|---|---|
| Telegram Stars | The only in-app digital-goods checkout candidate in the existing ADR. Stars are not segregated seller balances; NFT resale classification, irreversible delivery and dispute treatment require written platform/legal review. | Keep the existing dedicated test-only integration. No live checkout. |
| External card/PSP checkout | Could be evaluated for a separately permitted website flow; NFT/marketplace category acceptance, country coverage, chargebacks, refunds, KYC/AML, marketplace/split settlement and reserve requirements are provider-specific. | Do not select until legal entity, countries and provider underwriting are known. |
| TON / on-chain escrow | Not a card/payment-provider substitute and must not bypass Telegram's in-app Stars requirement. Custody, contract security, irreversible transfers and jurisdictional treatment remain separate gates. | Testnet-only research; no mainnet signing or production escrow. |

### Information required from the owner

- Seller's country of establishment, legal entity type and registration/tax status.
- Countries where sellers may register and buyers may purchase.
- Whether all goods are TEP-62 NFTs, whether any digital services or other goods are sold, and whether Telegram checkout is the only purchase surface.
- Whether the intended flow is in-app Stars, external website checkout, or both.
- Who is merchant of record, who receives provider funds, and whether the platform intends to split/hold/settle seller proceeds.
- Required settlement currencies, refund window, chargeback/dispute handling and payout countries.
- Written platform/legal review of peer-to-peer NFT resale and irreversible delivery.

Until those answers and written reviews exist, provider selection, production credentials, live charges/refunds, seller payouts and custody remain disabled.

## Tests and operational verification

- Existing PostgreSQL integration coverage is in `backend/tests/test_payment_core_integration.py`, `backend/tests/test_payment_refund_worker.py`, and `backend/tests/test_payment_ledger_guards.py`; it must use a disposable local test-named PostgreSQL database that is destroyed after the run, not a shared/staging/production database.
- Existing tests cover order/payment separation, duplicate charges, late/mismatched payment evidence, append-only event mutation, refund worker leases, ambiguous provider outcomes and reconciliation.
- The PostgreSQL guard integration test verifies the named TRUNCATE trigger exists in `pg_trigger` for all four target tables and verifies the refund DELETE trigger exists. It asserts DELETE/TRUNCATE rejection while a legitimate transaction lifecycle update remains allowed. A rejection caused only by an unrelated FK is not sufficient evidence that a trigger is installed.
- Do not report PostgreSQL integration tests as run locally unless an isolated disposable PostgreSQL service was actually available.
- No production credentials, production database, real payment, refund request, payout or deployment is part of this work.
