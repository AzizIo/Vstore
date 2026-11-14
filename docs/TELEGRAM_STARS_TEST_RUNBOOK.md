# Telegram Stars test bot: isolated end-to-end runbook

This procedure exercises the real Telegram invoice, checkout, successful-payment update and refund API against Telegram's **dedicated Test Server**. Test Stars are not production charges. It does not enable public checkout, production refunds, NFT delivery, escrow or seller payouts.

The repository includes an isolated Docker Compose stack in `docker-compose.stars-test.yml`. It creates its own PostgreSQL container, named volume and private Compose network. It does not load the production `.env`, connect to the production PostgreSQL container, publish a database port or start the production bot.

## Safety boundary

The bot, seeder and refund worker all fail closed unless these conditions hold:

- `ENVIRONMENT=test`;
- `TELEGRAM_STARS_TEST_ENABLED=true`;
- a dedicated `TELEGRAM_STARS_TEST_BOT_TOKEN` is supplied and differs from `BOT_TOKEN`;
- `DATABASE_URL` uses PostgreSQL and a local host (`localhost`, `127.0.0.1`, `::1`, `db` or `postgres`);
- the database name begins with `test_` or ends with `_test`;
- Telegram API calls use the test namespace `/bot{token}/test/{method}`.

**Never use the production bot token, primary Telegram account, production database, shared database, VPS production Compose project or a mainnet wallet.** Do not paste tokens, passwords, seed phrases or private keys into GitHub, chat, logs or screenshots. The synthetic NFT has no item address or wallet and cannot be transferred.

## 1. Create a Telegram Test Server bot

Telegram's Test Server is fully separate from the main environment. Log in with a test account, then create a new bot using `@BotFather` inside that test account.

- Telegram Desktop: Settings → Shift + Alt + right-click **Add Account** → **Test Server**.
- Telegram for macOS: click Settings ten times to show the Debug Menu, then Command-click **Add Account** and log in to the test server.
- Telegram iOS: tap Settings ten times → Accounts → Login to another account → Test.

Official references:
- https://core.telegram.org/bots/features#testing-your-bot
- https://core.telegram.org/bots/payments-stars

Copy the token from the **test** BotFather privately. It is not interchangeable with the production bot token.

## 2. Start the isolated local stack

Run these commands from the repository root, on a machine with Docker Compose. Do not run them from the production deployment directory if that directory is configured with production environment variables.

Read the test bot token without echoing it, then generate a separate password for the disposable database:

```bash
read -rsp "Telegram Test Server bot token: " TELEGRAM_STARS_TEST_BOT_TOKEN
echo
export TELEGRAM_STARS_TEST_BOT_TOKEN
export STARS_TEST_DB_PASSWORD="$(openssl rand -hex 24)"
```

Build the backend image and start only the test PostgreSQL service:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml build
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml up -d db
```

Apply every migration, including `0013_payment_refund_workflow`, to this disposable database:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml --profile tools run --rm migrate
```

If any safety check fails, stop. Do not remove or weaken a runtime guard.

## 3. Identify your Telegram test account

Start the test bot in the foreground:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml --profile bot up bot
```

In Telegram's **test account**, open the new test bot and send:

```text
/whoami
```

Copy the numeric test account ID. Stop the foreground process with Ctrl+C before running the one-shot database tool.

## 4. Create and pay a synthetic test order

Create a small five-Star synthetic order. Substitute only the numeric ID returned by `/whoami`:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml --profile tools run --rm tools -m scripts.seed_stars_test_order --buyer-telegram-id 123456789 --stars 5
```

Save the `order_id` printed by the script. Start the bot again:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml --profile bot up bot
```

Send this command in the private chat with the test bot:

```text
/pay ORDER_UUID
```

Replace `ORDER_UUID` with the generated ID. Complete the invoice using Telegram's Test Server account. The bot must validate the payer, payload, currency and amount before recording `successful_payment`.

Expected result: the bot replies that the **test** payment is confirmed. This must not mark the order completed or trigger NFT delivery.

## 5. Verify the ledger, then test a real Test Server refund

In a second terminal, set the same two environment variables (the test token and generated database password) and set the order ID:

```bash
export ORDER_ID='PASTE_ORDER_UUID'
```

Inspect the payment state:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml exec -T db psql -U viltara_stars_test -d viltara_test -c "SELECT i.status AS intent_status, t.status AS transaction_status, t.amount, t.currency FROM payment_intents i JOIN payment_transactions t ON t.payment_intent_id = i.id WHERE i.order_id = '${ORDER_ID}'::uuid;"
```

For the refund exercise, explicitly enqueue the one captured test charge:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml --profile tools run --rm tools -m scripts.queue_stars_test_refund --order-id "${ORDER_ID}" --confirm-test-refund
```

This test-only command accepts exactly one captured Telegram Stars charge for the specified order, marks it `refund_pending`, and creates one durable refund job. It refuses orders with zero or multiple captured charges and refuses to queue the same charge twice.

Run the opt-in worker in the foreground:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml --profile refund-worker up refund-worker
```

The worker uses `refundStarPayment` with the original Telegram charge ID and the dedicated test bot token. Wait for the worker to process the queued job, then stop it with Ctrl+C. If Telegram returns an ambiguous result, the worker reconciles using `getStarTransactions`; it does not blindly issue a second refund.

Verify the final state:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml exec -T db psql -U viltara_stars_test -d viltara_test -c "SELECT i.status AS intent_status, t.status AS transaction_status, r.status AS refund_status, array_agg(e.event_type ORDER BY e.created_at) AS events FROM payment_intents i JOIN payment_transactions t ON t.payment_intent_id = i.id JOIN payment_refunds r ON r.payment_transaction_id = t.id JOIN payment_events e ON e.payment_intent_id = i.id WHERE i.order_id = '${ORDER_ID}'::uuid GROUP BY i.id, t.id, r.id;"
```

Expected final states: transaction `refunded`, refund job `succeeded`, and events include `payment_succeeded`, `refund_requested` and `refund_succeeded`. The order and synthetic NFT remain undelivered.

## 6. Stop and remove the disposable stack

Stop and remove only this named test project:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml down
```

This keeps the test database volume for inspection. After you have saved the test results and are certain you no longer need the data, remove only the named test volume:

```bash
docker compose -p viltara-stars-test -f docker-compose.stars-test.yml down -v
```

Unset local secrets when finished:

```bash
unset TELEGRAM_STARS_TEST_BOT_TOKEN STARS_TEST_DB_PASSWORD ORDER_ID
```

## What this test does not approve

Passing this runbook verifies the Stars test path and test refund API integration only. It does not authorize production charges/refunds, public Mini App checkout, NFT delivery, TON custody, testnet/mainnet escrow deployment, seller payouts or buyer-guarantee claims. Policy classification (Issue #155), escrow/ADR approvals and manual TON testnet acceptance remain separate gates.
