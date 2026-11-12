# Issue #44: 1-vs-2 inventory discrepancy investigation

## Scope

Trace `GET /api/assets/me`, `POST /api/assets/me/sync`, the guarded asset upsert, and `frontend/src/inventory/MyInventory.tsx`. Changes are limited to tests, diagnostic tooling, and this report; no TON provider metadata or frontend pagination behavior is changed.

## Findings from the current main implementation

- `POST /api/assets/me/sync` is a full reconciliation. It scans every provider page for the selected verified wallet, rechecks existing assets against the account's other verified wallets, and reports `verified_count` for the reconciliation result.
- `GET /api/assets/me` is not a database inventory count. Each request fetches only the requested provider page, deduplicates addresses within that page, and calls the verifier for each candidate against the selected verified wallet. Only candidates with a successful current-owner verification are passed to the upsert.
- The GET response contains only rows returned by the guarded upsert. If an upsert is skipped because the asset has an active/reserved listing, that candidate is not included in the returned page.
- `MyInventory.tsx` renders the `items` array returned by `fetchMyInventory`; it merges subsequent pages by database asset ID. It does not fabricate NFT cards from a sync count or client-side wallet data.
- Pagination metadata (`next_offset` / `has_more`) comes from the provider page, while rendered item count is the number of candidates that pass verification and persistence. Therefore these numbers are not expected to be equal. A sync-wide count, a single GET page, and a SQL count of verified rows are different measurements.
- Because the provider is queried again for each GET page and each sync, these requests are not a shared snapshot. Provider index changes between requests can also affect page composition.

## Read-only diagnostic scenario

New command: `backend/scripts/diagnose_inventory_discrepancy.py`. Run from `backend/` in the same controlled environment as the application, with its usual `.env` and dependencies installed:

```bash
python -m scripts.diagnose_inventory_discrepancy --wallet-id <VERIFIED_WALLET_UUID> --limit 24 --offset 0 > inventory-diagnostic.json
```

The command reads the configured TON Center provider and PostgreSQL database. It checks that the selected wallet is verified and that its network matches the configured provider; then records the timestamp, provider cursor/page size, redacted address suffixes, verifier status for each candidate, matching DB rows filtered by network and normalized item address, and any active/reserved listing statuses. It prints the wallet UUID and network, but never the full wallet or NFT address, API key, or bearer token.

**It is intentionally read-only:** it does not call the API GET endpoint (which may upsert) or the sync endpoint (which mutates inventory), and it does not attempt an upsert. Accordingly, its `upsert` field is explicitly `not_executed_read_only`; an active/reserved listing is evidence of a possible upsert guard, not proof that an upsert was skipped during the historic request.

To complete one incident evidence bundle, capture the browser/API response separately with UTC timestamp and request query parameters, and compare its item-address suffixes with this JSON. Do not run a sync merely to collect evidence. Provider and DB observations are not an atomic snapshot, so note the timestamps and avoid claiming a historical cause unless the evidence lines up.

## Discrepancy status

The historic screenshot and a separate database diagnostic are insufficient to identify which NFT caused the observed 2-card/1-row discrepancy. No timestamped provider response, request logs, selected wallet ID/network, per-item verifier results, guarded-upsert results, API response, or matching DB snapshot was included with the report. The implementation explains several legitimate count differences, but does not prove which one caused that specific observation. The new diagnostic can collect fresh evidence in the target environment; it cannot recreate missing historical evidence.

## Regression coverage

Added `test_inventory_page_returns_only_items_verified_for_selected_wallet` in `backend/tests/test_assets_routes.py`. Its deterministic provider returns two candidates; the verifier confirms current ownership of one and reports an owner mismatch for the other. The assertion checks that the GET response contains only the verified item and that both candidates were checked against the selected wallet.

## Validation

The PR head previously reported passing Backend CI (Ruff + pytest) and Frontend CI (Vitest, production build, frontend Playwright E2E, API-backed E2E). The new diagnostic script has not yet been executed in a live environment because it requires the application's configured database and TON Center access. Run Ruff and the backend test suite again after this added script.

## Evidence interpretation

- Provider candidate count: rows returned by TON Center for the selected wallet and exact offset; indexed data, not a chain snapshot.
- Verifier status: result of fetching the item and checking its current owner against the selected wallet.
- DB rows: persisted NFT rows for the same network and normalized address, regardless of whether that row currently belongs to the selected user's account.
- Open listing statuses: active/reserved listings that can make the guarded GET upsert return no row.
- API `items` count: items returned to the client by that particular request after verification and upsert; not a whole-wallet count.
- Sync `verified_count`: result of a full reconciliation, not the same measurement as a single GET page.

Do not use an unfiltered TON Center query or an old screenshot as ownership evidence.
