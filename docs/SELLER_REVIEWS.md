# Order-verified seller reviews

VILTARA SHOP exposes seller reputation from immutable buyer reviews tied to completed NFT orders.

## Eligibility

A review can be created only when all of these conditions hold on the backend:

- the authenticated user is the persisted buyer of the order;
- the order status is `completed`;
- an order delivery attempt is `verified` and contains the observer-confirmed transaction hash and verification timestamp;
- the order has no existing review.

The seller is always derived from the order. The create request cannot select or replace the seller. Reserved, awaiting-transfer, observing-transfer, cancelled, expired, manually reviewed, foreign, and missing orders are not reviewable. Review records are immutable and one order can produce at most one review.

## Public API

`GET /api/reviews/sellers/{seller_id}?limit=20&offset=0` returns a bounded, stable newest-first page. It includes the backend-computed average, count, five-bucket rating distribution, and review cards. Public cards contain only an opaque review ID, rating, normalized comment, and creation time. They do not contain Telegram IDs, usernames, wallet addresses, email addresses, or author names.

`GET /api/reviews/eligibility?order_id={id}` requires authentication and returns only an opaque eligible/already-reviewed result. It does not disclose why another user's order is unavailable.

`POST /api/reviews` requires authentication and accepts:

```json
{"order_id":"uuid","rating":5,"comment":"Great transfer"}
```

Comments are optional, whitespace-normalized, and bounded to two thousand characters. A successful response confirms that the review is immutable.

## Product boundaries

The rating is deliberately explainable: average score, review count, and distribution of verified reviews. The feature does not create a composite trust score, payment, escrow, custody, refund, commission, payout, or buyer-protection state. Reservation remains distinct from payment, and existing order lifecycle and delivery observer rules are unchanged.

## Verification

The backend test suite covers authorization, evidence requirements, constraints, uniqueness, aggregate isolation, and pagination. The frontend tests cover public states, completed-order eligibility, form validation, retries, and duplicate-submit protection. API-backed Playwright uses only the disposable test PostgreSQL/Redis stack and loopback TON provider documented in [API_BACKED_E2E.md](API_BACKED_E2E.md).
