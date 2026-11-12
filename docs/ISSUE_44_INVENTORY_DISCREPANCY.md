# Issue #44: 1-vs-2 inventory discrepancy investigation

## Scope

Trace `GET /api/assets/me`, `POST /api/assets/me/sync`, the guarded asset upsert, and `frontend/src/inventory/MyInventory.tsx`. This investigation does not modify the TON provider or metadata handling.

## Findings from the current main implementation

- `POST /api/assets/me/sync` is a full reconciliation. It scans every provider page for the selected verified wallet, rechecks existing assets against the account's other verified wallets, and reports `verified_count` for the reconciliation result.
- `GET /api/assets/me` is not a database inventory count. Each request fetches only the requested provider page, deduplicates addresses within that page, and calls the verifier for each candidate against the selected verified wallet. Only candidates with a successful current-owner verification are passed to the upsert.
- The GET response contains only rows returned by the guarded upsert. If an upsert is skipped because the asset has an active/reserved listing, that candidate is not included in the returned page.
- `MyInventory.tsx` renders the `items` array returned by `fetchMyInventory`; it merges subsequent pages by database asset ID. It does not fabricate NFT cards from a sync count or client-side wallet data.
- Pagination metadata (`next_offset` / `has_more`) comes from the provider page, while rendered item count is the number of candidates that pass verification and persistence. Therefore these numbers are not expected to be equal. A sync-wide count, a single GET page, and a SQL count of verified rows are different measurements.
- Because the provider is queried again for each GET page and each sync, these requests are not a shared snapshot. Provider index changes between requests can also affect page composition.

## Discrepancy status

The historic screenshot and a separate database diagnostic are insufficient to identify which NFT caused the observed 2-card/1-row discrepancy. No timestamped provider response, request logs, selected wallet ID/network, or matching database snapshot was included with the report, so a definitive incident root cause cannot responsibly be claimed. The implementation explains several legitimate count differences, but does not prove that one of them caused that specific observation.

## Regression coverage

Added `test_inventory_page_returns_only_items_verified_for_selected_wallet` in `backend/tests/test_assets_routes.py`. Its deterministic provider returns two candidates; the verifier confirms current ownership of one and reports an owner mismatch for the other. The assertion checks that the GET response contains only the verified item and that both candidates were checked against the selected wallet.

## Test execution

Not run in this environment: the GitHub connector can read/write repository files but does not provide a checked-out runtime for executing pytest. The new test is committed to the investigation branch, but it must be run in the repository's backend test environment before calling it passing.

## Evidence needed to close the specific incident

Capture, from the same run: selected wallet ID and network, GET request query parameters, raw provider page addresses/cursor, verifier result per address, guarded-upsert result per verified candidate, GET response item addresses, and a database query filtered by network plus normalized item address. Do not use an unfiltered TON Center query or an old screenshot as ownership evidence.
