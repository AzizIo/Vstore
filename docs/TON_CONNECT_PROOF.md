# TON Connect wallet proof API

The backend verifies TON Connect `ton_proof` before setting `Wallet.is_verified`.
The authenticated user's ID comes from the API bearer token; client-supplied user
IDs and verification flags are not accepted.

## Configuration and support

Set `TON_CONNECT_ALLOWED_DOMAINS` to a JSON array of exact dApp domains, for
example `["app.example.com"]`, and set `TON_CONNECT_NETWORK` to `mainnet` or
`testnet`. Proof domains must exactly match an allowlisted domain. Empty or
invalid configuration disables both proof endpoints with HTTP 503.

The server accepts the TON Connect chain ID selected by this configuration
(`-239` for mainnet or `-3` for testnet) and writes the configured network to the
database; it never stores the network label supplied by the client. Only raw
workchain-0 addresses and the reviewed Wallet V3 R1, V3 R2, V4 R2, and V5 R1
contract layouts are currently supported. Other wallet versions, workchains,
and network IDs are rejected; there is no untrusted `get_public_key` fallback.

Challenges live in Redis for five minutes. A valid challenge is bound to the
authenticated user and is consumed atomically only after signature validation.
Proof timestamps may be at most five minutes old, with at most 30 seconds of
future clock skew.

## Endpoints

All endpoints below require `Authorization: Bearer <access-token>`.

### `POST /api/wallets/proof/challenge`

Returns a random, one-use TON Connect payload and expiry:

```json
{
  "payload": "server-generated-random-payload",
  "expires_at": "2026-11-10T12:00:00+00:00"
}
```

Pass `payload` as the TON Connect `ton_proof` request parameter. Do not construct
or reuse the payload on the client.

### `POST /api/wallets/proof/verify`

Submit the connected TON Connect account and successful proof. Values in this
example are placeholders, not real signatures:

```json
{
  "address": "0:<64-hex-character-account-hash>",
  "network": "-239",
  "public_key": "<64-hex-character-public-key>",
  "proof": {
    "timestamp": 1794312000,
    "domain": {
      "lengthBytes": 15,
      "value": "app.example.com"
    },
    "signature": "<base64-ed25519-signature>",
    "payload": "<payload-returned-by-challenge>",
    "state_init": "<base64-wallet-state-init-boc>"
  }
}
```

The response contains the verified wallet (`id`, normalized raw `address`,
server-selected `network`, `is_verified`, and `is_primary`). Duplicate wallets
return HTTP 409; invalid, expired, wrong-user, or replayed proofs return HTTP
401.

### `GET /api/wallets/me`

Returns only the authenticated user's wallets, without authentication data or
other users' records.

## Verification details and references

The verifier checks the configured network and exact allowlisted domain, the
UTF-8 byte length of the domain, proof timestamp and payload, StateInit BOC
canonical encoding, StateInit-derived account address, recognized wallet code
and data layout, and any supplied public key against the key extracted from that
state. It reconstructs the `ton-proof-item-v2/` message and verifies the
Ed25519 signature over
`sha256(0xffff ++ "ton-connect" ++ sha256(message))`. The challenge key is
SHA-256-indexed in Redis and compare-and-deleted atomically after successful
verification.

Specification references:

- [TON Connect specification: `ton_proof` address-proof signature](https://github.com/ton-blockchain/ton-connect/blob/02bd2e77f53641e2b9975e484af0b4fe521d6b05/spec/connect.md#address-proof-signature-ton_proof)
- [TON Docs: authenticate users with `ton_proof`](https://docs.ton.org/applications/ton-connect/how-to/ton-proof)
- [TON Connect SDK verifier example](https://github.com/ton-connect/sdk/tree/a07a165977eae17578b2414797f74d4bf54962eb/apps/demo-dapp-with-react-ui/src/server)

No chain transaction is sent, and wallet proof is not treated as proof of NFT
ownership. No seed phrase or private key is requested or stored.
