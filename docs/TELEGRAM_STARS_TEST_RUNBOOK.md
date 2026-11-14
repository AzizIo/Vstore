# Telegram Stars test bot runbook

This is an **internal test-only procedure** for the isolated Telegram Stars bot added in PR #170. It does not enable public checkout, production payments, refunds, escrow or NFT delivery.

## Safety requirements

The test bot refuses to start unless all of these conditions are true:

- `ENVIRONMENT=test`;
- `TELEGRAM_STARS_TEST_ENABLED=true`;
- `TELEGRAM_STARS_TEST_BOT_TOKEN` is supplied and differs from `BOT_TOKEN`;
- `DATABASE_URL` is PostgreSQL using a local host (`localhost`, `127.0.0.1`, `::1`, `db` or `postgres`);
- the database name begins with `test_` or ends with `_test`.

The bot uses Telegram's dedicated test API route `/bot{token}/test/{method}`; it does not use aiogram's default production route. Its file endpoint also stays in the test namespace. The URLs are covered by unit tests.

**Do not use a production Telegram account, primary bot token, shared database, VPS production environment or mainnet wallet for this procedure.** No seed phrase or private key is needed.

## 1. Create a Telegram test account and bot

Telegram's test environment is separate from the main environment. Create a new test account and a new bot with @BotFather while logged into that test account.

Official steps:

- [Telegram Bot Features — Dedicated test environment](https://core.telegram.org/bots/features#testing-your-bot): for Telegram Desktop, use Settings → Shift + Alt + right-click **Add Account** → **Test Server**. On macOS Telegram, open the debug menu by clicking Settings ten times, then Command-click **Add Account** and log in to the test server.
- [Telegram Mini Apps — Testing Mini Apps](https://core.telegram.org/bots/webapps#testing-mini-apps): documents the separate test account and the dedicated Test Bot API route.

Create a new bot through @BotFather inside the test environment and copy its token into a local environment variable. Do not paste it into GitHub, a PR comment, a log, or this repository.

## 2. Create a dedicated local PostgreSQL database

Start a local PostgreSQL instance and create a database named `viltara_test` (or another name ending in `_test`). Use a local PostgreSQL role with permission to create schema objects. For example:

```bash
createdb -h 127.0.0.1 -p 5432 -U postgres viltara_test
```

Use the local database credentials configured on your machine. Do not point `DATABASE_URL` at the Vstore VPS, a shared developer database, preview, staging or production.

## 3. Configure only the test process

From the repository's `backend/` directory, set the environment for this terminal. `BOT_TOKEN` is deliberately a non-secret placeholder: the test runtime only needs a non-empty value to ensure it is not reusing the primary token. Do not copy a real production token into this process.

```bash
export ENVIRONMENT=test
export TELEGRAM_STARS_TEST_ENABLED=true
export BOT_TOKEN=not-a-real-token-used-only-by-the-test-guard
export TELEGRAM_STARS_TEST_BOT_TOKEN='PASTE_TOKEN_FROM_TELEGRAM_TEST_BOTFATHER'
export DATABASE_URL='postgresql+asyncpg://postgres:YOUR_LOCAL_PASSWORD@127.0.0.1:5432/viltara_test'
```

Replace only the local database role/password and test-bot token. Keep the host local and the database name test-scoped.

## 4. Apply migrations

Run these commands from `backend/` in the same terminal so later processes inherit the isolated test configuration:

```bash
python -m pip install -e '.[dev]'
alembic upgrade head
```

The migration command must use the same local disposable test database configured above. Do not register a webhook for this test bot; it uses long polling. If any guard fails, stop and fix the test configuration; do not weaken or bypass the runtime guard.

## 5. Exercise the test flow

Only use synthetic rows in `viltara_test`. The repository includes a guarded seeder so you do not need to create linked rows manually.

1. Start the test bot with `python -m app.payments_test_bot`.
2. In a private chat, send `/whoami` and copy the numeric Telegram test account ID returned by the bot.
3. Stop polling with Ctrl+C. In the same terminal, create a disposable order:

   ```bash
   python -m scripts.seed_stars_test_order --buyer-telegram-id 123456789 --stars 25
   ```

   Replace `123456789` with the ID returned by `/whoami`. The default amount is 25 XTR; allowed test amounts are 1–100000 XTR. The script reuses/creates the test buyer, creates a synthetic seller, and creates one reserved XTR order with a **pending, unverified placeholder NFT that has no item address or wallet**. It refuses to run unless all bot test-environment guards pass and it uses the same local disposable test database. The command prints the generated `order_id`.
4. Start the test bot again and send the generated order ID:

   ```text
   /pay ORDER_UUID
   ```

The bot creates an invoice from the persisted order snapshot. Telegram's test environment delivers `pre_checkout_query` and `successful_payment`; the backend validates the payer, payload, currency and amount before recording the payment ledger event. The synthetic NFT is not transferable and no on-chain delivery is attempted.

Available support commands are `/paysupport`, `/terms` and `/support`.

A successful Stars test payment **does not** mark the NFT order completed. NFT delivery still requires the separate on-chain verification flow. This test bot does not implement or claim escrow, guaranteed delivery, seller payouts or automatic refunds. Refunds must use the separate durable refund worker workflow; do not add a direct refund call to this bot. That worker remains a separate review-gated change in PR #173.

## 6. Stop and clean up

Stop polling with Ctrl+C. Remove the test environment variables from the terminal:

```bash
unset ENVIRONMENT TELEGRAM_STARS_TEST_ENABLED BOT_TOKEN
unset TELEGRAM_STARS_TEST_BOT_TOKEN DATABASE_URL
```

When finished, drop only the local disposable `viltara_test` database after confirming that the connection target is local and the database name is test-scoped. Never run cleanup commands against any other database.

## What this runbook does not authorize

It does not authorize a public paid flow, production Stars charges, production refunds, TON custody, testnet/mainnet escrow deployment, seller settlement or buyer-guarantee claims. The Telegram policy classification in Issue #155, live testnet acceptance in Issue #46 and payment/escrow ADR approvals remain separate gates.
