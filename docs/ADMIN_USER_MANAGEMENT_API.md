# Admin User Management API

Status: implemented for the closed Beta admin dashboard. Routes are mounted under `/api/admin` and extend the existing protected `/admin` workspace; they do not create a second admin surface.

## Authorization

Every route in this feature depends on the existing `require_admin` dependency. The server validates the bearer session against the persisted user and then checks `ADMIN_TELEGRAM_IDS` on the server. No client-supplied Telegram ID, role or actor ID is accepted as authority.

The routes return bounded Pydantic DTOs, not complete SQLAlchemy models. User-facing data includes name, username, Telegram ID, registration date, block status and aggregate counts. Admin user details include verified wallet addresses shortened server-side. No private keys, seed phrases, session tokens or wallet credentials are returned.

## Endpoints

| Method | Path | Description |
|---|---|---|
| GET | `/overview` | Aggregated user/listing/order counts plus recent registrations and platform events |
| GET | `/users` | Paginated users; validated username/Telegram ID search; blocked filter; sort by registration, listing count or deal count |
| GET | `/users/{user_id}` | Basic user record, aggregates and shortened verified wallet addresses |
| GET | `/users/{user_id}/listings` | Paginated listings and statuses for the selected user |
| GET | `/users/{user_id}/orders` | Paginated orders, participant role and latest delivery-attempt status |
| GET | `/users/{user_id}/audit` | Relevant user-access decisions and listing moderation history |
| GET | `/orders` | Read-only deals list, UUID search and order-status filter |
| GET | `/audit-log` | Unified pagination/filtering across listing-moderation and user-access audit logs |
| POST | `/users/{user_id}/block` | Requires a reason and `Idempotency-Key`; sets the account restriction |
| POST | `/users/{user_id}/unblock` | Requires a reason and `Idempotency-Key`; clears the account restriction |

User and order list endpoints use a page size of 1–100 and bounded offset. User searches are validated and limited in length. Read endpoints return an empty page rather than requiring the entire user collection to be loaded.

## Block / unblock behavior

Access-changing endpoints lock the target user row, prohibit self-actions and protect accounts whose Telegram IDs are present in the admin allowlist. The operation and its audit record are written in the same transaction. A repeated key and matching request returns the original result; reusing the key for a different action, target or reason returns HTTP 409.

The new `admin_user_audit_log` table is separate from the existing listing moderation audit. It stores only the previous/current `is_blocked` value, decision reason, actor/target IDs and request metadata. A unique constraint prevents duplicate actor keys. PostgreSQL UPDATE, DELETE and TRUNCATE triggers enforce append-only behavior. Downgrade is blocked while records exist to preserve the audit trail.

## Blocked accounts

Blocked users can authenticate into the Mini App to see the restriction message and read their profile, wallets, verified inventory, own listings and existing order/delivery state. The standard authenticated dependency rejects blocked accounts for write-capable endpoints. Existing order workflow endpoints use a separate allow-blocked identity dependency but still validate the caller's ownership/participation and order state in the service; creating a new order has a separate explicit block check. This does not mark reservations as paid and adds no refund, payout or manual completion path.

## Overview semantics

All metrics are queried from PostgreSQL. “Not blocked” means the persisted user restriction flag is false; it does not imply online presence. “Deals in progress” counts existing order statuses `reserved`, `awaiting_transfer`, and `observing_transfer`; “completed” uses `OrderStatus.COMPLETED`. Delivery status is obtained from the latest stored delivery attempt, not inferred from a reservation or payment.

## Migration and verification

Migration `0014_admin_user_management` extends `0013_payment_refund_workflow`. It adds the dedicated audit table and the chronology indexes used by registration/order views. The admin integration test creates a disposable PostgreSQL database to avoid leaving audit records in the shared test DB; it tests repeated actions, validation, safe DTO output and audit immutability. No production migration has been run.
