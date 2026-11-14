// VILTARA single-deal escrow protocol v1.
// Source of truth for opcodes, TL-B layouts, storage and generated ABI.

const PROTOCOL_VERSION = 1
const TESTNET_GLOBAL_ID = -3
const TESTNET_NETWORK_ID = -3
const ESCROW_DOMAIN = 0x56455343 // "VESC"
const NFT_FORWARD_MAGIC = 0x56454E46 // "VENF"

const ORACLE_ACTION_NFT_DELIVERED = 1
const ORACLE_ACTION_NFT_RETURNED_TO_SELLER = 2
const ORACLE_ACTION_SELLER_PAYOUT = 3
const ORACLE_ACTION_BUYER_REFUND = 4
const ORACLE_ACTION_UNEXPECTED_NFT_RECOVERED = 5

const RESOLUTION_BUYER_WINS = 1
const RESOLUTION_SELLER_WINS = 2

const STATE_INTENT_CREATED = 0
const STATE_AWAITING_NFT = 1
const STATE_AWAITING_BUYER_FUNDS = 2
const STATE_FUNDED_REVIEW = 3
const STATE_NFT_RELEASE_PENDING = 4
const STATE_DELIVERED_DISPUTE_WINDOW = 5
const STATE_DISPUTED = 6
const STATE_NFT_RETURN_PENDING = 7
const STATE_SELLER_PAYOUT_PENDING = 8
const STATE_BUYER_REFUND_PENDING = 9
const STATE_SETTLED = 10
const STATE_REFUNDED = 11
const STATE_EXPIRED = 12
const STATE_MANUAL_REVIEW = 13

const DISPUTE_PHASE_NONE = 0
const DISPUTE_PHASE_PRE_DELIVERY = 1
const DISPUTE_PHASE_POST_DELIVERY = 2

const PENDING_NONE = 0
const PENDING_EXPIRE_AFTER_NFT_RETURN = 1
const PENDING_REFUND_AFTER_NFT_RETURN = 2
const PENDING_PAYOUT_AFTER_NFT_DELIVERY = 3
const PENDING_REFUND_RECONCILIATION = 4
const PENDING_PAYOUT_RECONCILIATION = 5
const PENDING_UNEXPECTED_RECOVERY = 6

const SELLER_DEPOSIT_WINDOW_SECONDS = 1800
const BUYER_FUNDING_WINDOW_SECONDS = 3600
const BUYER_REVIEW_WINDOW_SECONDS = 86400
const DELIVERY_CONFIRMATION_GRACE_SECONDS = 1800
const POST_DELIVERY_DISPUTE_WINDOW_SECONDS = 172800
const POST_DELIVERY_NFT_RETURN_WINDOW_SECONDS = 86400
const ARBITRATION_WINDOW_SECONDS = 604800
const SETTLEMENT_RECONCILIATION_GRACE_SECONDS = 1800

enum Errors {
    NotTestnet = 700
    NotSeller = 701
    NotBuyer = 702
    InvalidState = 703
    InvalidValue = 704
    InvalidNft = 705
    InvalidDeal = 706
    NotAuthorized = 707
    InvalidAttestation = 708
    InvalidSignatures = 709
    Deadline = 710
    NothingToRecover = 711
    UnexpectedMessage = 712
}

struct DealRoles {
    seller: address
    buyer: address
}

struct DealAsset {
    itemAddress: address
    collectionAddress: address
    dealSalt: uint256
}

struct DealMoney {
    principalNanotons: coins
    executionReserve: coins
    nftTransferValue: coins
    fundQueryId: uint64
    nftDepositQueryId: uint64
    nftReleaseQueryId: uint64
    nftReturnToEscrowQueryId: uint64
    nftReturnToSellerQueryId: uint64
    sellerPayoutQueryId: uint64
    buyerRefundQueryId: uint64
}

struct AuthorityKeys {
    keyA: uint256
    keyB: uint256
    keyC: uint256
}

struct DealSecurity {
    oracleKeys: Cell<AuthorityKeys>
    resolverKeys: Cell<AuthorityKeys>
}

struct DealTerms {
    roles: Cell<DealRoles>
    asset: Cell<DealAsset>
    money: Cell<DealMoney>
    security: Cell<DealSecurity>
    networkId: int32
    protocolVersion: uint16
}

struct DealEvidence {
    lastEvidenceHash: uint256
    disputeReasonHash: uint256
}

struct DealRecovery {
    unexpectedPreviousOwner: address?
    unexpectedItemAddress: address?
}

struct DealProgress {
    state: uint8
    deadlineUnix: uint64
    disputePhase: uint8
    pendingAction: uint8
    nftInEscrow: bool
    principalLocked: bool
    // Monotonic, per-deal nonce for all oracle-attested outbound actions.
    // It is also used as the outbound TON message query_id.
    oracleAttemptId: uint64
    // Monotonic nonce for each dispute, preventing old resolver decisions
    // from becoming valid again if the same evidence hash is submitted later.
    disputeAttemptId: uint64
    evidence: Cell<DealEvidence>
    recovery: Cell<DealRecovery>
}

struct EscrowStorage {
    terms: Cell<DealTerms>
    progress: Cell<DealProgress>
}

struct DealStateReply {
    state: uint8
    deadlineUnix: uint64
    disputePhase: uint8
    pendingAction: uint8
    nftInEscrow: bool
    principalLocked: bool
    lastEvidenceHash: uint256
    disputeReasonHash: uint256
}

struct (0x56450001) ActivateDeal {
    queryId: uint64
    dealSalt: uint256
}

struct (0x56450002) FundDeal {
    queryId: uint64
    dealSalt: uint256
}

struct (0x56450003) AcceptDeal {
    queryId: uint64
    dealSalt: uint256
}

struct (0x56450004) OpenDispute {
    queryId: uint64
    dealSalt: uint256
    reasonHash: uint256
}

struct (0x56450005) OracleAttestation {
    data: Cell<OracleAttestationData>
    signatures: Cell<OracleSignatureSet>
}

struct (0x56450006) ResolveDispute {
    data: Cell<ResolverDecisionData>
    signatures: Cell<ResolverSignatureSet>
}

struct (0x56450007) TimeoutDeal {
    queryId: uint64
    dealSalt: uint256
}

struct (0x56450008) RecoverUnexpectedNft {
    queryId: uint64
    dealSalt: uint256
}

struct OracleContext {
    domain: uint32
    protocolVersion: uint16
    networkId: int32
    escrowAddress: address
    dealSalt: uint256
    action: uint8
    attemptId: uint64
}

struct OracleRoute {
    itemAddress: address
    sourceAddress: address
    destinationAddress: address
    amountNanotons: coins
    queryId: uint64
}

struct OraclePosition {
    masterchainSeqno: uint32
    logicalTime: uint64
}

struct OracleEvidenceHashes {
    messageHash: uint256
    traceHash: uint256
    evidenceHash: uint256
}

struct OracleAttestationData {
    context: Cell<OracleContext>
    route: Cell<OracleRoute>
    position: Cell<OraclePosition>
    hashes: Cell<OracleEvidenceHashes>
}

struct Signature {
    data: bits512
}

struct OracleSignatureSet {
    signatureA: Cell<Signature>
    signatureB: Cell<Signature>
    signatureC: Cell<Signature>
}

struct ResolverDecisionContext {
    domain: uint32
    protocolVersion: uint16
    networkId: int32
    escrowAddress: address
    dealSalt: uint256
    disputePhase: uint8
    outcome: uint8
    attemptId: uint64
    evidenceHash: uint256
}

struct ResolverDecisionData {
    context: Cell<ResolverDecisionContext>
}

struct ResolverSignatureSet {
    signatureA: Cell<Signature>
    signatureB: Cell<Signature>
    signatureC: Cell<Signature>
}

struct (0b0) PayloadInline {
    value: RemainingBitsAndRefs
}

struct (0b1) PayloadInRef {
    value: Cell<RemainingBitsAndRefs>
}

struct (0x5fcc3d14) NftTransfer {
    queryId: uint64
    newOwnerAddress: address
    sendExcessesTo: address?
    customPayload: cell?
    forwardTonAmount: coins
    @abi.clientType(PayloadInline | PayloadInRef)
    forwardPayload: RemainingBitsAndRefs
}

struct (0x05138d91) NotificationForNewOwner {
    queryId: uint64
    oldOwnerAddress: address
    @abi.clientType(PayloadInline | PayloadInRef)
    payload: RemainingBitsAndRefs
}

struct SettlementMessage {
    queryId: uint64
    dealSalt: uint256
    action: uint8
}

type AllowedMessage =
    | ActivateDeal
    | FundDeal
    | AcceptDeal
    | OpenDispute
    | OracleAttestation
    | ResolveDispute
    | TimeoutDeal
    | RecoverUnexpectedNft
    | NotificationForNewOwner

fun EscrowStorage.load(): EscrowStorage {
    return EscrowStorage.fromCell(contract.getData());
}

fun EscrowStorage.save(self) {
    contract.setData(self.toCell());
}
