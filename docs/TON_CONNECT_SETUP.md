# TON Connect: setup and manual verification

This document covers wallet linking for the Telegram Mini App. A connected account is **not** a verified wallet. The backend remains authoritative: a wallet is displayed as verified only after `POST /api/wallets/proof/verify` accepts its TON Connect Proof and `GET /api/wallets/me` returns the verified record.

## Configuration

Configure the same real public HTTPS origin in frontend and backend. Do not guess a production hostname.

In `frontend/.env` (start from `frontend/.env.example`):

```dotenv
VITE_TONCONNECT_APP_URL=https://<your-public-miniapp-host>
VITE_TONCONNECT_MANIFEST_URL=https://<your-public-miniapp-host>/tonconnect-manifest.json
```

In the root `.env` (start from `.env.example`):

```dotenv
TON_CONNECT_ALLOWED_DOMAINS=["<your-public-miniapp-host>"]
TON_CONNECT_NETWORK=mainnet
```

Use the hostname only for `TON_CONNECT_ALLOWED_DOMAINS`: no `https://`, port, path, or trailing slash. It must exactly match the TON Connect Proof domain sent by the wallet. Use `TON_CONNECT_NETWORK=testnet` and the corresponding testnet wallet/network only when explicitly testing testnet. The backend fails closed when this allowlist is empty or invalid.

The app URL must be an origin without a path. For development, a public HTTPS tunnel can be used; set both frontend URLs to that tunnel's origin and temporarily allow the exact hostname in the backend list. Do not keep a temporary tunnel host as production configuration.

## Manifest and icon

- `/tonconnect-manifest.json` is generated from `VITE_TONCONNECT_APP_URL`, with the app origin, name, and absolute `iconUrl`.
- `/tonconnect-icon.png` is a 180×180 PNG placed in the public frontend assets.
- Vite development and preview middleware serve the manifest with JSON content type and CORS headers. Production static hosting/reverse proxy must serve both files over HTTPS without authentication and add `Access-Control-Allow-Origin: *` (or the requesting origin) for the manifest response.
- Production build intentionally fails without both frontend TON Connect variables, to avoid publishing a placeholder manifest.

After deployment, verify from a network independent of the VPS:

```bash
curl -i https://<your-public-miniapp-host>/tonconnect-manifest.json
curl -i https://<your-public-miniapp-host>/tonconnect-icon.png
```

The manifest request must return HTTP 200, `Content-Type: application/json`, and a JSON object with `url`, `name`, and `iconUrl`. The icon must return HTTP 200 and `image/png`. Confirm the manifest is raw JSON, not a login page, Cloudflare challenge, or HTML fallback.

## Manual test with Telegram and Tonkeeper

Use a test account and the intended network. Do not enter or share a seed phrase or private key; the app never needs either.

1. Build and deploy the Mini App to the configured HTTPS origin. Confirm the manifest and PNG checks above pass. Confirm backend `TON_CONNECT_ALLOWED_DOMAINS` contains exactly that hostname and `TON_CONNECT_NETWORK` matches the chain you will use.
2. Open the Mini App from the actual Telegram bot menu button/link on a phone with Tonkeeper installed. Sign in through the existing Telegram Mini App authentication. Do not test only in a desktop browser if the intended flow uses Tonkeeper on mobile.
3. Tap **Connect & verify**. The app requests a fresh backend challenge before opening TON Connect. Select Tonkeeper and approve only the TON Connect proof/signature prompt. This is a proof signature, not a payment or NFT transfer.
4. After a successful signature, check the UI says **Wallet verified by VILTARA**. Check the network label, then call `GET /api/wallets/me` with the same authenticated API bearer token and confirm the matching address/network is `is_verified: true`. The address printed by the client alone is not evidence.
5. Disconnect and reopen the Mini App. A restored TonConnect session without a fresh proof must not create a new backend wallet record or trigger `POST /api/wallets/proof/verify`. An already-linked wallet can remain displayed as verified only because the backend returns its prior verified record.
6. Switch to an unlinked account or the wrong network. The new account/network must not be shown as verified. Reconnect through **Connect & verify** to request a fresh challenge and proof for that account/network.
7. Cancel the Tonkeeper prompt or use a wallet that does not return TON Proof. The UI must show an actionable error and must not mark the wallet verified. If the challenge expires while the prompt is open, reconnect to get a new challenge.
8. Check negative cases using tests or a non-production environment: invalid signature, wrong domain, wrong chain/network, expired challenge, challenge issued to another user, and proof replay. The same proof should succeed once and then fail on replay. Never tamper with production requests.

## CI and local checks

```bash
cd backend
ruff check app tests migrations
pytest -q

cd ../frontend
npm run test:coverage
VITE_TONCONNECT_APP_URL=https://viltara-ci.example \
VITE_TONCONNECT_MANIFEST_URL=https://viltara-ci.example/tonconnect-manifest.json \
npm run build
```

The `viltara-ci.example` values are reserved example-only values for build verification. Replace them with the actual host for any build intended to be deployed. Wallet proof verifies control of a wallet address only; this integration does not enable payments, escrow, transactions, or NFT transfer.
