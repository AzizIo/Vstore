import "types"
import "signatures"

contract DealEscrow {
    author: "AzizIo"
    version: "1.0.0"
    description: "Immutable single-deal TON NFT + native TON escrow. Testnet only."
    storage: EscrowStorage
    incomingMessages: AllowedMessage
}

fun assertTestnet(terms: DealTerms) {
    assert (terms.networkId == TESTNET_NETWORK_ID) throw Errors.NotTestnet;
    assert (terms.protocolVersion == PROTOCOL_VERSION) throw Errors.InvalidDeal;
    assert (contract.getAddress().getWorkchain() == BASECHAIN) throw Errors.NotTestnet;

    val globalIdCell = blockchain.configParam(19);
    assert (globalIdCell != null) throw Errors.NotTestnet;
    val globalId = globalIdCell.beginParse().loadInt(32);
    assert (globalId == TESTNET_GLOBAL_ID) throw Errors.NotTestnet;

    val security = terms.security.load();
    val oracle = security.oracleKeys.load();
    val resolver = security.resolverKeys.load();
    assert (
        oracle.keyA != 0 && oracle.keyB != 0 && oracle.keyC != 0
        && oracle.keyA != oracle.keyB && oracle.keyA != oracle.keyC && oracle.keyB != oracle.keyC
    ) throw Errors.InvalidDeal;
    assert (
        resolver.keyA != 0 && resolver.keyB != 0 && resolver.keyC != 0
        && resolver.keyA != resolver.keyB && resolver.keyA != resolver.keyC && resolver.keyB != resolver.keyC
    ) throw Errors.InvalidDeal;
    assert (
        oracle.keyA != resolver.keyA && oracle.keyA != resolver.keyB && oracle.keyA != resolver.keyC
        && oracle.keyB != resolver.keyA && oracle.keyB != resolver.keyB && oracle.keyB != resolver.keyC
        && oracle.keyC != resolver.keyA && oracle.keyC != resolver.keyB && oracle.keyC != resolver.keyC
    ) throw Errors.InvalidDeal;
}

fun validateTerms(terms: DealTerms) {
    val roles = terms.roles.load();
    val asset = terms.asset.load();
    val money = terms.money.load();

    assert (roles.seller != roles.buyer) throw Errors.InvalidDeal;
    assert (asset.dealSalt != 0) throw Errors.InvalidDeal;
    assert (asset.itemAddress.getWorkchain() == BASECHAIN) throw Errors.InvalidDeal;
    assert (asset.collectionAddress.getWorkchain() == BASECHAIN) throw Errors.InvalidDeal;
    assert (money.principalNanotons > 0) throw Errors.InvalidValue;
    assert (money.executionReserve >= grams("0.5")) throw Errors.InvalidValue;
    assert (money.sellerDeploymentRefundNanotons >= grams("0.02"))
        throw Errors.InvalidValue;
    assert (money.sellerDeploymentRefundNanotons <= grams("0.1"))
        throw Errors.InvalidValue;
    assert (money.nftTransferValue >= grams("0.05")) throw Errors.InvalidValue;
    assert (money.nftTransferValue <= grams("0.15")) throw Errors.InvalidValue;
    assert (
        money.executionReserve
        >= money.nftTransferValue * 3
            + money.sellerDeploymentRefundNanotons
            + TERMINAL_STORAGE_RESERVE
            + grams("0.1")
    ) throw Errors.InvalidValue;
    assert (money.fundQueryId != 0) throw Errors.InvalidDeal;
    assert (money.nftDepositQueryId != 0) throw Errors.InvalidDeal;
    assert (money.nftReleaseQueryId != 0) throw Errors.InvalidDeal;
    assert (money.nftReturnToEscrowQueryId != 0) throw Errors.InvalidDeal;
}

fun requireActionValue(valueCoins: coins) {
    assert (valueCoins >= grams("0.01")) throw Errors.InvalidValue;
}

fun checkDealSalt(asset: DealAsset, suppliedSalt: uint256) {
    assert (asset.dealSalt == suppliedSalt) throw Errors.InvalidDeal;
}

fun asManualReview(progress: DealProgress): DealProgress {
    var next = progress;
    next.state = STATE_MANUAL_REVIEW;
    next.deadlineUnix = 0;
    return next;
}

fun makeOutboundAction(
    kind: uint8,
    itemAddress: address,
    destination: address,
    recipient: address,
    responseDestination: address,
    queryId: uint64,
    dealSalt: uint256,
    attemptId: uint64,
    amountNanotons: coins,
    messageValueNanotons: coins,
    expectedState: uint8,
    expectedPendingAction: uint8,
    retryWindowSeconds: uint32,
    messageBodyHash: uint256,
    status: uint8,
    bouncePhase: uint8,
    exitCode: int32,
): OutboundAction {
    return OutboundAction {
        kind,
        queryId,
        dealSalt,
        attemptId,
        amountNanotons,
        messageValueNanotons,
        expectedState,
        expectedPendingAction,
        retryWindowSeconds,
        messageBodyHash,
        status,
        bouncePhase,
        exitCode,
        addresses: OutboundActionAddresses {
            itemAndDestination: OutboundActionAddressPair {
                first: itemAddress,
                second: destination,
            }.toCell(),
            recipientAndResponse: OutboundActionAddressPair {
                first: recipient,
                second: responseDestination,
            }.toCell(),
        }.toCell(),
    };
}

fun recordOutboundAction(mutate progress: DealProgress, action: OutboundAction) {
    var actions = progress.outboundActions.load();
    if (actions.first == null) {
        actions.first = action.toCell();
    } else if (actions.second == null) {
        actions.second = action.toCell();
    } else {
        throw Errors.OutboundActionCapacity;
    }
    progress.outboundActions = actions.toCell();
}

fun consumeOutboundAction(
    mutate progress: DealProgress,
    kind: uint8,
    itemAddress: address,
    recipient: address,
    queryId: uint64,
    amountNanotons: coins,
    verifyAmount: bool,
): bool {
    var actions = progress.outboundActions.load();
    if (actions.first != null) {
        val action = actions.first.load();
        val addresses = action.addresses.load();
        val itemAndDestination = addresses.itemAndDestination.load();
        val recipientAndResponse = addresses.recipientAndResponse.load();
        if (
            action.status == OUTBOUND_STATUS_PENDING
            && action.kind == kind
            && itemAndDestination.first == itemAddress
            && recipientAndResponse.first == recipient
            && action.queryId == queryId
            && action.attemptId == queryId
            && (!verifyAmount || action.amountNanotons == amountNanotons)
        ) {
            actions.first = null;
            progress.outboundActions = actions.toCell();
            return true;
        }
    }
    if (actions.second != null) {
        val action = actions.second.load();
        val addresses = action.addresses.load();
        val itemAndDestination = addresses.itemAndDestination.load();
        val recipientAndResponse = addresses.recipientAndResponse.load();
        if (
            action.status == OUTBOUND_STATUS_PENDING
            && action.kind == kind
            && itemAndDestination.first == itemAddress
            && recipientAndResponse.first == recipient
            && action.queryId == queryId
            && action.attemptId == queryId
            && (!verifyAmount || action.amountNanotons == amountNanotons)
        ) {
            actions.second = null;
            progress.outboundActions = actions.toCell();
            return true;
        }
    }
    return false;
}

fun DealProgress.startOracleAttempt(mutate self): uint64 {
    assert (self.oracleAttemptId < 0xffffffffffffffff) throw Errors.InvalidAttestation;
    self.oracleAttemptId += 1;
    return self.oracleAttemptId;
}

fun hasValidInlineNftPayload(payload: slice, asset: DealAsset): bool {
    if (payload.remainingBitsCount() != 289 || payload.remainingRefsCount() != 0) {
        return false;
    }

    var body = payload;
    if (body.loadUint(1) != 0) {
        return false;
    }
    if (body.loadUint(32) != NFT_FORWARD_MAGIC) {
        return false;
    }
    if (body.loadUint(256) != asset.dealSalt) {
        return false;
    }
    return body.remainingBitsCount() == 0 && body.remainingRefsCount() == 0;
}

fun makeNftPayload(asset: DealAsset): RemainingBitsAndRefs {
    return beginCell()
        .storeBool(false)
        .storeUint(NFT_FORWARD_MAGIC, 32)
        .storeUint(asset.dealSalt, 256)
        .toSlice();
}

fun sendNftTo(
    mutate progress: DealProgress,
    kind: uint8,
    itemAddress: address,
    newOwnerAddress: address,
    responseDestination: address,
    queryId: uint64,
    asset: DealAsset,
    transferValue: coins,
    expectedState: uint8,
    expectedPendingAction: uint8,
    retryWindowSeconds: uint32,
) {
    val body = NftTransfer {
        queryId,
        newOwnerAddress,
        sendExcessesTo: responseDestination,
        customPayload: null,
        forwardTonAmount: grams("0.01"),
        forwardPayload: makeNftPayload(asset),
    };
    recordOutboundAction(mutate progress, makeOutboundAction(
            kind,
            itemAddress,
            itemAddress,
            newOwnerAddress,
            responseDestination,
            queryId,
            asset.dealSalt,
            queryId,
            transferValue,
            transferValue,
            expectedState,
            expectedPendingAction,
            retryWindowSeconds,
            body.toCell().hash(),
            OUTBOUND_STATUS_PENDING,
            0,
            0
        ));
    val transfer = createMessage({
        bounce: BounceMode.RichBounce,
        value: transferValue,
        dest: itemAddress,
        body,
    });
    transfer.send(SEND_MODE_PAY_FEES_SEPARATELY + SEND_MODE_BOUNCE_ON_ACTION_FAIL);
}

fun sendSellerPayout(
    mutate progress: DealProgress,
    roles: DealRoles,
    asset: DealAsset,
    money: DealMoney,
    attemptId: uint64,
) {
    val body = SettlementMessage {
        queryId: attemptId,
        dealSalt: asset.dealSalt,
        action: ORACLE_ACTION_SELLER_PAYOUT,
    };
    recordOutboundAction(mutate progress, makeOutboundAction(
            OUTBOUND_KIND_SELLER_PAYOUT,
            asset.itemAddress,
            roles.seller,
            roles.seller,
            roles.seller,
            attemptId,
            asset.dealSalt,
            attemptId,
            money.principalNanotons,
            money.principalNanotons,
            STATE_SELLER_PAYOUT_PENDING,
            PENDING_PAYOUT_RECONCILIATION,
            SETTLEMENT_RECONCILIATION_GRACE_SECONDS,
            body.toCell().hash(),
            OUTBOUND_STATUS_PENDING,
            0,
            0
        ));
    val payout = createMessage({
        bounce: BounceMode.RichBounce,
        value: money.principalNanotons,
        dest: roles.seller,
        body,
    });
    payout.send(SEND_MODE_PAY_FEES_SEPARATELY + SEND_MODE_BOUNCE_ON_ACTION_FAIL);
}

fun sendBuyerRefund(
    mutate progress: DealProgress,
    roles: DealRoles,
    asset: DealAsset,
    money: DealMoney,
    attemptId: uint64,
) {
    val body = SettlementMessage {
        queryId: attemptId,
        dealSalt: asset.dealSalt,
        action: ORACLE_ACTION_BUYER_REFUND,
    };
    recordOutboundAction(mutate progress, makeOutboundAction(
            OUTBOUND_KIND_BUYER_REFUND,
            asset.itemAddress,
            roles.buyer,
            roles.buyer,
            roles.buyer,
            attemptId,
            asset.dealSalt,
            attemptId,
            money.principalNanotons,
            money.principalNanotons,
            STATE_BUYER_REFUND_PENDING,
            PENDING_REFUND_RECONCILIATION,
            SETTLEMENT_RECONCILIATION_GRACE_SECONDS,
            body.toCell().hash(),
            OUTBOUND_STATUS_PENDING,
            0,
            0
        ));
    val refund = createMessage({
        bounce: BounceMode.RichBounce,
        value: money.principalNanotons,
        dest: roles.buyer,
        body,
    });
    refund.send(SEND_MODE_PAY_FEES_SEPARATELY + SEND_MODE_BOUNCE_ON_ACTION_FAIL);
}

fun sendSellerDeploymentRefund(
    mutate progress: DealProgress,
    roles: DealRoles,
    asset: DealAsset,
    money: DealMoney,
    queryId: uint64,
    expectedState: uint8,
) {
    val body = SettlementMessage {
        queryId,
        dealSalt: asset.dealSalt,
        action: SETTLEMENT_ACTION_SELLER_DEPLOYMENT_REFUND,
    };
    recordOutboundAction(mutate progress, makeOutboundAction(
            OUTBOUND_KIND_SELLER_DEPLOYMENT_REFUND,
            asset.itemAddress,
            roles.seller,
            roles.seller,
            roles.seller,
            queryId,
            asset.dealSalt,
            queryId,
            money.sellerDeploymentRefundNanotons,
            money.sellerDeploymentRefundNanotons,
            expectedState,
            PENDING_NONE,
            0,
            body.toCell().hash(),
            OUTBOUND_STATUS_PENDING,
            0,
            0
        ));
    val refund = createMessage({
        bounce: BounceMode.RichBounce,
        value: money.sellerDeploymentRefundNanotons,
        dest: roles.seller,
        body,
    });
    refund.send(SEND_MODE_PAY_FEES_SEPARATELY + SEND_MODE_BOUNCE_ON_ACTION_FAIL);
}

fun sendRemainingBalanceTo(
    mutate progress: DealProgress,
    recipient: address,
    asset: DealAsset,
    queryId: uint64,
    expectedState: uint8,
) {
    val body = SettlementMessage {
        queryId,
        dealSalt: asset.dealSalt,
        action: SETTLEMENT_ACTION_EXECUTION_RESERVE_REFUND,
    };
    recordOutboundAction(mutate progress, makeOutboundAction(
            OUTBOUND_KIND_EXECUTION_RESERVE_REFUND,
            asset.itemAddress,
            recipient,
            recipient,
            recipient,
            queryId,
            asset.dealSalt,
            queryId,
            0,
            0,
            expectedState,
            PENDING_NONE,
            0,
            body.toCell().hash(),
            OUTBOUND_STATUS_PENDING,
            0,
            0
        ));
    val refund = createMessage({
        bounce: BounceMode.RichBounce,
        value: 0,
        dest: recipient,
        body,
    });
    // BounceMode.RichBounce keeps the exact original body available for
    // action/destination/query correlation if the receiver rejects the refund.
    // SAFETY: terminal paths reserve TERMINAL_STORAGE_RESERVE before this
    // carry-all refund and fix the recipient to the snapshotted seller or buyer.
    // Principal and seller allowance are sent by separate, action-correlated messages.
    refund.send(
        SEND_MODE_CARRY_ALL_BALANCE
        + SEND_MODE_PAY_FEES_SEPARATELY
        + SEND_MODE_BOUNCE_ON_ACTION_FAIL
    );
}

// The principal is settled separately. Return the seller-funded deployment
// allowance, keep a small amount for terminal getters/storage, and send every
// other remaining nanotons (including unused buyer execution reserve) to buyer.
fun settleRemainingBalanceForBuyer(
    mutate progress: DealProgress,
    roles: DealRoles,
    asset: DealAsset,
    money: DealMoney,
) {
    val sellerRefundId = progress.startOracleAttempt();
    sendSellerDeploymentRefund(mutate progress, roles, asset, money, sellerRefundId, progress.state);

    reserveGramsOnBalance(TERMINAL_STORAGE_RESERVE, RESERVE_MODE_EXACT_AMOUNT);
    val buyerRefundId = progress.startOracleAttempt();
    sendRemainingBalanceTo(
        mutate progress,
        roles.buyer,
        asset,
        buyerRefundId,
        progress.state,
    );
}

// If the buyer never funded the deal, the NFT and the remaining TON are returned
// to the seller. Keep only the fixed terminal storage reserve.
fun settleExpiredBalanceForSeller(
    mutate progress: DealProgress,
    roles: DealRoles,
    asset: DealAsset,
) {
    reserveGramsOnBalance(TERMINAL_STORAGE_RESERVE, RESERVE_MODE_EXACT_AMOUNT);
    val sellerRefundId = progress.startOracleAttempt();
    sendRemainingBalanceTo(
        mutate progress,
        roles.seller,
        asset,
        sellerRefundId,
        progress.state,
    );
}

fun handleNftOwnershipNotification(
    senderAddress: address,
    msg: NotificationForNewOwner,
    storage: EscrowStorage,
) {
    var progress = storage.progress.load();
    val terms = storage.terms.load();
    assertTestnet(terms);
    val roles = terms.roles.load();
    val asset = terms.asset.load();
    val money = terms.money.load();

    // Only the exact item fixed in StateInit may alter this DealEscrow.
    // An unrelated NFT notification cannot be used as collateral.
    if (senderAddress != asset.itemAddress) {
        return;
    }

    val isExpectedDeposit = (
        progress.state == STATE_AWAITING_NFT
        && msg.oldOwnerAddress == roles.seller
        && msg.queryId == money.nftDepositQueryId
        && blockchain.now() <= progress.deadlineUnix
    );
    val isExpectedBuyerReturn = (
        progress.state == STATE_DISPUTED
        && progress.disputePhase == DISPUTE_PHASE_POST_DELIVERY
        && !progress.nftInEscrow
        && msg.oldOwnerAddress == roles.buyer
        && msg.queryId == money.nftReturnToEscrowQueryId
        && blockchain.now() <= progress.deadlineUnix
    );

    if (
        (isExpectedDeposit || isExpectedBuyerReturn)
        && hasValidInlineNftPayload(msg.payload, asset)
    ) {
        progress.nftInEscrow = true;
        if (isExpectedDeposit) {
            progress.state = STATE_AWAITING_BUYER_FUNDS;
            progress.deadlineUnix = (blockchain.now() + BUYER_FUNDING_WINDOW_SECONDS) as uint64;
        } else {
            // Exact configured item is back in escrow; resolver authorization
            // remains required before the NFT or principal can move.
            progress.deadlineUnix = (blockchain.now() + ARBITRATION_WINDOW_SECONDS) as uint64;
        }
        storage.progress = progress.toCell();
        storage.save();
        return;
    }

    // TEP-62 ownership has already changed before ownership_assigned is emitted.
    // Never revert a malformed callback from the snapshotted item: doing so would
    // leave the NFT owned by this escrow with no recovery information.
    progress.nftInEscrow = true;
    var recovery = progress.recovery.load();
    recovery.unexpectedItemAddress = senderAddress;
    recovery.unexpectedPreviousOwner = msg.oldOwnerAddress;
    progress.recovery = recovery.toCell();
    progress = asManualReview(progress);
    storage.progress = progress.toCell();
    storage.save();
}

fun handleOracleAttestation(msg: OracleAttestation, storage: EscrowStorage) {
    var progress = storage.progress.load();
    assert (
        progress.deadlineUnix > 0
        && blockchain.now() <= progress.deadlineUnix
    ) throw Errors.Deadline;
    val terms = storage.terms.load();
    assertTestnet(terms);

    val roles = terms.roles.load();
    val asset = terms.asset.load();
    val money = terms.money.load();
    val security = terms.security.load();

    val data = msg.data.load();
    val context = data.context.load();
    val route = data.route.load();
    val position = data.position.load();
    val hashes = data.hashes.load();

    assert (context.domain == ESCROW_DOMAIN) throw Errors.InvalidAttestation;
    assert (context.protocolVersion == terms.protocolVersion) throw Errors.InvalidAttestation;
    assert (context.networkId == TESTNET_NETWORK_ID) throw Errors.InvalidAttestation;
    assert (context.escrowAddress == contract.getAddress()) throw Errors.InvalidAttestation;
    assert (context.dealSalt == asset.dealSalt) throw Errors.InvalidAttestation;
    assert (context.attemptId > 0) throw Errors.InvalidAttestation;
    assert (context.attemptId == progress.oracleAttemptId) throw Errors.InvalidAttestation;
    assert (route.queryId == progress.oracleAttemptId) throw Errors.InvalidAttestation;
    if (context.action == ORACLE_ACTION_UNEXPECTED_NFT_RECOVERED) {
        val recovery = progress.recovery.load();
        assert (recovery.unexpectedItemAddress != null) throw Errors.InvalidAttestation;
        assert (route.itemAddress == recovery.unexpectedItemAddress) throw Errors.InvalidAttestation;
    } else {
        assert (route.itemAddress == asset.itemAddress) throw Errors.InvalidAttestation;
    }
    assert (position.masterchainSeqno > 0) throw Errors.InvalidAttestation;
    assert (position.logicalTime > 0) throw Errors.InvalidAttestation;
    assert (hashes.messageHash != 0 && hashes.traceHash != 0 && hashes.evidenceHash != 0)
        throw Errors.InvalidAttestation;

    val digest = msg.data.hash();
    val oracleKeys = security.oracleKeys.load();
    val signatureCount = countValidOracleSignatures(digest, oracleKeys, msg.signatures.load());
    assert (signatureCount >= 2) throw Errors.InvalidSignatures;

    var evidence = progress.evidence.load();
    evidence.lastEvidenceHash = hashes.evidenceHash;
    progress.evidence = evidence.toCell();

    if (context.action == ORACLE_ACTION_NFT_DELIVERED) {
        assert (progress.state == STATE_NFT_RELEASE_PENDING) throw Errors.InvalidState;
        assert (route.sourceAddress == contract.getAddress()) throw Errors.InvalidAttestation;
        assert (route.destinationAddress == roles.buyer) throw Errors.InvalidAttestation;
        assert (route.amountNanotons == 0) throw Errors.InvalidAttestation;
        assert (consumeOutboundAction(
            mutate progress,
            OUTBOUND_KIND_NFT_RELEASE,
            route.itemAddress,
            route.destinationAddress,
            route.queryId,
            0,
            false,
        )) throw Errors.OutboundActionMissing;
        progress.nftInEscrow = false;
        if (progress.pendingAction == PENDING_PAYOUT_AFTER_NFT_DELIVERY) {
            val payoutAttemptId = progress.startOracleAttempt();
            sendSellerPayout(mutate progress, roles, asset, money, payoutAttemptId);
            progress.state = STATE_SELLER_PAYOUT_PENDING;
            progress.pendingAction = PENDING_PAYOUT_RECONCILIATION;
            progress.deadlineUnix = (blockchain.now() + SETTLEMENT_RECONCILIATION_GRACE_SECONDS) as uint64;
        } else {
            progress.state = STATE_DELIVERED_DISPUTE_WINDOW;
            progress.pendingAction = PENDING_NONE;
            progress.disputePhase = DISPUTE_PHASE_NONE;
            progress.deadlineUnix = (blockchain.now() + POST_DELIVERY_DISPUTE_WINDOW_SECONDS) as uint64;
        }
    } else if (context.action == ORACLE_ACTION_NFT_RETURNED_TO_SELLER) {
        assert (progress.state == STATE_NFT_RETURN_PENDING) throw Errors.InvalidState;
        assert (route.sourceAddress == contract.getAddress()) throw Errors.InvalidAttestation;
        assert (route.destinationAddress == roles.seller) throw Errors.InvalidAttestation;
        assert (route.amountNanotons == 0) throw Errors.InvalidAttestation;
        assert (route.queryId == context.attemptId) throw Errors.InvalidAttestation;
        assert (consumeOutboundAction(
            mutate progress,
            OUTBOUND_KIND_NFT_RETURN,
            route.itemAddress,
            route.destinationAddress,
            route.queryId,
            0,
            false,
        )) throw Errors.OutboundActionMissing;
        progress.nftInEscrow = false;
        if (progress.pendingAction == PENDING_EXPIRE_AFTER_NFT_RETURN) {
            progress.state = STATE_EXPIRED;
            progress.pendingAction = PENDING_NONE;
            progress.principalLocked = false;
            progress.deadlineUnix = 0;
            settleExpiredBalanceForSeller(mutate progress, roles, asset);
        } else if (progress.pendingAction == PENDING_REFUND_AFTER_NFT_RETURN) {
            val refundAttemptId = progress.startOracleAttempt();
            sendBuyerRefund(mutate progress, roles, asset, money, refundAttemptId);
            progress.state = STATE_BUYER_REFUND_PENDING;
            progress.pendingAction = PENDING_REFUND_RECONCILIATION;
            progress.deadlineUnix = (blockchain.now() + SETTLEMENT_RECONCILIATION_GRACE_SECONDS) as uint64;
        } else {
            throw Errors.InvalidState;
        }
    } else if (context.action == ORACLE_ACTION_SELLER_PAYOUT) {
        assert (progress.state == STATE_SELLER_PAYOUT_PENDING) throw Errors.InvalidState;
        assert (progress.pendingAction == PENDING_PAYOUT_RECONCILIATION) throw Errors.InvalidState;
        assert (route.sourceAddress == contract.getAddress()) throw Errors.InvalidAttestation;
        assert (route.destinationAddress == roles.seller) throw Errors.InvalidAttestation;
        assert (route.amountNanotons == money.principalNanotons) throw Errors.InvalidAttestation;
        assert (consumeOutboundAction(
            mutate progress,
            OUTBOUND_KIND_SELLER_PAYOUT,
            route.itemAddress,
            route.destinationAddress,
            route.queryId,
            route.amountNanotons,
            true,
        )) throw Errors.OutboundActionMissing;
        progress.state = STATE_SETTLED;
        progress.pendingAction = PENDING_NONE;
        progress.principalLocked = false;
        progress.deadlineUnix = 0;
        settleRemainingBalanceForBuyer(mutate progress, roles, asset, money);
    } else if (context.action == ORACLE_ACTION_BUYER_REFUND) {
        assert (progress.state == STATE_BUYER_REFUND_PENDING) throw Errors.InvalidState;
        assert (progress.pendingAction == PENDING_REFUND_RECONCILIATION) throw Errors.InvalidState;
        assert (route.sourceAddress == contract.getAddress()) throw Errors.InvalidAttestation;
        assert (route.destinationAddress == roles.buyer) throw Errors.InvalidAttestation;
        assert (route.amountNanotons == money.principalNanotons) throw Errors.InvalidAttestation;
        assert (consumeOutboundAction(
            mutate progress,
            OUTBOUND_KIND_BUYER_REFUND,
            route.itemAddress,
            route.destinationAddress,
            route.queryId,
            route.amountNanotons,
            true,
        )) throw Errors.OutboundActionMissing;
        progress.state = STATE_REFUNDED;
        progress.pendingAction = PENDING_NONE;
        progress.principalLocked = false;
        progress.deadlineUnix = 0;
        settleRemainingBalanceForBuyer(mutate progress, roles, asset, money);
    } else if (context.action == ORACLE_ACTION_UNEXPECTED_NFT_RECOVERED) {
        assert (progress.state == STATE_NFT_RETURN_PENDING) throw Errors.InvalidState;
        assert (progress.pendingAction == PENDING_UNEXPECTED_RECOVERY) throw Errors.InvalidState;
        assert (route.sourceAddress == contract.getAddress()) throw Errors.InvalidAttestation;
        val recovery = progress.recovery.load();
        assert (recovery.unexpectedPreviousOwner != null) throw Errors.InvalidState;
        assert (route.destinationAddress == recovery.unexpectedPreviousOwner) throw Errors.InvalidAttestation;
        assert (route.amountNanotons == 0) throw Errors.InvalidAttestation;
        assert (route.queryId == context.attemptId) throw Errors.InvalidAttestation;
        assert (consumeOutboundAction(
            mutate progress,
            OUTBOUND_KIND_UNEXPECTED_NFT_RECOVERY,
            route.itemAddress,
            route.destinationAddress,
            route.queryId,
            0,
            false,
        )) throw Errors.OutboundActionMissing;
        progress.nftInEscrow = false;
        progress.state = STATE_MANUAL_REVIEW;
        progress.pendingAction = PENDING_NONE;
        progress.deadlineUnix = 0;
        var clearedRecovery = progress.recovery.load();
        clearedRecovery.unexpectedPreviousOwner = null;
        clearedRecovery.unexpectedItemAddress = null;
        progress.recovery = clearedRecovery.toCell();
    } else {
        throw Errors.InvalidAttestation;
    }

    storage.progress = progress.toCell();
    storage.save();
}

fun handleDisputeResolution(msg: ResolveDispute, storage: EscrowStorage) {
    var progress = storage.progress.load();
    assert (
        progress.deadlineUnix > 0
        && blockchain.now() <= progress.deadlineUnix
    ) throw Errors.Deadline;
    val terms = storage.terms.load();
    assertTestnet(terms);

    val roles = terms.roles.load();
    val asset = terms.asset.load();
    val money = terms.money.load();
    val security = terms.security.load();
    val context = msg.data.load().context.load();

    assert (progress.state == STATE_DISPUTED) throw Errors.InvalidState;
    assert (progress.nftInEscrow) throw Errors.InvalidState;
    assert (context.domain == ESCROW_DOMAIN) throw Errors.InvalidAttestation;
    assert (context.protocolVersion == terms.protocolVersion) throw Errors.InvalidAttestation;
    assert (context.networkId == TESTNET_NETWORK_ID) throw Errors.InvalidAttestation;
    assert (context.escrowAddress == contract.getAddress()) throw Errors.InvalidAttestation;
    assert (context.dealSalt == asset.dealSalt) throw Errors.InvalidAttestation;
    assert (context.disputePhase == progress.disputePhase) throw Errors.InvalidAttestation;
    assert (context.evidenceHash == progress.evidence.load().disputeReasonHash)
        throw Errors.InvalidAttestation;
    assert (context.attemptId > 0) throw Errors.InvalidAttestation;
    assert (context.attemptId == progress.disputeAttemptId) throw Errors.InvalidAttestation;

    val digest = msg.data.hash();
    val resolverKeys = security.resolverKeys.load();
    val signatureCount = countValidResolverSignatures(digest, resolverKeys, msg.signatures.load());
    assert (signatureCount >= 2) throw Errors.InvalidSignatures;

    if (context.outcome == RESOLUTION_BUYER_WINS) {
        // The exact item is already held by this contract (pre-delivery dispute)
        // or has been returned by the buyer (post-delivery dispute).
        val returnAttemptId = progress.startOracleAttempt();
        sendNftTo(
            mutate progress,
            OUTBOUND_KIND_NFT_RETURN,
            asset.itemAddress,
            roles.seller,
            roles.seller,
            returnAttemptId,
            asset,
            money.nftTransferValue,
            STATE_NFT_RETURN_PENDING,
            PENDING_REFUND_AFTER_NFT_RETURN,
            DELIVERY_CONFIRMATION_GRACE_SECONDS,
        );
        progress.state = STATE_NFT_RETURN_PENDING;
        progress.pendingAction = PENDING_REFUND_AFTER_NFT_RETURN;
        progress.deadlineUnix = (blockchain.now() + DELIVERY_CONFIRMATION_GRACE_SECONDS) as uint64;
    } else if (context.outcome == RESOLUTION_SELLER_WINS) {
        val releaseAttemptId = progress.startOracleAttempt();
        sendNftTo(
            mutate progress,
            OUTBOUND_KIND_NFT_RELEASE,
            asset.itemAddress,
            roles.buyer,
            roles.seller,
            releaseAttemptId,
            asset,
            money.nftTransferValue,
            STATE_NFT_RELEASE_PENDING,
            PENDING_PAYOUT_AFTER_NFT_DELIVERY,
            DELIVERY_CONFIRMATION_GRACE_SECONDS,
        );
        progress.state = STATE_NFT_RELEASE_PENDING;
        progress.pendingAction = PENDING_PAYOUT_AFTER_NFT_DELIVERY;
        progress.deadlineUnix = (blockchain.now() + DELIVERY_CONFIRMATION_GRACE_SECONDS) as uint64;
    } else {
        throw Errors.InvalidAttestation;
    }

    storage.progress = progress.toCell();
    storage.save();
}

fun retryBouncedOutboundAction(
    mutate progress: DealProgress,
    action: OutboundAction,
    roles: DealRoles,
    asset: DealAsset,
    money: DealMoney,
) {
    assert (action.status == OUTBOUND_STATUS_BOUNCED) throw Errors.RetryNotReady;
    val retryAttemptId = progress.startOracleAttempt();

    val addresses = action.addresses.load();
    val itemAndDestination = addresses.itemAndDestination.load();
    val recipientAndResponse = addresses.recipientAndResponse.load();
    if (action.kind <= OUTBOUND_KIND_BUYER_REFUND) {
        progress.state = action.expectedState;
        progress.pendingAction = action.expectedPendingAction;
        progress.deadlineUnix = (
            blockchain.now() + action.retryWindowSeconds
        ) as uint64;
    }

    if (
        action.kind == OUTBOUND_KIND_NFT_RELEASE
        || action.kind == OUTBOUND_KIND_NFT_RETURN
        || action.kind == OUTBOUND_KIND_UNEXPECTED_NFT_RECOVERY
    ) {
        sendNftTo(
            mutate progress,
            action.kind,
            itemAndDestination.first,
            recipientAndResponse.first,
            recipientAndResponse.second,
            retryAttemptId,
            asset,
            action.amountNanotons,
            action.expectedState,
            action.expectedPendingAction,
            action.retryWindowSeconds,
        );
    } else if (action.kind == OUTBOUND_KIND_SELLER_PAYOUT) {
        sendSellerPayout(mutate progress, roles, asset, money, retryAttemptId);
    } else if (action.kind == OUTBOUND_KIND_BUYER_REFUND) {
        sendBuyerRefund(mutate progress, roles, asset, money, retryAttemptId);
    } else if (action.kind == OUTBOUND_KIND_SELLER_DEPLOYMENT_REFUND) {
        sendSellerDeploymentRefund(
            mutate progress,
            roles,
            asset,
            money,
            retryAttemptId,
            action.expectedState,
        );
    } else if (action.kind == OUTBOUND_KIND_EXECUTION_RESERVE_REFUND) {
        sendRemainingBalanceTo(
            mutate progress,
            recipientAndResponse.first,
            asset,
            retryAttemptId,
            action.expectedState,
        );
    } else {
        throw Errors.OutboundActionMissing;
    }
}

fun onInternalMessage(in: InMessage) {
    if (in.body.isEmpty()) {
        return;
    }

    val msg = lazy AllowedMessage.fromSlice(in.body);
    var storage = EscrowStorage.load();

    match (msg) {
        ActivateDeal => {
            requireActionValue(in.valueCoins);
            var progress = storage.progress.load();
            val terms = storage.terms.load();
            assertTestnet(terms);
            validateTerms(terms);
            val roles = terms.roles.load();
            val asset = terms.asset.load();
            val money = terms.money.load();
            checkDealSalt(asset, msg.dealSalt);
            assert (contract.getOriginalBalance() >= (
                in.valueCoins + money.sellerDeploymentRefundNanotons + TERMINAL_STORAGE_RESERVE
            )) throw Errors.InvalidValue;
            assert (in.senderAddress == roles.seller) throw Errors.NotSeller;
            assert (progress.state == STATE_INTENT_CREATED) throw Errors.InvalidState;
            progress.state = STATE_AWAITING_NFT;
            progress.deadlineUnix = (blockchain.now() + SELLER_DEPOSIT_WINDOW_SECONDS) as uint64;
            storage.progress = progress.toCell();
            storage.save();
        }
        FundDeal => {
            requireActionValue(in.valueCoins);
            var progress = storage.progress.load();
            val terms = storage.terms.load();
            assertTestnet(terms);
            val roles = terms.roles.load();
            val asset = terms.asset.load();
            val money = terms.money.load();
            checkDealSalt(asset, msg.dealSalt);
            assert (in.senderAddress == roles.buyer) throw Errors.NotBuyer;
            assert (progress.state == STATE_AWAITING_BUYER_FUNDS) throw Errors.InvalidState;
            assert (blockchain.now() <= progress.deadlineUnix) throw Errors.Deadline;
            assert (msg.queryId == money.fundQueryId) throw Errors.InvalidDeal;
            assert (progress.nftInEscrow) throw Errors.InvalidNft;
            assert (!progress.principalLocked) throw Errors.InvalidState;
            assert (in.valueCoins == money.principalNanotons + money.executionReserve)
                throw Errors.InvalidValue;
            progress.principalLocked = true;
            progress.state = STATE_FUNDED_REVIEW;
            progress.deadlineUnix = (blockchain.now() + BUYER_REVIEW_WINDOW_SECONDS) as uint64;
            storage.progress = progress.toCell();
            storage.save();
        }
        AcceptDeal => {
            requireActionValue(in.valueCoins);
            var progress = storage.progress.load();
            val terms = storage.terms.load();
            assertTestnet(terms);
            val roles = terms.roles.load();
            val asset = terms.asset.load();
            val money = terms.money.load();
            checkDealSalt(asset, msg.dealSalt);
            assert (in.senderAddress == roles.buyer) throw Errors.NotBuyer;
            assert (progress.state == STATE_FUNDED_REVIEW) throw Errors.InvalidState;
            assert (blockchain.now() <= progress.deadlineUnix) throw Errors.Deadline;
            assert (progress.principalLocked && progress.nftInEscrow) throw Errors.InvalidState;
            assert (msg.queryId == money.nftReleaseQueryId) throw Errors.InvalidDeal;

            val releaseAttemptId = progress.startOracleAttempt();
            sendNftTo(
                mutate progress,
                OUTBOUND_KIND_NFT_RELEASE,
                asset.itemAddress,
                roles.buyer,
                roles.seller,
                releaseAttemptId,
                asset,
                money.nftTransferValue,
                STATE_NFT_RELEASE_PENDING,
                PENDING_NONE,
                DELIVERY_CONFIRMATION_GRACE_SECONDS,
            );
            progress.state = STATE_NFT_RELEASE_PENDING;
            progress.deadlineUnix = (blockchain.now() + DELIVERY_CONFIRMATION_GRACE_SECONDS) as uint64;
            progress.pendingAction = PENDING_NONE;
            storage.progress = progress.toCell();
            storage.save();
        }
        OpenDispute => {
            requireActionValue(in.valueCoins);
            var progress = storage.progress.load();
            val terms = storage.terms.load();
            assertTestnet(terms);
            val roles = terms.roles.load();
            val asset = terms.asset.load();
            checkDealSalt(asset, msg.dealSalt);
            assert (in.senderAddress == roles.buyer) throw Errors.NotBuyer;
            assert (msg.reasonHash != 0 && msg.queryId != 0) throw Errors.InvalidDeal;
            assert (progress.principalLocked) throw Errors.InvalidState;

            if (progress.state == STATE_FUNDED_REVIEW) {
                assert (blockchain.now() <= progress.deadlineUnix) throw Errors.Deadline;
                assert (progress.nftInEscrow) throw Errors.InvalidNft;
                progress.disputePhase = DISPUTE_PHASE_PRE_DELIVERY;
            } else if (progress.state == STATE_DELIVERED_DISPUTE_WINDOW) {
                assert (blockchain.now() <= progress.deadlineUnix) throw Errors.Deadline;
                assert (!progress.nftInEscrow) throw Errors.InvalidNft;
                progress.disputePhase = DISPUTE_PHASE_POST_DELIVERY;
            } else {
                throw Errors.InvalidState;
            }

            assert (progress.disputeAttemptId < 0xffffffffffffffff)
                throw Errors.InvalidAttestation;
            progress.disputeAttemptId += 1;
            progress.state = STATE_DISPUTED;
            var evidence = progress.evidence.load();
            evidence.disputeReasonHash = msg.reasonHash;
            progress.evidence = evidence.toCell();
            progress.deadlineUnix = (
                blockchain.now()
                + (progress.disputePhase == DISPUTE_PHASE_POST_DELIVERY
                    ? POST_DELIVERY_NFT_RETURN_WINDOW_SECONDS
                    : ARBITRATION_WINDOW_SECONDS)
            ) as uint64;
            storage.progress = progress.toCell();
            storage.save();
        }
        OracleAttestation => {
            requireActionValue(in.valueCoins);
            handleOracleAttestation(msg, storage);
        }
        ResolveDispute => {
            requireActionValue(in.valueCoins);
            handleDisputeResolution(msg, storage);
        }
        TimeoutDeal => {
            requireActionValue(in.valueCoins);
            var progress = storage.progress.load();
            val terms = storage.terms.load();
            assertTestnet(terms);
            val asset = terms.asset.load();
            val roles = terms.roles.load();
            val money = terms.money.load();
            checkDealSalt(asset, msg.dealSalt);
            assert (msg.queryId != 0) throw Errors.InvalidDeal;
            assert (progress.deadlineUnix != 0 && blockchain.now() > progress.deadlineUnix)
                throw Errors.Deadline;

            if (progress.state == STATE_AWAITING_NFT) {
                progress.state = STATE_EXPIRED;
                progress.deadlineUnix = 0;
                settleExpiredBalanceForSeller(mutate progress, roles, asset);
            } else if (progress.state == STATE_AWAITING_BUYER_FUNDS) {
                assert (progress.nftInEscrow) throw Errors.InvalidNft;
                val returnAttemptId = progress.startOracleAttempt();
                sendNftTo(
                    mutate progress,
                    OUTBOUND_KIND_NFT_RETURN,
                    asset.itemAddress,
                    roles.seller,
                    roles.seller,
                    returnAttemptId,
                    asset,
                    money.nftTransferValue,
                    STATE_NFT_RETURN_PENDING,
                    PENDING_EXPIRE_AFTER_NFT_RETURN,
                    DELIVERY_CONFIRMATION_GRACE_SECONDS,
                );
                progress.state = STATE_NFT_RETURN_PENDING;
                progress.pendingAction = PENDING_EXPIRE_AFTER_NFT_RETURN;
                progress.deadlineUnix = (blockchain.now() + DELIVERY_CONFIRMATION_GRACE_SECONDS) as uint64;
            } else if (progress.state == STATE_FUNDED_REVIEW) {
                assert (progress.principalLocked && progress.nftInEscrow) throw Errors.InvalidState;
                val returnAttemptId = progress.startOracleAttempt();
                sendNftTo(
                    mutate progress,
                    OUTBOUND_KIND_NFT_RETURN,
                    asset.itemAddress,
                    roles.seller,
                    roles.seller,
                    returnAttemptId,
                    asset,
                    money.nftTransferValue,
                    STATE_NFT_RETURN_PENDING,
                    PENDING_REFUND_AFTER_NFT_RETURN,
                    DELIVERY_CONFIRMATION_GRACE_SECONDS,
                );
                progress.state = STATE_NFT_RETURN_PENDING;
                progress.pendingAction = PENDING_REFUND_AFTER_NFT_RETURN;
                progress.deadlineUnix = (blockchain.now() + DELIVERY_CONFIRMATION_GRACE_SECONDS) as uint64;
            } else if (progress.state == STATE_DELIVERED_DISPUTE_WINDOW) {
                assert (progress.principalLocked && !progress.nftInEscrow) throw Errors.InvalidState;
                val payoutAttemptId = progress.startOracleAttempt();
                sendSellerPayout(mutate progress, roles, asset, money, payoutAttemptId);
                progress.state = STATE_SELLER_PAYOUT_PENDING;
                progress.pendingAction = PENDING_PAYOUT_RECONCILIATION;
                progress.deadlineUnix = (blockchain.now() + SETTLEMENT_RECONCILIATION_GRACE_SECONDS) as uint64;
            } else {
                progress = asManualReview(progress);
            }
            storage.progress = progress.toCell();
            storage.save();
        }
        RetryFailedOutboundAction => {
            requireActionValue(in.valueCoins);
            var progress = storage.progress.load();
            val terms = storage.terms.load();
            assertTestnet(terms);
            val roles = terms.roles.load();
            val asset = terms.asset.load();
            val money = terms.money.load();
            checkDealSalt(asset, msg.dealSalt);

            var actions = progress.outboundActions.load();
            if (actions.first != null && actions.first.load().queryId == msg.queryId) {
                val action = actions.first.load();
                val recipient = action.addresses.load().recipientAndResponse.load().first;
                assert (action.dealSalt == msg.dealSalt) throw Errors.InvalidDeal;
                assert (action.status == OUTBOUND_STATUS_BOUNCED) throw Errors.RetryNotReady;
                assert (in.senderAddress == recipient) throw Errors.UnauthorizedRetry;
                actions.first = null;
                progress.outboundActions = actions.toCell();
                retryBouncedOutboundAction(mutate progress, action, roles, asset, money);
            } else if (actions.second != null && actions.second.load().queryId == msg.queryId) {
                val action = actions.second.load();
                val recipient = action.addresses.load().recipientAndResponse.load().first;
                assert (action.dealSalt == msg.dealSalt) throw Errors.InvalidDeal;
                assert (action.status == OUTBOUND_STATUS_BOUNCED) throw Errors.RetryNotReady;
                assert (in.senderAddress == recipient) throw Errors.UnauthorizedRetry;
                actions.second = null;
                progress.outboundActions = actions.toCell();
                retryBouncedOutboundAction(mutate progress, action, roles, asset, money);
            } else {
                throw Errors.OutboundActionMissing;
            }
            storage.progress = progress.toCell();
            storage.save();
        }
        RecoverUnexpectedNft => {
            requireActionValue(in.valueCoins);
            var progress = storage.progress.load();
            val terms = storage.terms.load();
            assertTestnet(terms);
            val asset = terms.asset.load();
            val money = terms.money.load();
            assert (progress.state == STATE_MANUAL_REVIEW) throw Errors.InvalidState;
            assert (msg.dealSalt == asset.dealSalt) throw Errors.InvalidDeal;
            val recovery = progress.recovery.load();
            assert (recovery.unexpectedItemAddress != null) throw Errors.NothingToRecover;
            assert (recovery.unexpectedPreviousOwner != null) throw Errors.NothingToRecover;
            assert (progress.nftInEscrow) throw Errors.NothingToRecover;
            val previousOwner = recovery.unexpectedPreviousOwner;
            assert (in.senderAddress == previousOwner) throw Errors.NotAuthorized;
            val unexpectedItem = recovery.unexpectedItemAddress;
            val recoveryAttemptId = progress.startOracleAttempt();
            sendNftTo(
                mutate progress,
                OUTBOUND_KIND_UNEXPECTED_NFT_RECOVERY,
                unexpectedItem,
                previousOwner,
                previousOwner,
                recoveryAttemptId,
                asset,
                money.nftTransferValue,
                STATE_NFT_RETURN_PENDING,
                PENDING_UNEXPECTED_RECOVERY,
                DELIVERY_CONFIRMATION_GRACE_SECONDS,
            );
            progress.state = STATE_NFT_RETURN_PENDING;
            progress.pendingAction = PENDING_UNEXPECTED_RECOVERY;
            progress.deadlineUnix = (blockchain.now() + DELIVERY_CONFIRMATION_GRACE_SECONDS) as uint64;
            storage.progress = progress.toCell();
            storage.save();
        }
        NotificationForNewOwner => {
            handleNftOwnershipNotification(in.senderAddress, msg, storage);
        }
        else => {
            assert (in.body.isEmpty()) throw Errors.UnexpectedMessage;
        }
    }
}

fun onBouncedMessage(in: InMessageBounced) {
    // All contract-created outbound messages use RichBounce. The returned
    // original body hash, bounce sender and original value must match an
    // explicitly persisted descriptor; unrelated and stale bounces are ignored.
    val rich = lazy RichBounceBody.fromSlice(in.bouncedBody);
    val originalBodyHash = rich.originalBody.hash();
    val originalValue = rich.originalInfo.load().valueCoins;

    var storage = EscrowStorage.load();
    var progress = storage.progress.load();
    var actions = progress.outboundActions.load();
    var matched = false;
    var criticalAction = false;

    if (actions.first != null) {
        var action = actions.first.load();
        val destination = action.addresses.load().itemAndDestination.load().second;
        if (
            action.status == OUTBOUND_STATUS_PENDING
            && destination == in.senderAddress
            && action.messageBodyHash == originalBodyHash
            && (
                action.kind == OUTBOUND_KIND_EXECUTION_RESERVE_REFUND
                || action.messageValueNanotons == originalValue
            )
        ) {
            action.status = OUTBOUND_STATUS_BOUNCED;
            action.bouncePhase = rich.bouncedByPhase;
            action.exitCode = rich.exitCode;
            actions.first = action.toCell();
            matched = true;
            criticalAction = action.kind <= OUTBOUND_KIND_BUYER_REFUND;
            if (criticalAction && progress.state == action.expectedState) {
                progress = asManualReview(progress);
            }
        }
    }

    if (!matched && actions.second != null) {
        var action = actions.second.load();
        val destination = action.addresses.load().itemAndDestination.load().second;
        if (
            action.status == OUTBOUND_STATUS_PENDING
            && destination == in.senderAddress
            && action.messageBodyHash == originalBodyHash
            && (
                action.kind == OUTBOUND_KIND_EXECUTION_RESERVE_REFUND
                || action.messageValueNanotons == originalValue
            )
        ) {
            action.status = OUTBOUND_STATUS_BOUNCED;
            action.bouncePhase = rich.bouncedByPhase;
            action.exitCode = rich.exitCode;
            actions.second = action.toCell();
            matched = true;
            criticalAction = action.kind <= OUTBOUND_KIND_BUYER_REFUND;
            if (criticalAction && progress.state == action.expectedState) {
                progress = asManualReview(progress);
            }
        }
    }

    if (matched) {
        progress.outboundActions = actions.toCell();
        storage.progress = progress.toCell();
        storage.save();
    }
}

get fun get_state(): uint8 {
    return EscrowStorage.load().progress.load().state;
}

get fun get_progress(): DealProgress {
    return EscrowStorage.load().progress.load();
}

get fun get_deal_terms(): DealTerms {
    return EscrowStorage.load().terms.load();
}

get fun get_oracle_keys(): AuthorityKeys {
    return EscrowStorage.load().terms.load().security.load().oracleKeys.load();
}

get fun get_resolver_keys(): AuthorityKeys {
    return EscrowStorage.load().terms.load().security.load().resolverKeys.load();
}
