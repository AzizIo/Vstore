# TON NFT verification (read-only)

## Scope

`TONNFTVerifier` reads one TON NFT item, checks initialization, collection/index association, and current ownership against an expected seller wallet. It performs no database writes, transactions, transfers, API route registration, or listing publication.

## Standard and data source

The contract interface is [TEP-62](https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md): `get_nft_data()` exposes initialization, index, collection and owner; a collection exposes `get_nft_address_by_index(index)`. See the [TON NFT reference implementation](https://docs.ton.org/contracts/standard/tokens/nft/nft-reference).

The initial adapter uses [TON Center API v3](https://docs.ton.org/ecosystem/api/toncenter/v3/overview), `GET /api/v3/nft/items`. Its documented filters include item address, collection address and index, and its response includes `init`, `index`, `collection_address`, `owner_address` and item address. The verifier queries the item by address, then queries the indexer by collection plus index and compares the returned item address. This implements TON's documented [high-level NFT collection membership verification flow](https://docs.ton.org/contracts/standard/tokens/nft/verify).

## Trust model and limitations

- TON Center v3 is an indexed data layer, not a trustless cryptographic proof response. This adapter trusts the configured provider's indexed view; it does not independently execute contract get-methods or validate a Merkle proof.
- Indexing lag, API rate limits, provider availability and upstream data quality can affect results. Configure an API key and controlled endpoint in deployment; never hardcode credentials.
- A missing item is `not_found`; malformed upstream data is `invalid_data`; network, timeout and server failures are `provider_unavailable`. Temporary provider failure is never evidence of incorrect ownership.
- Friendly addresses are checksum-validated and normalized to raw `workchain:hex` form before comparison.
- Metadata is optional, bounded display data only. The adapter does not fetch metadata URLs or images. Metadata never proves collection membership or ownership.
- Collection-less TEP-62 items skip the collection lookup but still require initialized state and owner match.
- The result is a **point-in-time snapshot**. Ownership can change immediately after verification; this does not reserve the NFT, prevent transfers, or authorize listing publication.

## Usage

```python
from app.assets.ton_nft import TONCenterV3Config, TONCenterV3Provider, TONNFTVerifier

config = TONCenterV3Config(
    base_url="https://toncenter.com/api/v3",  # use testnet endpoint for testnet assets
    api_key=None,  # inject from secret configuration in deployment
    timeout_seconds=8.0,
)

async with TONCenterV3Provider(config) as provider:
    result = await TONNFTVerifier(provider).verify(item_address, seller_wallet_address)
    if result.is_verified:
        ...  # re-check before any irreversible operation
```

The HTTP transport is asynchronous `httpx`. Unit tests inject `httpx.MockTransport`; no live TON endpoint or API key is needed.
