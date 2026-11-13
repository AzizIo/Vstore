# Admin Moderation & Audit Center

The moderation API is mounted under `/api/admin`. It uses the existing verified bearer session, then assigns the administrator role from the server-side `ADMIN_TELEGRAM_IDS` allowlist. The allowlist defaults to empty, which denies all admin access. For the current Docker Compose API service, add a JSON array of numeric Telegram user IDs to the root `.env`, for example `ADMIN_TELEGRAM_IDS=[123456789]`; do not commit real administrator IDs. The `api` service receives this file through Compose `env_file`. Open the separate moderation workspace at the Mini App origin plus `/admin`; the route checks the verified Telegram session and the API allowlist. Never send a role, actor ID, or Telegram ID in a moderation request.

## Endpoints

- `GET /api/admin/access` — returns whether the authenticated session is allowlisted.
- `GET /api/admin/moderation?limit=25&offset=0&status=pending_review` — bounded queue (limit 1–100, offset 0–10000); statuses are pending_review, active and suspended. Private drafts are not exposed to moderators. Each item includes an explainable status/verification reason.
- `POST /api/admin/listings/{id}/decision` — approve, reject, suspend or restore. Requires `Idempotency-Key` (8–128 characters), a reason code and a 5–500 character explanation.
- `GET /api/admin/audit` and `GET /api/admin/listings/{id}/audit` — bounded, stable audit history with optional target/action filters.

## State transitions and verification

A seller's publish request does not make a listing public. It performs a fresh ownership check and moves DRAFT → PENDING_REVIEW. Only the admin approval action can move PENDING_REVIEW → ACTIVE. Editing a pending submission returns it to DRAFT, so changed content must be resubmitted. The seller can withdraw a pending submission.

- Approve: pending_review → active. The API rechecks current TON NFT ownership against a verified seller wallet through the existing verifier, then locks and revalidates listing, wallet and asset before committing.
- Reject: pending_review → cancelled. This is an explicit terminal moderation decision, not a listing deletion.
- Suspend: active → suspended. Reserved, sold, cancelled and expired listings cannot be suspended.
- Restore: suspended → active only after the same fresh TON ownership verification and conflict checks used for safe publication.
- Other transitions are rejected with HTTP 409. The existing order lifecycle is unchanged; the catalogue only offers active listings.

## Audit guarantees

Each successful decision and its listing status update commit in the same database transaction. The unique actor/idempotency-key constraint prevents duplicate events; replaying the same key and payload returns the original event, while reusing it for a different decision returns 409. A PostgreSQL trigger rejects every UPDATE, DELETE or TRUNCATE against `moderation_audit_log`. Downgrade refuses to drop a populated log.

Audit snapshots contain only listing ID/status/title/price/currency, seller UUID, asset verification status and a boolean ownership-match signal. Telegram IDs, wallet/item addresses, credentials, tokens and provider payloads are not recorded. Audit reads and all decisions require the admin allowlist check on every request. Bearer authentication is header-based (not cookie-based), so browser ambient-cookie CSRF is not used; CORS remains governed by the existing configured origins.

## CI / local validation

Run backend checks with `cd backend && ruff check . && pytest`. Run frontend checks with `cd frontend && npm test && npm run build && npm run test:e2e`. The API-backed Playwright job uses the isolated CI-only PostgreSQL/Redis stack and a loopback TON provider fixture; it does not target production.
