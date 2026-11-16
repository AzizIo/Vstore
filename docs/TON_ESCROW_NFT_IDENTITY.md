# TON escrow NFT identity and collection policy

## Purpose and trust boundary

Escrow listing creation, deal reservation, action preparation, and terminal owner reconciliation require a proof-anchored identity for a standard TEP-62 NFT. A TON Center indexed owner/address or an unproven remote get-method response is not sufficient evidence.

The verifier reads the item account state and collection account state from the **same trusted masterchain block** through the existing Pytoniq trust-level-0 testnet client. It checks:

- both accounts are active at that block and carry code/data;
- the collection address is explicitly allowlisted by operator-reviewed policy;
- the item account's deployed code hash and collection's stored NFT item code hash equal the policy's item-code hash;
- the collection's code hash equals the policy's collection-code hash;
- the item data's collection/index/owner fields are well-formed;
- the item's index is below the collection's next_item_index;
- reconstructing the standard collection's get_nft_address_by_index(index) result from the proof-read collection item code and index yields the exact item account address;
- requested owner, when provided, equals the owner read from the same block.

This implementation does not execute arbitrary collection get-method code. The configured derivation policy explicitly limits the supported collection to tep62-standard-nft-collection-v1; the operator is responsible for reviewing the collection code hash before allowlisting it.

## Configuration

Set TON_ESCROW_NFT_COLLECTION_POLICIES to a JSON array. The default [] intentionally denies new escrow NFT intents.

Example shape only (hash/address placeholders are not usable values):

    [
      {
        "policy_id": "reviewed-testnet-collection-v1",
        "collection_address": "0:<64-hex-basechain-address-hash>",
        "collection_code_hash": "<64-hex-sha256-of-reviewed-collection-code>",
        "item_code_hash": "<64-hex-sha256-of-reviewed-item-code>",
        "derivation": "tep62-standard-nft-collection-v1"
      }
    ]

Do not copy code hashes from NFT metadata or indexed API responses. Establish them from a trusted/proof-checked account-state read, review the collection implementation and its upgradeability, then approve the exact collection address and code hashes through deployment configuration. Duplicate collection entries, malformed hashes, an unknown derivation type, a code mismatch, and an empty policy list all fail closed.

No approved production or live-testnet collection policy is shipped in this repository. Do not enable the policy by guessing a collection or hash. Preview-specific wiring remains owned by the release integration work and was not modified here.

## Persisted identity evidence

Successful listing intent and deal creation persist canonical JSON identity evidence with an independent SHA-256 digest, including policy id/digest, exact item and collection addresses, item index, item/collection/item-template code hashes, item/collection data hashes, derived item address, trusted masterchain sequence/block hash, trust-anchor key-block hash, provider id, and observation time.

The database check constraints require the JSON's evidence_sha256 to match the separate digest column. PostgreSQL triggers and ORM guards prevent changing an identity snapshot once written, and protect the bound network, marketplace listing, seller, item/collection/seller addresses, price and idempotency key. The seller-intent binding trigger also protects the local asset ID, seller wallet ID and listing key. Lifecycle status updates remain permitted; proof-bound fields do not. Creating a buyer deal repeats the proof at a fresh trusted block and requires the policy/code/address identity anchor to match the seller intent snapshot.

Action preparation verifies the persisted snapshot and obtains a new trusted identity/owner proof before producing new unsigned wallet payloads. Existing idempotent retries of already-persisted unsigned payloads remain byte-for-byte replays. Terminal-owner reconciliation repeats the collection/item proof; release/relisting stays blocked if the snapshot is absent, altered, mismatched, stale, or cannot be proven.

Legacy rows without identity evidence are not silently blessed. Such deals require operator review and cannot authorize new wallet actions or terminal listing release until an explicit safe reconciliation path is approved.

## Failure handling

- Provider timeout or unavailable trusted masterchain head: return a retryable unavailable response; do not reserve a new deal or prepare a new payload.
- Owner mismatch, unapproved collection, malformed account data, wrong item code, wrong collection code, wrong derived item address, or changed policy/identity: reject with conflict/fail-closed evidence handling.
- Missing persisted identity evidence or digest mismatch: action preparation is blocked; terminal reconciliation leaves the underlying marketplace listing reserved and requires manual review.
- The verifier does not sign, broadcast, or submit a TON message. Wallet users still sign the exact unsigned BOCs returned by the existing preparation flow.
- This feature remains TON testnet only. Production deployment and Preview config changes are out of scope.

## Migration and tests

Migration 0020_escrow_nft_identity_snapshots adds nullable evidence columns for safe rollout; it does not manufacture evidence for old rows. The migration is reversible only while both identity columns are empty. Run backend CI's PostgreSQL upgrade/downgrade test, then the escrow tests covering allowlist failure, forged collection, same-index/wrong-address, item/collection code mismatch, owner change, stale digest, provider failure, and same-block account reads before accepting a policy or enabling the flow.


## Cryptographic finality boundary

Indexer observations are discovery hints only. The existing testnet finality provider:

1. Creates a Pytoniq LiteClient with `trust_level=0`; when using the default factory, its configured init key block must match the built-in trusted testnet key-block set.
2. Resolves the candidate workchain/shard/sequence to a LiteServer block ID and rejects a locator mismatch.
3. Requests the shard-block inclusion proof, follows the masterchain proof chain from the trusted key block (including the validator/config signatures checked by Pytoniq), and separately checks the shard inclusion proof against the masterchain.
4. Requires the proof-returned masterchain sequence to match the discovered candidate's sequence, then requires the latest trusted masterchain head to be at least `TON_ESCROW_FINALITY_MIN_DEPTH` blocks beyond that inclusion block.
5. Retrieves the transaction list with proof from the shard block, uniquely matches the escrow account/LT/transaction-cell hash, and verifies the inbound message hash/destination and derived trace binding. It reads contract getters from the same proven masterchain anchor and reconciles them with the immutable deal snapshot before the observer can advance canonical state.

The discovery candidate's `finalized` bit never authorizes state advancement. If the locator conflicts with the proof-returned block, the transaction/message is absent or ambiguous, validator/config proof validation fails, the current head lacks the configured depth, or any contract getter disagrees with the snapshot, the provider returns invalid/unavailable evidence and the observer leaves the event pending/retryable or routes it to manual review. It must not turn an indexer status into a successful terminal event.

Adversarial tests now cover a mismatched shard locator, an indexed/masterchain sequence conflict, insufficient masterchain depth, validator/config-proof failure, and shard-inclusion-proof failure. These exercise the fail-closed boundary with controlled proof-client doubles; they are not a live testnet acceptance test and do not substitute for an owner-approved end-to-end test using disposable wallets.


### Database immutability guard

PostgreSQL triggers freeze identity snapshots and proof-bound listing/deal terms even when a row has no snapshot yet, preventing direct SQL from retrofitting evidence onto legacy rows. Deal buyer binding, salt, principal, and established contract bindings are immutable; lifecycle status updates remain allowed. Downgrade refuses to discard identity evidence while any listing intent or deal references it.
