# Telegram order notifications

## Runtime setup

1. Set `BOT_TOKEN` to the token issued by BotFather.
2. Set `TELEGRAM_MINI_APP_URL` to the direct link of the configured Mini App, for example
   `https://t.me/<bot_username>/<app_short_name>`.
3. Apply migrations with `alembic upgrade head`.
4. Start the API and the optional bot worker:

   ```bash
   docker compose up -d api
   docker compose --profile bot up -d bot
   ```

The bot container runs both aiogram polling and the outbox worker. API instances only enqueue
notification records; they never make a Telegram network request while committing an order.

## Events and recipients

| Lifecycle event | Buyer | Seller |
| --- | --- | --- |
| Order created / listing reserved | Confirmation | Reservation notice |
| Buyer cancellation | Cancellation notice | Cancellation notice |
| Automatic expiry | Expiry notice | Expiry notice |
| Delivery prepared / seller action required | Transfer intent is prepared; no delivery claim | Review and sign the exact transfer in your own wallet |
| Transfer reference submitted / observation started | Independent verification is in progress | Wait for backend verification; do not send another transfer |
| Transfer independently confirmed | Exact transfer verified by backend observer | Exact transfer verified by backend observer |
| Manual review / reconciliation required | Delivery is not confirmed; do not assume success | Delivery is not confirmed; do not submit another transfer |

Each outbox row snapshots the recipient Telegram ID and role. The unique deduplication key is
based on order, lifecycle event, and recipient. The order transition, order event, and outbox
rows are committed atomically.

Messages contain an order reference, truthful lifecycle status, amount/currency, and an optional deep link with
`startapp=order_<id>`. Delivery notifications never claim success before the backend observer has confirmed finalized evidence. Messages do not include wallet addresses, initData, JWTs, signatures, raw provider payloads or private data. Delivery notices are inserted in the same database transaction as the accepted delivery state transition.

## Retry and operations

The worker polls every 5 seconds by default and processes batches of 10. Claims are protected by
`FOR UPDATE SKIP LOCKED` and a 5-minute lease. A crashed worker's processing rows become
eligible again when the lease expires. Transient failures use bounded exponential backoff,
starting at 5 seconds and capped at 1 hour; Telegram flood-control delays are used when present
and are also capped. Eight failed attempts or a permanent Telegram error move the row to
`failed`. The last error and attempt count remain stored for inspection.

Configuration:

| Variable | Default | Purpose |
| --- | ---: | --- |
| `NOTIFICATION_POLL_SECONDS` | `5` | Idle poll interval |
| `NOTIFICATION_BATCH_SIZE` | `10` | Maximum rows claimed per pass |
| `NOTIFICATION_CLAIM_LEASE_SECONDS` | `300` | Recovery window for abandoned claims |
| `NOTIFICATION_MAX_ATTEMPTS` | `8` | Maximum transient attempts |
| `NOTIFICATION_RETRY_BASE_SECONDS` | `5` | First exponential retry delay |
| `NOTIFICATION_RETRY_MAX_SECONDS` | `3600` | Maximum retry delay |
| `TELEGRAM_MINI_APP_URL` | unset | Direct Mini App URL |

Operational checks should alert on old `pending` rows, any `failed` rows, and a growing
`attempt_count`. A useful starting query:

```sql
SELECT status, count(*) AS notifications,
       min(created_at) AS oldest_created_at,
       max(attempt_count) AS max_attempts
FROM telegram_notification_outbox
GROUP BY status
ORDER BY status;
```

## Delivery semantics and limitations

The outbox makes enqueueing durable and deduplicated, and prevents two live workers from
processing the same lease simultaneously. Telegram Bot API `sendMessage` does not provide a
client-supplied idempotency key, so exactly-once delivery cannot be guaranteed: if the process
crashes after Telegram accepts a message but before the success update commits, the message can
be sent again after lease recovery. The implemented guarantee is at-least-once delivery with
duplicate risk limited to that unavoidable acknowledgement window.

No payment processing, escrow, refunds, payout, or NFT transfer is performed by these
notifications. A notification is informational only. A failed notification send cannot roll back or fabricate a chain verification result.


## Guided Telegram bot experience

The user-facing bot exposes a compact Russian command menu:

| Command | Purpose |
| --- | --- |
| `/start` | Premium welcome screen and main navigation |
| `/app` | Open the configured Mini App |
| `/buy` | Buyer guide: catalogue, reservation and NFT delivery |
| `/sell` | Seller guide: wallet proof, inventory, moderation and transfer |
| `/orders` | Explain reservation and delivery states |
| `/safety` | Wallet and anti-scam guidance |
| `/help` | Help center and guided navigation |

The inline menu offers the same guided screens without requiring users to remember
commands. All help screens provide a return-to-menu action and an optional Mini App
launch button. If the Mini App URL is missing or invalid, the instructional screens
remain available.

Bot copy must remain aligned with the product model: a reservation is not payment,
the seller signs the NFT transfer in their own wallet, and only the backend observer
can independently confirm delivery. The bot does not offer wallet signing, payment,
escrow, refunds, support impersonation, or Telegram Gifts transfer functionality.
