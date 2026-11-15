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

The database check constraints require the JSON's evidence_sha256 to match the separate digest column. PostgreSQL triggers and ORM guards prevent changing an identity snapshot once written. Creating a buyer deal repeats the proof at a fresh trusted block and requires the policy/code/address identity anchor to match the seller intent snapshot.

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
