# TON NFT verification (read-only)

## Scope

\`TONNFTVerifier\` reads TEP-62 contract state, checks initialization, collection/index association, and current ownership against an expected wallet. It performs no database writes, transactions, transfers, or wallet signing.

## Ownership source of truth

TON Center v3 has two distinct roles in this adapter:

- \`GET /api/v3/nft/items\` is used to discover candidate NFTs for an owner and to retrieve optional display metadata.
- \`POST /api/v3/runGetMethod\` executes the NFT contract's \`get_nft_data()\` method for each candidate. The returned \`owner_address\`, initialization flag, index and collection address are used for verification. The provider's indexed \`owner_address\` is not accepted as proof of current ownership.
- For collection NFTs, the verifier calls the collection contract's \`get_nft_address_by_index(index)\` using \`runGetMethod\` and compares the returned address with the exact item contract address.

This follows TEP-62: \`get_nft_data()\` returns initialization, index, collection, owner and content; the collection's \`get_nft_address_by_index(index)\` confirms the item address at that index. See the [TEP-62 standard](https://github.com/ton-blockchain/TEPs/blob/master/text/0062-nft-standard.md) and [TON NFT processing guide](https://docs.ton.org/develop/dapps/asset-processing/nfts).

## Trust model and limitations

- Contract get-methods are stronger than trusting the indexer's denormalized owner field, but a hosted RPC provider is still a trusted node service, not an independently validated Merkle proof. For high-value operations, use a provider/node with an explicit finality and proof policy.
- The owner value is a point-in-time contract-state observation. Ownership can change immediately after verification; this does not reserve the NFT or authorize publication forever.
- Indexer results are discovery hints only. A stale or inaccurate owner field in \`nft/items\` cannot by itself make an NFT appear verified.
- Missing/uninitialized contracts, non-zero get-method exit codes, malformed stack data, collection-index mismatch, or owner mismatch are not treated as verified.
- Timeout, DNS, rate-limit and server failures remain provider-unavailable errors; they must never be converted into an empty inventory or an ownership mismatch.
- Friendly addresses are checksum-validated and normalized to raw \`workchain:hex\` form before comparison.
- Metadata is optional bounded display data. Metadata lookup failures do not invalidate on-chain ownership verification and metadata never proves ownership.
- Collection-less TEP-62 items skip the collection method but still require initialized state and exact owner match.

## TON Center limits

The API key is passed only to TON Center requests. TON Center documents a default limit of 1 request per second without an API key for \`runGetMethod\`; configure an API key and a suitable plan for normal inventory sizes. Calls are bounded by the existing provider timeout, response-size limit and retry policy. No unbounded retries are used.

## Usage

\`\`\`python
from app.assets.ton_nft import TONCenterV3Config, TONCenterV3Provider, TONNFTVerifier

config = TONCenterV3Config(
    base_url="https://toncenter.com/api/v3",  # use testnet endpoint for testnet assets
    api_key=None,  # inject from secret configuration in deployment
    timeout_seconds=8.0,
)

async with TONCenterV3Provider(config) as provider:
    result = await TONNFTVerifier(provider).verify(item_address, wallet_address)
    if result.is_verified:
        ...  # re-check before any irreversible operation
\`\`\`

The transport is asynchronous \`httpx\`. Unit tests inject \`httpx.MockTransport\`; no live TON endpoint or API key is needed.
