# Live demo preflight

Run this read-only check from a laptop or another machine with outbound HTTPS before showing VILTARA SHOP to a customer or investor.

It verifies the public endpoints that can be checked without signing in:

- API readiness, including PostgreSQL, Redis and authentication configuration
- Mini App entry page (HTTP 200 HTML)
- TON Connect manifest (HTTP 200 JSON and expected same-origin URLs)
- TON Connect icon (HTTP 200, `image/png` and a valid PNG signature)

## Run

From the repository root:

```bash
python backend/scripts/demo_preflight.py \
  --api-url https://<public-api-origin> \
  --mini-app-url https://<public-mini-app-origin>
```

If the manifest is hosted at a non-default path, pass `--manifest-url`. The current frontend contract expects `/tonconnect-manifest.json` on the Mini App origin, so a different origin or path is rejected.

Use origins only: do not include paths, query strings, usernames, passwords or tokens. The script never reads `.env`, does not print response bodies, does not send credentials, and does not modify the deployment. HTTP is accepted only for localhost development.

Exit code is `0` only when all checks pass; otherwise it is `1`. The report is deliberately limited to public reachability and configuration. It does **not** prove Telegram launch, a live wallet proof, authenticated listing/order actions, bot delivery, or NFT transfer. Those require the separate manual Telegram acceptance checklist.
