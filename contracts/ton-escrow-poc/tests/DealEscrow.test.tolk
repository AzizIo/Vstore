import "@acton/emulation/config"
import "@acton/emulation/network"
import "@acton/emulation/testing"
import "@acton/crypto"
import "@acton/testing/expect"
import "@acton/types/transaction"

import "@contracts/types"
import "@contracts/signatures"
import "@wrappers/DealEscrow.gen"
import "@wrappers/TestNftItem.gen"

const TEST_SIGNER_A_SEED = 0x1111111111111111111111111111111111111111111111111111111111111111
const TEST_SIGNER_B_SEED = 0x2222222222222222222222222222222222222222222222222222222222222222
const TEST_SIGNER_C_SEED = 0x3333333333333333333333333333333333333333333333333333333333333333
const TEST_RESOLVER_A_SEED = 0x4444444444444444444444444444444444444444444444444444444444444444
const TEST_RESOLVER_B_SEED = 0x5555555555555555555555555555555555555555555555555555555555555555
const TEST_RESOLVER_C_SEED = 0x6666666666666666666666666666666666666666666666666666666666666666

const TEST_RESOLVER_A_KEY = 0xd759793bbc13a2819a827c76adb6fba8a49aee007f49f2d0992d99b825ad2c48
const TEST_RESOLVER_B_KEY = 0xc6822637c7d310ec57627be00ba259d253749f4aaf644470cffbe53a35f73242
const TEST_RESOLVER_C_KEY = 0x34b4d9043156cb6dcf0beb0a2949b7559c940d2bcb6dbe8c53a9b30278e3a746

const ZERO_SIGNATURE_BITS: bits512 = "00000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000000".hexToSlice() as bits512
const TEST_ED25519_DIGEST: uint256 = 0xabababababababababababababababababababababababababababababababab
const TEST_SIGNER_A_KEY: uint256 = 0xd04ab232742bb4ab3a1368bd4615e4e6d0224ab71a016baf8520a332c9778737
const TEST_SIGNER_B_KEY: uint256 = 0xa09aa5f47a6759802ff955f8dc2d2a14a5c99d23be97f864127ff9383455a4f0
const TEST_SIGNER_C_KEY: uint256 = 0x17cb79fb2b4120f2b1ec65e4198d6e08b28e813feb01e4a400839b85e18080ce
const TEST_ED25519_SIGNATURE_A: bits512 = "d263f4be3cf5941bc3c063f085a595e5e0c3b9d2ec9061af2f461e226bc0643b992bae6982f3e3e6bbc3034486e873e49ec6adcbb11c2062f39686d82110cb02".hexToSlice() as bits512
const TEST_ED25519_SIGNATURE_B: bits512 = "be9bf22e2e85ac1a0e7347407ccef4eb9822faceba5bcbc3faa18ae120ab11199fa3d727c4d4596b28b86ecc99e5e4795c73432c8af4f958214420d49b26cc06".hexToSlice() as bits512
const TEST_ED25519_SIGNATURE_C: bits512 = "f896b2a98036e2710dcfb423c87d39ea8c91df1a114d7bb9a6dafb6333bfbcd87b2239c2154216f3ba6140f16c0efdd03a16c60e9296242021c1725357e74000".hexToSlice() as bits512

fun configureTestnet() {
    val currentGlobalId = testing.getConfig().getParamRaw(19).beginParse().loadInt(32);
    if (currentGlobalId != TESTNET_GLOBAL_ID) {
        var config = testing.getConfig();
        config.setParamRaw(19, beginCell().storeInt(TESTNET_GLOBAL_ID, 32).endCell());
        assert (testing.setConfig(config)) throw Errors.NotTestnet;
    }
}

fun createFixture(
    salt: uint256,
    initialState: uint8 = STATE_INTENT_CREATED,
    oracleAttemptId: uint64 = 0,
    initialDeadlineUnix: uint64 = 0,
    initialNftInEscrow: bool = false,
    initialPrincipalLocked: bool = false,
    rejectRecipient: address? = null,
    sellerAddressOverride: address? = null,
): (DealEscrow, TestNftItem, Treasury, Treasury) {
    configureTestnet();
    val seller = testing.treasury("seller");
    val buyer = testing.treasury("buyer");
    val collection = testing.treasury("test-collection");
    val admin = testing.treasury("test-nft-policy-admin");
    var dealSeller = seller.address;
    if (sellerAddressOverride != null) {
        dealSeller = sellerAddressOverride;
    }
    val nftItem = TestNftItem.fromStorage({
        ownerAddress: seller.address,
        fixtureSalt: salt,
        policy: TestNftTransferPolicy {
            adminAddress: admin.address,
            rejectRecipient,
        }.toCell(),
    });

    val roles: DealRoles = {
        seller: dealSeller,
        buyer: buyer.address,
    };
    val asset: DealAsset = {
        itemAddress: nftItem.address,
        collectionAddress: collection.address,
        dealSalt: salt,
    };
    val money: DealMoney = {
        principalNanotons: grams("1"),
        executionReserve: grams("0.5"),
        sellerDeploymentRefundNanotons: grams("0.05"),
        nftTransferValue: grams("0.08"),
        fundQueryId: 1001,
        nftDepositQueryId: 1002,
        nftReleaseQueryId: 1003,
        nftReturnToEscrowQueryId: 1004,
    };
    val security: DealSecurity = {
        oracleKeys: AuthorityKeys {
            keyA: TEST_SIGNER_A_KEY,
            keyB: TEST_SIGNER_B_KEY,
            keyC: TEST_SIGNER_C_KEY,
        }.toCell(),
        resolverKeys: AuthorityKeys {
            keyA: TEST_RESOLVER_A_KEY,
            keyB: TEST_RESOLVER_B_KEY,
            keyC: TEST_RESOLVER_C_KEY,
        }.toCell(),
    };
    val terms: DealTerms = {
        roles: roles.toCell(),
        asset: asset.toCell(),
        money: money.toCell(),
        security: security.toCell(),
        networkId: TESTNET_NETWORK_ID,
        protocolVersion: PROTOCOL_VERSION,
    };
    var outboundActions: OutboundActionSet = {
        first: null,
        second: null,
    };
    if (initialState == STATE_NFT_RELEASE_PENDING) {
        val releasePayload = beginCell()
            .storeBool(false)
            .storeUint(NFT_FORWARD_MAGIC, 32)
            .storeUint(salt, 256)
            .toSlice();
        val releaseBody = NftTransfer {
            queryId: oracleAttemptId,
            newOwnerAddress: buyer.address,
            sendExcessesTo: seller.address,
            customPayload: null,
            forwardTonAmount: grams("0.01"),
            forwardPayload: releasePayload,
        };
        outboundActions.first = OutboundAction {
            kind: OUTBOUND_KIND_NFT_RELEASE,
            queryId: oracleAttemptId,
            dealSalt: salt,
            attemptId: oracleAttemptId,
            amountNanotons: grams("0.08"),
            messageValueNanotons: grams("0.08"),
            expectedState: STATE_NFT_RELEASE_PENDING,
            expectedPendingAction: PENDING_NONE,
            retryWindowSeconds: DELIVERY_CONFIRMATION_GRACE_SECONDS,
            messageBodyHash: releaseBody.toCell().hash(),
            status: OUTBOUND_STATUS_PENDING,
            bouncePhase: 0,
            exitCode: 0,
            addresses: OutboundActionAddresses {
                itemAndDestination: OutboundActionAddressPair {
                    first: nftItem.address,
                    second: nftItem.address,
                }.toCell(),
                recipientAndResponse: OutboundActionAddressPair {
                    first: buyer.address,
                    second: seller.address,
                }.toCell(),
            }.toCell(),
        }.toCell();
    }
    val progress: DealProgress = {
        state: initialState,
        deadlineUnix: initialDeadlineUnix,
        disputePhase: DISPUTE_PHASE_NONE,
        pendingAction: PENDING_NONE,
        nftInEscrow: initialNftInEscrow,
        principalLocked: initialPrincipalLocked,
        oracleAttemptId,
        disputeAttemptId: 0,
        evidence: DealEvidence {
            lastEvidenceHash: 0,
            disputeReasonHash: 0,
        }.toCell(),
        recovery: DealRecovery {
            unexpectedPreviousOwner: null,
            unexpectedItemAddress: null,
        }.toCell(),
        outboundActions: outboundActions.toCell(),
    };

    val escrow = DealEscrow.fromStorage({
        terms: terms.toCell(),
        progress: progress.toCell(),
    });
    return (escrow, nftItem, seller, buyer);
}

fun activateDeal(
    escrow: DealEscrow,
    seller: Treasury,
    salt: uint256,
) {
    val activate = escrow.sendActivateDeal(
        seller.address,
        1,
        salt,
        { value: grams("0.03"), bounce: true },
    );
    expect(activate).toHaveSuccessfulTx<ActivateDeal>({
        from: seller.address,
        to: escrow.address,
    });
}

fun deployAndActivate(
    escrow: DealEscrow,
    seller: Treasury,
    salt: uint256,
) {
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    activateDeal(escrow, seller, salt);
}

fun buildDepositBody(escrowAddress: address, sellerAddress: address, queryId: uint64, salt: uint256): cell {
    val payload = beginCell()
        .storeBool(false)
        .storeUint(NFT_FORWARD_MAGIC, 32)
        .storeUint(salt, 256)
        .endCell();

    return beginCell()
        .storeUint(0x5fcc3d14, 32)
        .storeUint(queryId, 64)
        .storeAddress(escrowAddress)
        .storeAddress(sellerAddress)
        .storeMaybeRef(null)
        .storeCoins(grams("0.02"))
        .storeSlice(payload.beginParse())
        .endCell();
}

fun depositExpectedNft(
    escrow: DealEscrow,
    nftItem: TestNftItem,
    seller: Treasury,
    salt: uint256,
) {
    val deposit = nftItem.sendAny(
        seller.address,
        buildDepositBody(escrow.address, seller.address, 1002, salt),
        { value: grams("0.12"), bounce: true },
    );
    expect(deposit).toHaveSuccessfulTx<NftTransfer>({
        from: seller.address,
        to: nftItem.address,
    });
    expect(deposit).toHaveTx<NotificationForNewOwner>({
        from: nftItem.address,
        to: escrow.address,
    });
}

fun buildOracleSignatures(data: cell): Cell<OracleSignatureSet> {
    return OracleSignatureSet {
        signatureA: Signature {
            data: crypto.rawSign(TEST_SIGNER_A_SEED, data.hash()) as bits512,
        }.toCell(),
        signatureB: Signature {
            data: crypto.rawSign(TEST_SIGNER_B_SEED, data.hash()) as bits512,
        }.toCell(),
        signatureC: Signature {
            data: crypto.rawSign(TEST_SIGNER_C_SEED, data.hash()) as bits512,
        }.toCell(),
    }.toCell();
}

fun buildResolverSignatures(data: cell): Cell<ResolverSignatureSet> {
    return ResolverSignatureSet {
        signatureA: Signature {
            data: crypto.rawSign(TEST_RESOLVER_A_SEED, data.hash()) as bits512,
        }.toCell(),
        signatureB: Signature {
            data: crypto.rawSign(TEST_RESOLVER_B_SEED, data.hash()) as bits512,
        }.toCell(),
        signatureC: Signature {
            data: crypto.rawSign(TEST_RESOLVER_C_SEED, data.hash()) as bits512,
        }.toCell(),
    }.toCell();
}

fun buildTestOracleAttestation(
    escrow: DealEscrow,
    salt: uint256,
    action: uint8,
    attemptId: uint64,
    itemAddress: address,
    sourceAddress: address,
    destinationAddress: address,
    amountNanotons: coins,
    queryId: uint64,
    evidenceHash: uint256,
    masterchainSeqno: uint32,
    logicalTime: uint64,
): OracleAttestation {
    val data: OracleAttestationData = {
        context: OracleContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: salt,
            action,
            attemptId,
        }.toCell(),
        route: OracleRoute {
            itemAddress,
            sourceAddress,
            destinationAddress,
            amountNanotons,
            queryId,
        }.toCell(),
        position: OraclePosition {
            masterchainSeqno,
            logicalTime,
        }.toCell(),
        hashes: OracleEvidenceHashes {
            messageHash: evidenceHash + 1,
            traceHash: evidenceHash + 2,
            evidenceHash,
        }.toCell(),
    };
    return OracleAttestation {
        data: data.toCell(),
        signatures: buildOracleSignatures(data.toCell()),
    };
}


fun buildTestResolverDecision(
    escrow: DealEscrow,
    salt: uint256,
    disputePhase: uint8,
    outcome: uint8,
    attemptId: uint64,
    evidenceHash: uint256,
): ResolveDispute {
    val decision: ResolverDecisionData = {
        context: ResolverDecisionContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: salt,
            disputePhase,
            outcome,
            attemptId,
            evidenceHash,
        }.toCell(),
    };
    return ResolveDispute {
        data: decision.toCell(),
        signatures: buildResolverSignatures(decision.toCell()),
    };
}


get fun `test deployment address is derived from immutable StateInit`() {
    val (escrowA, _, seller, _) = createFixture(0xA11CE);
    val (escrowB, _, _, _) = createFixture(0xA11CE);

    expect(escrowA.address).toEqual(escrowB.address);
    val deployResult = escrowA.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrowA.address });
    expect(escrowA.getState()).toEqual(STATE_INTENT_CREATED);
}

get fun `test seller activates a per-deal escrow`() {
    val (escrow, _, seller, _) = createFixture(0xA11CF);
    deployAndActivate(escrow, seller, 0xA11CF);
    expect(escrow.getState()).toEqual(STATE_AWAITING_NFT);
}

get fun `test only the snapshotted seller can activate the deal`() {
    val (escrow, _, seller, buyer) = createFixture(0xA11D0);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

    val badActivation = escrow.sendActivateDeal(
        buyer.address,
        1,
        0xA11D0,
        { value: grams("0.03"), bounce: true },
    );
    expect(badActivation).toHaveFailedTx<ActivateDeal>({
        from: buyer.address,
        to: escrow.address,
        exitCode: Errors.NotSeller,
    });
    expect(escrow.getState()).toEqual(STATE_INTENT_CREATED);
}

get fun `test exact TEP-62 item deposit unlocks buyer funding state`() {
    val (escrow, nftItem, seller, _) = createFixture(0xA11D1);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });

    activateDeal(escrow, seller, 0xA11D1);
    depositExpectedNft(escrow, nftItem, seller, 0xA11D1);
    expect(escrow.getState()).toEqual(STATE_AWAITING_BUYER_FUNDS);
}

get fun `test a different NFT item sender cannot unlock buyer funding`() {
    val (escrow, nftItem, seller, _) = createFixture(0xA11D2);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val realItemDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(realItemDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });
    activateDeal(escrow, seller, 0xA11D2);

    val fakeOwner = testing.treasury("fake-item-owner");
    val fakeItem = TestNftItem.fromStorage({ ownerAddress: fakeOwner.address, fixtureSalt: 0xA11D2 + 100 });
    val fakeDeploy = fakeItem.deploy(fakeOwner.address, { value: grams("0.05"), bounce: false });
    expect(fakeDeploy).toHaveSuccessfulDeploy({ to: fakeItem.address });
    val fakeDeposit = fakeItem.sendAny(
        fakeOwner.address,
        buildDepositBody(escrow.address, fakeOwner.address, 1002, 0xA11D2),
        { value: grams("0.12"), bounce: true },
    );
    expect(fakeDeposit).toHaveSuccessfulTx<NftTransfer>({
        from: fakeOwner.address,
        to: fakeItem.address,
    });
    expect(escrow.getState()).toEqual(STATE_AWAITING_NFT);
}

get fun `test buyer must attach exact principal plus execution reserve`() {
    val (escrow, nftItem, seller, buyer) = createFixture(0xA11D3);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });
    activateDeal(escrow, seller, 0xA11D3);
    depositExpectedNft(escrow, nftItem, seller, 0xA11D3);

    val invalidFunding = escrow.sendFundDeal(
        buyer.address,
        1001,
        0xA11D3,
        { value: grams("1.49"), bounce: true },
    );
    expect(invalidFunding).toHaveFailedTx<FundDeal>({
        from: buyer.address,
        to: escrow.address,
        exitCode: Errors.InvalidValue,
    });
    expect(escrow.getState()).toEqual(STATE_AWAITING_BUYER_FUNDS);

    val funding = escrow.sendFundDeal(
        buyer.address,
        1001,
        0xA11D3,
        { value: grams("1.5"), bounce: true },
    );
    expect(funding).toHaveSuccessfulTx<FundDeal>({
        from: buyer.address,
        to: escrow.address,
    });
    expect(escrow.getState()).toEqual(STATE_FUNDED_REVIEW);
}

get fun `test buyer acceptance is pre-delivery and participant scoped`() {
    val (escrow, nftItem, seller, buyer) = createFixture(0xA11D4);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });
    activateDeal(escrow, seller, 0xA11D4);
    depositExpectedNft(escrow, nftItem, seller, 0xA11D4);
    escrow.sendFundDeal(buyer.address, 1001, 0xA11D4, { value: grams("1.5"), bounce: true });

    val rejected = escrow.sendAcceptDeal(
        seller.address,
        1003,
        0xA11D4,
        { value: grams("0.03"), bounce: true },
    );
    expect(rejected).toHaveFailedTx<AcceptDeal>({
        from: seller.address,
        to: escrow.address,
        exitCode: Errors.NotBuyer,
    });
    expect(escrow.getState()).toEqual(STATE_FUNDED_REVIEW);

    val accepted = escrow.sendAcceptDeal(
        buyer.address,
        1003,
        0xA11D4,
        { value: grams("0.03"), bounce: true },
    );
    expect(accepted).toHaveSuccessfulTx<AcceptDeal>({
        from: buyer.address,
        to: escrow.address,
    });
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
    expect(nftItem.getOwner()).toEqual(buyer.address);
}

get fun `test observed NFT transfer alone never settles a deal`() {
    val (escrow, nftItem, seller, buyer) = createFixture(0xA11D5);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });
    activateDeal(escrow, seller, 0xA11D5);
    depositExpectedNft(escrow, nftItem, seller, 0xA11D5);
    escrow.sendFundDeal(buyer.address, 1001, 0xA11D5, { value: grams("1.5"), bounce: true });
    escrow.sendAcceptDeal(buyer.address, 1003, 0xA11D5, { value: grams("0.03"), bounce: true });

    expect(nftItem.getOwner()).toEqual(buyer.address);
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
}

get fun `test contract rejects activation on mainnet global id`() {
    val (escrow, _, seller, _) = createFixture(0xA11D6);

    var mainnetConfig = testing.getConfig();
    mainnetConfig.setParamRaw(19, beginCell().storeInt(-239, 32).endCell());
    assert (testing.setConfig(mainnetConfig)) throw Errors.NotTestnet;

    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

    val activation = escrow.sendActivateDeal(
        seller.address,
        1,
        0xA11D6,
        { value: grams("0.03"), bounce: true },
    );
    expect(activation).toHaveFailedTx<ActivateDeal>({
        from: seller.address,
        to: escrow.address,
        exitCode: Errors.NotTestnet,
    });
    expect(escrow.getState()).toEqual(STATE_INTENT_CREATED);
}

get fun `test stale oracle attempt cannot advance escrow state`() {
    testing.setNow(1_700_000_000);
    val (escrow, nftItem, seller, buyer) = createFixture(
        0xA11D7,
        STATE_NFT_RELEASE_PENDING,
        2,
        1_700_000_060,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

    val staleData: OracleAttestationData = {
        context: OracleContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: 0xA11D7,
            action: ORACLE_ACTION_NFT_DELIVERED,
            attemptId: 1,
        }.toCell(),
        route: OracleRoute {
            itemAddress: nftItem.address,
            sourceAddress: escrow.address,
            destinationAddress: buyer.address,
            amountNanotons: 0,
            queryId: 1,
        }.toCell(),
        position: OraclePosition {
            masterchainSeqno: 1,
            logicalTime: 1,
        }.toCell(),
        hashes: OracleEvidenceHashes {
            messageHash: 1,
            traceHash: 1,
            evidenceHash: 1,
        }.toCell(),
    };
    val dummySignature = Signature { data: ZERO_SIGNATURE_BITS }.toCell();
    val staleAttestation = OracleAttestation {
        data: staleData.toCell(),
        signatures: OracleSignatureSet {
            signatureA: dummySignature,
            signatureB: dummySignature,
            signatureC: dummySignature,
        }.toCell(),
    };

    val rejected = escrow.sendAny(
        seller.address,
        staleAttestation.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(rejected).toHaveFailedTx<OracleAttestation>({
        from: seller.address,
        to: escrow.address,
        exitCode: Errors.InvalidAttestation,
    });
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
}

get fun `test terminal payout returns unused execution reserve to buyer`() {
    val (escrow, nftItem, seller, buyer) = createFixture(
        0xA11D8,
        STATE_DELIVERED_DISPUTE_WINDOW,
        0,
        1,
        false,
        true,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

    val sellerBalanceBeforeSettlement = testing.getAccountBalance(seller.address);

    // Simulate the buyer's exact principal + execution-reserve funding.
    val buyerFunding = net.send(
        buyer.address,
        createMessage({
            bounce: false,
            value: grams("1.5"),
            dest: escrow.address,
            body: beginCell().endCell(),
        }),
    );
    expect(buyerFunding).toHaveSuccessfulTx({
        from: buyer.address,
        to: escrow.address,
    });
    val buyerBalanceAfterFunding = testing.getAccountBalance(buyer.address);

    val keeper = testing.treasury("reserve-oracle-keeper");
    val timeout = escrow.sendAny(
        keeper.address,
        TimeoutDeal {
            queryId: 77,
            dealSalt: 0xA11D8,
        }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(timeout).toHaveSuccessfulTx<TimeoutDeal>({
        from: keeper.address,
        to: escrow.address,
    });
    expect(escrow.getState()).toEqual(STATE_SELLER_PAYOUT_PENDING);

    val sellerBalanceAfterPayoutInitiated = testing.getAccountBalance(seller.address);
    expect(sellerBalanceAfterPayoutInitiated)
        .toBeGreater(sellerBalanceBeforeSettlement + grams("0.9"));
    val payoutData: OracleAttestationData = {
        context: OracleContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: 0xA11D8,
            action: ORACLE_ACTION_SELLER_PAYOUT,
            attemptId: 1,
        }.toCell(),
        route: OracleRoute {
            itemAddress: nftItem.address,
            sourceAddress: escrow.address,
            destinationAddress: seller.address,
            amountNanotons: grams("1"),
            queryId: 1,
        }.toCell(),
        position: OraclePosition {
            masterchainSeqno: 1,
            logicalTime: 1,
        }.toCell(),
        hashes: OracleEvidenceHashes {
            messageHash: 1,
            traceHash: 1,
            evidenceHash: 2,
        }.toCell(),
    };
    val payoutAttestation = OracleAttestation {
        data: payoutData.toCell(),
        signatures: buildOracleSignatures(payoutData.toCell()),
    };

    // The emulator bypass is intentionally scoped to this test. The separate
    // crypto fixture tests exercise real Ed25519 verification.
    val acceptedPayout = escrow.sendAny(
        keeper.address,
        payoutAttestation.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(acceptedPayout).toHaveSuccessfulTx<OracleAttestation>({
        from: keeper.address,
        to: escrow.address,
    });

    expect(escrow.getState()).toEqual(STATE_SETTLED);
    val sellerDeploymentRefundTx = acceptedPayout.findTransaction({
        from: escrow.address,
        to: seller.address,
    });
    val buyerRefundTx = acceptedPayout.findTransaction({
        from: escrow.address,
        to: buyer.address,
    });
    expect(sellerDeploymentRefundTx).toBeNotNull();
    expect(buyerRefundTx).toBeNotNull();

    val sellerDeploymentRefund = sellerDeploymentRefundTx!.loadBody<SettlementMessage>();
    val buyerReserveRefund = buyerRefundTx!.loadBody<SettlementMessage>();
    expect(sellerDeploymentRefund.action).toEqual(SETTLEMENT_ACTION_SELLER_DEPLOYMENT_REFUND);
    expect(buyerReserveRefund.action).toEqual(SETTLEMENT_ACTION_EXECUTION_RESERVE_REFUND);
    expect(sellerDeploymentRefund.queryId).toBeLess(buyerReserveRefund.queryId);

    expect(testing.getAccountBalance(buyer.address))
        .toBeGreater(buyerBalanceAfterFunding + grams("0.4"));
    expect(testing.getAccountBalance(seller.address))
        .toBeGreater(sellerBalanceAfterPayoutInitiated + grams("0.04"));
    expect(testing.getAccountBalance(escrow.address))
        .toBeGreater(grams("0.005"));
    expect(testing.getAccountBalance(escrow.address))
        .toBeLess(grams("0.02"));
}

get fun `test 2-of-3 Ed25519 oracle and resolver signatures use distinct signer keys`() {
    val keys: AuthorityKeys = {
        keyA: TEST_SIGNER_A_KEY,
        keyB: TEST_SIGNER_B_KEY,
        keyC: TEST_SIGNER_C_KEY,
    };
    val validA = Signature { data: TEST_ED25519_SIGNATURE_A }.toCell();
    val validB = Signature { data: TEST_ED25519_SIGNATURE_B }.toCell();
    val validC = Signature { data: TEST_ED25519_SIGNATURE_C }.toCell();
    val invalid = Signature { data: ZERO_SIGNATURE_BITS }.toCell();

    val threeValidOracle = OracleSignatureSet {
        signatureA: validA,
        signatureB: validB,
        signatureC: validC,
    };
    expect(countValidOracleSignatures(TEST_ED25519_DIGEST, keys, threeValidOracle)).toEqual(3);

    val twoValidOracle = OracleSignatureSet {
        signatureA: validA,
        signatureB: validB,
        signatureC: invalid,
    };
    expect(countValidOracleSignatures(TEST_ED25519_DIGEST, keys, twoValidOracle)).toEqual(2);

    val oneValidOracle = OracleSignatureSet {
        signatureA: validA,
        signatureB: invalid,
        signatureC: invalid,
    };
    expect(countValidOracleSignatures(TEST_ED25519_DIGEST, keys, oneValidOracle)).toEqual(1);

    // Copying one signer's signature into all three slots cannot produce quorum.
    val duplicateOracle = OracleSignatureSet {
        signatureA: validA,
        signatureB: validA,
        signatureC: validA,
    };
    expect(countValidOracleSignatures(TEST_ED25519_DIGEST, keys, duplicateOracle)).toEqual(1);

    val threeValidResolver = ResolverSignatureSet {
        signatureA: validA,
        signatureB: validB,
        signatureC: validC,
    };
    expect(countValidResolverSignatures(TEST_ED25519_DIGEST, keys, threeValidResolver)).toEqual(3);

    val twoValidResolver = ResolverSignatureSet {
        signatureA: validA,
        signatureB: validB,
        signatureC: invalid,
    };
    expect(countValidResolverSignatures(TEST_ED25519_DIGEST, keys, twoValidResolver)).toEqual(2);

    val oneValidResolver = ResolverSignatureSet {
        signatureA: validA,
        signatureB: invalid,
        signatureC: invalid,
    };
    expect(countValidResolverSignatures(TEST_ED25519_DIGEST, keys, oneValidResolver)).toEqual(1);

    val duplicateResolver = ResolverSignatureSet {
        signatureA: validA,
        signatureB: validA,
        signatureC: validA,
    };
    expect(countValidResolverSignatures(TEST_ED25519_DIGEST, keys, duplicateResolver)).toEqual(1);
}

get fun `test actual nft transfer bounce is correlated and retryable with signed delivery`() {
    testing.setNow(1_700_000_000);
    val salt = 0xA11D9;
    val buyer = testing.treasury("buyer");
    val (escrow, nftItem, seller, _) = createFixture(
        salt,
        STATE_INTENT_CREATED,
        0,
        0,
        false,
        false,
        buyer.address,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });

    activateDeal(escrow, seller, salt);
    depositExpectedNft(escrow, nftItem, seller, salt);
    val funding = escrow.sendFundDeal(
        buyer.address,
        1001,
        salt,
        { value: grams("1.5"), bounce: true },
    );
    expect(funding).toHaveSuccessfulTx<FundDeal>({ to: escrow.address });

    val accepted = escrow.sendAcceptDeal(
        buyer.address,
        1003,
        salt,
        { value: grams("0.03"), bounce: true },
    );
    expect(accepted).toHaveSuccessfulTx<AcceptDeal>({ to: escrow.address });
    expect(nftItem.getOwner()).toEqual(escrow.address);
    expect(escrow.getState()).toEqual(STATE_MANUAL_REVIEW);
    expect(escrow.getProgress().principalLocked).toEqual(true);
    expect(escrow.getProgress().nftInEscrow).toEqual(true);

    val failed = escrow.getProgress().outboundActions.load().first.load();
    expect(failed.kind).toEqual(OUTBOUND_KIND_NFT_RELEASE);
    expect(failed.status).toEqual(OUTBOUND_STATUS_BOUNCED);
    val failedAddresses = failed.addresses.load();
    expect(failedAddresses.itemAndDestination.load().second).toEqual(nftItem.address);
    expect(failedAddresses.recipientAndResponse.load().first).toEqual(buyer.address);
    expect(failed.queryId).toEqual(1);

    val admin = testing.treasury("test-nft-policy-admin");
    val allowRetry = nftItem.sendAny(
        admin.address,
        UpdateNftTransferPolicy { rejectRecipient: null }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(allowRetry).toHaveSuccessfulTx<UpdateNftTransferPolicy>({ to: nftItem.address });

    val retry = escrow.sendAny(
        buyer.address,
        RetryFailedOutboundAction { queryId: failed.queryId, dealSalt: salt }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(retry).toHaveSuccessfulTx<RetryFailedOutboundAction>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
    expect(escrow.getProgress().oracleAttemptId).toEqual(2);
    expect(nftItem.getOwner()).toEqual(buyer.address);

    val delivered = buildTestOracleAttestation(
        escrow,
        salt,
        ORACLE_ACTION_NFT_DELIVERED,
        2,
        nftItem.address,
        escrow.address,
        buyer.address,
        0,
        2,
        0xA11D91,
        99,
        99,
    );
    val deliveryConfirmed = escrow.sendAny(
        testing.treasury("signed-delivery-oracle").address,
        delivered.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(deliveryConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_DELIVERED_DISPUTE_WINDOW);
    expect(escrow.getProgress().principalLocked).toEqual(true);
    expect(escrow.getProgress().nftInEscrow).toEqual(false);
}


get fun `test seller payout bounce is correlated and keeps principal locked`() {
    testing.setNow(1_700_000_000);
    val salt = 0xA11DA;
    val buyer = testing.treasury("buyer");
    val uninitializedSeller = address.fromWorkchainAndHash(
        0,
        0xA11DA00000000000000000000000000000000000000000000000000000000001,
    );
    val (escrow, _, deployer, _) = createFixture(
        salt,
        STATE_DELIVERED_DISPUTE_WINDOW,
        0,
        1_699_999_999,
        false,
        true,
        null,
        uninitializedSeller,
    );
    val deployResult = escrow.deploy(deployer.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

    val funding = net.send(
        buyer.address,
        createMessage({
            bounce: false,
            value: grams("1.5"),
            dest: escrow.address,
            body: beginCell().endCell(),
        }),
    );
    expect(funding).toHaveSuccessfulTx({ from: buyer.address, to: escrow.address });

    val timeout = escrow.sendAny(
        testing.treasury("payout-bounce-keeper").address,
        TimeoutDeal { queryId: 88, dealSalt: salt }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(timeout).toHaveSuccessfulTx<TimeoutDeal>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_MANUAL_REVIEW);
    expect(escrow.getProgress().principalLocked).toEqual(true);
    expect(escrow.getProgress().nftInEscrow).toEqual(false);

    val actions = escrow.getProgress().outboundActions.load();
    expect(actions.first).toBeNotNull();
    val failed = actions.first.load();
    expect(failed.kind).toEqual(OUTBOUND_KIND_SELLER_PAYOUT);
    expect(failed.status).toEqual(OUTBOUND_STATUS_BOUNCED);
    expect(failed.addresses.load().itemAndDestination.load().second).toEqual(uninitializedSeller);
    expect(failed.queryId).toEqual(1);
}

get fun `test expired oracle attestation is rejected before timeout transaction`() {
    testing.setNow(1_700_000_000);
    val deadline = testing.getNow() - 1;
    val (escrow, nftItem, seller, buyer) = createFixture(
        0xA11DA,
        STATE_NFT_RELEASE_PENDING,
        1,
        deadline,
        false,
        true,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    expect(testing.getNow()).toBeGreater(deadline);

    val data: OracleAttestationData = {
        context: OracleContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: 0xA11DA,
            action: ORACLE_ACTION_NFT_DELIVERED,
            attemptId: 1,
        }.toCell(),
        route: OracleRoute {
            itemAddress: nftItem.address,
            sourceAddress: escrow.address,
            destinationAddress: buyer.address,
            amountNanotons: 0,
            queryId: 1,
        }.toCell(),
        position: OraclePosition {
            masterchainSeqno: 1,
            logicalTime: 1,
        }.toCell(),
        hashes: OracleEvidenceHashes {
            messageHash: 1,
            traceHash: 1,
            evidenceHash: 0xA11DA,
        }.toCell(),
    };
    val attestation = OracleAttestation {
        data: data.toCell(),
        signatures: buildOracleSignatures(data.toCell()),
    };

    val result = escrow.sendAny(
        testing.treasury("late-oracle-keeper").address,
        attestation.toCell(),
        { value: grams("0.03"), bounce: true },
    );

    expect(result).toHaveFailedTx<OracleAttestation>({
        to: escrow.address,
        exitCode: Errors.Deadline,
    });
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
}

get fun `test expired resolver decision is rejected before timeout transaction`() {
    testing.setNow(1_700_000_000);
    val salt = 0xA11DB;
    val (escrow, nftItem, seller, buyer) = createFixture(salt);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });

    activateDeal(escrow, seller, salt);
    depositExpectedNft(escrow, nftItem, seller, salt);
    val funding = escrow.sendFundDeal(
        buyer.address,
        1001,
        salt,
        { value: grams("1.5"), bounce: true },
    );
    expect(funding).toHaveSuccessfulTx<FundDeal>({ to: escrow.address });

    val reasonHash = 0xA11DBA;
    val dispute = escrow.sendAny(
        buyer.address,
        OpenDispute {
            queryId: 9001,
            dealSalt: salt,
            reasonHash,
        }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(dispute).toHaveSuccessfulTx<OpenDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_DISPUTED);

    val arbitrationDeadline = escrow.getProgress().deadlineUnix;
    testing.setNow((arbitrationDeadline + 1) as uint32);
    expect(testing.getNow()).toBeGreater(arbitrationDeadline);

    val decision: ResolverDecisionData = {
        context: ResolverDecisionContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: salt,
            disputePhase: DISPUTE_PHASE_PRE_DELIVERY,
            outcome: RESOLUTION_SELLER_WINS,
            attemptId: 1,
            evidenceHash: reasonHash,
        }.toCell(),
    };
    val resolution = ResolveDispute {
        data: decision.toCell(),
        signatures: buildResolverSignatures(decision.toCell()),
    };

    val result = escrow.sendAny(
        testing.treasury("late-resolver-keeper").address,
        resolution.toCell(),
        { value: grams("0.03"), bounce: true },
    );

    expect(result).toHaveFailedTx<ResolveDispute>({
        to: escrow.address,
        exitCode: Errors.Deadline,
    });
    expect(escrow.getState()).toEqual(STATE_DISPUTED);
    expect(nftItem.getOwner()).toEqual(escrow.address);
}

get fun `test timeout requires time strictly after the deadline`() {
    testing.setNow(1_700_000_000);
    val deadline = testing.getNow() as uint64;
    val salt = 0xA11DD;
    val (escrow, _, seller, _) = createFixture(
        salt,
        STATE_AWAITING_NFT,
        0,
        deadline,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

    val keeper = testing.treasury("exact-timeout-keeper");
    val atDeadline = escrow.sendAny(
        keeper.address,
        TimeoutDeal {
            queryId: 7701,
            dealSalt: salt,
        }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(atDeadline).toHaveFailedTx<TimeoutDeal>({
        to: escrow.address,
        exitCode: Errors.Deadline,
    });
    expect(escrow.getState()).toEqual(STATE_AWAITING_NFT);

    testing.setNow((deadline + 1) as uint32);
    val afterDeadline = escrow.sendAny(
        keeper.address,
        TimeoutDeal {
            queryId: 7702,
            dealSalt: salt,
        }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(afterDeadline).toHaveSuccessfulTx<TimeoutDeal>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_EXPIRED);
}


get fun `test oracle attestation is accepted at the exact state deadline`() {
    testing.setNow(1_700_000_000);
    val deadline = testing.getNow() as uint64;
    val salt = 0xA11DE;
    val (escrow, nftItem, seller, buyer) = createFixture(
        salt,
        STATE_NFT_RELEASE_PENDING,
        1,
        deadline,
        false,
        true,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

    val data: OracleAttestationData = {
        context: OracleContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: salt,
            action: ORACLE_ACTION_NFT_DELIVERED,
            attemptId: 1,
        }.toCell(),
        route: OracleRoute {
            itemAddress: nftItem.address,
            sourceAddress: escrow.address,
            destinationAddress: buyer.address,
            amountNanotons: 0,
            queryId: 1,
        }.toCell(),
        position: OraclePosition {
            masterchainSeqno: 1,
            logicalTime: 1,
        }.toCell(),
        hashes: OracleEvidenceHashes {
            messageHash: 1,
            traceHash: 1,
            evidenceHash: 0xA11DE,
        }.toCell(),
    };
    val attestation = OracleAttestation {
        data: data.toCell(),
        signatures: buildOracleSignatures(data.toCell()),
    };

    val result = escrow.sendAny(
        testing.treasury("exact-deadline-oracle").address,
        attestation.toCell(),
        { value: grams("0.03"), bounce: true },
    );

    expect(result).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_DELIVERED_DISPUTE_WINDOW);
}


get fun `test resolver decision is accepted at the exact arbitration deadline`() {
    testing.setNow(1_700_000_000);
    val salt = 0xA11DF;
    val (escrow, nftItem, seller, buyer) = createFixture(salt);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });

    activateDeal(escrow, seller, salt);
    depositExpectedNft(escrow, nftItem, seller, salt);
    val funding = escrow.sendFundDeal(
        buyer.address,
        1001,
        salt,
        { value: grams("1.5"), bounce: true },
    );
    expect(funding).toHaveSuccessfulTx<FundDeal>({ to: escrow.address });

    val reasonHash = 0xA11DFA;
    val dispute = escrow.sendAny(
        buyer.address,
        OpenDispute {
            queryId: 9011,
            dealSalt: salt,
            reasonHash,
        }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(dispute).toHaveSuccessfulTx<OpenDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_DISPUTED);

    val arbitrationDeadline = escrow.getProgress().deadlineUnix;
    testing.setNow(arbitrationDeadline as uint32);
    expect(testing.getNow()).toEqual(arbitrationDeadline);

    val decision: ResolverDecisionData = {
        context: ResolverDecisionContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: salt,
            disputePhase: DISPUTE_PHASE_PRE_DELIVERY,
            outcome: RESOLUTION_SELLER_WINS,
            attemptId: 1,
            evidenceHash: reasonHash,
        }.toCell(),
    };
    val resolution = ResolveDispute {
        data: decision.toCell(),
        signatures: buildResolverSignatures(decision.toCell()),
    };

    val result = escrow.sendAny(
        testing.treasury("exact-deadline-resolver").address,
        resolution.toCell(),
        { value: grams("0.03"), bounce: true },
    );

    expect(result).toHaveSuccessfulTx<ResolveDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
    expect(nftItem.getOwner()).toEqual(buyer.address);
}


get fun `test pre-delivery buyer dispute returns NFT and refunds principal exactly once`() {
    testing.setNow(1_700_000_000);
    val salt = 0xA11E0;
    val (escrow, nftItem, seller, buyer) = createFixture(salt);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });

    activateDeal(escrow, seller, salt);
    depositExpectedNft(escrow, nftItem, seller, salt);
    val funding = escrow.sendFundDeal(
        buyer.address,
        1001,
        salt,
        { value: grams("1.5"), bounce: true },
    );
    expect(funding).toHaveSuccessfulTx<FundDeal>({ to: escrow.address });

    val reasonHash = 0xA11E0A;
    val dispute = escrow.sendAny(
        buyer.address,
        OpenDispute {
            queryId: 9101,
            dealSalt: salt,
            reasonHash,
        }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(dispute).toHaveSuccessfulTx<OpenDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_DISPUTED);

    val decision: ResolverDecisionData = {
        context: ResolverDecisionContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: salt,
            disputePhase: DISPUTE_PHASE_PRE_DELIVERY,
            outcome: RESOLUTION_BUYER_WINS,
            attemptId: 1,
            evidenceHash: reasonHash,
        }.toCell(),
    };
    val resolution = ResolveDispute {
        data: decision.toCell(),
        signatures: buildResolverSignatures(decision.toCell()),
    };

    val acceptedResolution = escrow.sendAny(
        testing.treasury("buyer-dispute-resolver").address,
        resolution.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(acceptedResolution).toHaveSuccessfulTx<ResolveDispute>({ to: escrow.address });

    expect(escrow.getState()).toEqual(STATE_NFT_RETURN_PENDING);
    expect(nftItem.getOwner()).toEqual(seller.address);
    val buyerBalanceBeforePrincipalRefund = testing.getAccountBalance(buyer.address);

    val nftReturnedData: OracleAttestationData = {
        context: OracleContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: salt,
            action: ORACLE_ACTION_NFT_RETURNED_TO_SELLER,
            attemptId: 1,
        }.toCell(),
        route: OracleRoute {
            itemAddress: nftItem.address,
            sourceAddress: escrow.address,
            destinationAddress: seller.address,
            amountNanotons: 0,
            queryId: 1,
        }.toCell(),
        position: OraclePosition {
            masterchainSeqno: 10,
            logicalTime: 10,
        }.toCell(),
        hashes: OracleEvidenceHashes {
            messageHash: 0x101,
            traceHash: 0x102,
            evidenceHash: 0x103,
        }.toCell(),
    };
    val nftReturnedAttestation = OracleAttestation {
        data: nftReturnedData.toCell(),
        signatures: OracleSignatureSet {
            signatureA: dummySignature,
            signatureB: dummySignature,
            signatureC: dummySignature,
        }.toCell(),
    };

    val nftReturnConfirmed = escrow.sendAny(
        testing.treasury("buyer-dispute-oracle").address,
        nftReturnedAttestation.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(nftReturnConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });

    expect(escrow.getState()).toEqual(STATE_BUYER_REFUND_PENDING);
    expect(testing.getAccountBalance(buyer.address))
        .toBeGreater(buyerBalanceBeforePrincipalRefund);

    val buyerBalanceBeforeReserveRefund = testing.getAccountBalance(buyer.address);
    val refundData: OracleAttestationData = {
        context: OracleContext {
            domain: ESCROW_DOMAIN,
            protocolVersion: PROTOCOL_VERSION,
            networkId: TESTNET_NETWORK_ID,
            escrowAddress: escrow.address,
            dealSalt: salt,
            action: ORACLE_ACTION_BUYER_REFUND,
            attemptId: 2,
        }.toCell(),
        route: OracleRoute {
            itemAddress: nftItem.address,
            sourceAddress: escrow.address,
            destinationAddress: buyer.address,
            amountNanotons: grams("1"),
            queryId: 2,
        }.toCell(),
        position: OraclePosition {
            masterchainSeqno: 11,
            logicalTime: 11,
        }.toCell(),
        hashes: OracleEvidenceHashes {
            messageHash: 0x201,
            traceHash: 0x202,
            evidenceHash: 0x203,
        }.toCell(),
    };
    val refundAttestation = OracleAttestation {
        data: refundData.toCell(),
        signatures: OracleSignatureSet {
            signatureA: dummySignature,
            signatureB: dummySignature,
            signatureC: dummySignature,
        }.toCell(),
    };

    val refundConfirmed = escrow.sendAny(
        testing.treasury("buyer-refund-oracle").address,
        refundAttestation.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(refundConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });

    expect(escrow.getState()).toEqual(STATE_REFUNDED);
    expect(escrow.getProgress().principalLocked).toEqual(false);
    expect(escrow.getProgress().nftInEscrow).toEqual(false);
    expect(nftItem.getOwner()).toEqual(seller.address);
    expect(testing.getAccountBalance(buyer.address))
        .toBeGreater(buyerBalanceBeforeReserveRefund);

    val duplicateRefund = escrow.sendAny(
        testing.treasury("duplicate-buyer-refund-oracle").address,
        refundAttestation.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(duplicateRefund).toHaveFailedTx<OracleAttestation>({
        to: escrow.address,
        exitCode: Errors.Deadline,
    });
    expect(escrow.getState()).toEqual(STATE_REFUNDED);
}


get fun `test post-delivery seller dispute outcome requires buyer NFT return before payout`() {
    testing.setNow(1_700_000_000);
    val salt = 0xA11E1;
    val (escrow, nftItem, seller, buyer) = createFixture(salt);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });

    activateDeal(escrow, seller, salt);
    depositExpectedNft(escrow, nftItem, seller, salt);
    val funding = escrow.sendFundDeal(
        buyer.address,
        1001,
        salt,
        { value: grams("1.5"), bounce: true },
    );
    expect(funding).toHaveSuccessfulTx<FundDeal>({ to: escrow.address });
    val accepted = escrow.sendAcceptDeal(
        buyer.address,
        1003,
        salt,
        { value: grams("0.03"), bounce: true },
    );
    expect(accepted).toHaveSuccessfulTx<AcceptDeal>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
    expect(nftItem.getOwner()).toEqual(buyer.address);

    val delivered = buildTestOracleAttestation(
        escrow,
        salt,
        ORACLE_ACTION_NFT_DELIVERED,
        1,
        nftItem.address,
        escrow.address,
        buyer.address,
        0,
        1,
        0x301,
        21,
        21,
    );
    val deliveryConfirmed = escrow.sendAny(
        testing.treasury("post-delivery-oracle").address,
        delivered.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(deliveryConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_DELIVERED_DISPUTE_WINDOW);

    val reasonHash = 0xA11E1A;
    val dispute = escrow.sendAny(
        buyer.address,
        OpenDispute {
            queryId: 9201,
            dealSalt: salt,
            reasonHash,
        }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(dispute).toHaveSuccessfulTx<OpenDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_DISPUTED);
    expect(escrow.getProgress().disputePhase).toEqual(DISPUTE_PHASE_POST_DELIVERY);

    val buyerReturn = nftItem.sendAny(
        buyer.address,
        buildDepositBody(escrow.address, buyer.address, 1004, salt),
        { value: grams("0.12"), bounce: true },
    );
    expect(buyerReturn).toHaveSuccessfulTx<NftTransfer>({ to: nftItem.address });
    expect(buyerReturn).toHaveTx<NotificationForNewOwner>({
        from: nftItem.address,
        to: escrow.address,
    });
    expect(nftItem.getOwner()).toEqual(escrow.address);
    expect(escrow.getState()).toEqual(STATE_DISPUTED);
    expect(escrow.getProgress().nftInEscrow).toEqual(true);

    val resolution = buildTestResolverDecision(
        escrow,
        salt,
        DISPUTE_PHASE_POST_DELIVERY,
        RESOLUTION_SELLER_WINS,
        1,
        reasonHash,
    );
    val acceptedResolution = escrow.sendAny(
        testing.treasury("post-delivery-resolver").address,
        resolution.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(acceptedResolution).toHaveSuccessfulTx<ResolveDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
    expect(nftItem.getOwner()).toEqual(buyer.address);

    val deliveredAfterDispute = buildTestOracleAttestation(
        escrow,
        salt,
        ORACLE_ACTION_NFT_DELIVERED,
        2,
        nftItem.address,
        escrow.address,
        buyer.address,
        0,
        2,
        0x302,
        22,
        22,
    );
    val deliveryConfirmedAfterDispute = escrow.sendAny(
        testing.treasury("post-delivery-release-oracle").address,
        deliveredAfterDispute.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(deliveryConfirmedAfterDispute)
        .toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_SELLER_PAYOUT_PENDING);

    val payout = buildTestOracleAttestation(
        escrow,
        salt,
        ORACLE_ACTION_SELLER_PAYOUT,
        3,
        nftItem.address,
        escrow.address,
        seller.address,
        grams("1"),
        3,
        0x303,
        23,
        23,
    );
    val payoutConfirmed = escrow.sendAny(
        testing.treasury("post-delivery-payout-oracle").address,
        payout.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(payoutConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });

    expect(escrow.getState()).toEqual(STATE_SETTLED);
    expect(escrow.getProgress().principalLocked).toEqual(false);
    expect(escrow.getProgress().nftInEscrow).toEqual(false);
    expect(nftItem.getOwner()).toEqual(buyer.address);
}


get fun `test pre-delivery seller dispute outcome settles payout after delivery attestation`() {
    testing.setNow(1_700_000_000);
    val salt = 0xA11E2;
    val (escrow, nftItem, seller, buyer) = createFixture(salt);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });

    activateDeal(escrow, seller, salt);
    depositExpectedNft(escrow, nftItem, seller, salt);
    val funding = escrow.sendFundDeal(
        buyer.address,
        1001,
        salt,
        { value: grams("1.5"), bounce: true },
    );
    expect(funding).toHaveSuccessfulTx<FundDeal>({ to: escrow.address });

    val reasonHash = 0xA11E2A;
    val dispute = escrow.sendAny(
        buyer.address,
        OpenDispute {
            queryId: 9301,
            dealSalt: salt,
            reasonHash,
        }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(dispute).toHaveSuccessfulTx<OpenDispute>({ to: escrow.address });

    val resolution = buildTestResolverDecision(
        escrow,
        salt,
        DISPUTE_PHASE_PRE_DELIVERY,
        RESOLUTION_SELLER_WINS,
        1,
        reasonHash,
    );
    val acceptedResolution = escrow.sendAny(
        testing.treasury("pre-delivery-seller-resolver").address,
        resolution.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(acceptedResolution).toHaveSuccessfulTx<ResolveDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
    expect(nftItem.getOwner()).toEqual(buyer.address);

    val delivery = buildTestOracleAttestation(
        escrow, salt, ORACLE_ACTION_NFT_DELIVERED, 1,
        nftItem.address, escrow.address, buyer.address, 0, 1, 0x401, 31, 31,
    );
    val deliveryConfirmed = escrow.sendAny(
        testing.treasury("pre-delivery-seller-delivery-oracle").address,
        delivery.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(deliveryConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_SELLER_PAYOUT_PENDING);

    val payout = buildTestOracleAttestation(
        escrow, salt, ORACLE_ACTION_SELLER_PAYOUT, 2,
        nftItem.address, escrow.address, seller.address, grams("1"), 2, 0x402, 32, 32,
    );
    val payoutConfirmed = escrow.sendAny(
        testing.treasury("pre-delivery-seller-payout-oracle").address,
        payout.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(payoutConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });

    expect(escrow.getState()).toEqual(STATE_SETTLED);
    expect(escrow.getProgress().principalLocked).toEqual(false);
    expect(escrow.getProgress().nftInEscrow).toEqual(false);
    expect(nftItem.getOwner()).toEqual(buyer.address);
}


get fun `test post-delivery buyer dispute outcome returns NFT and refunds buyer`() {
    testing.setNow(1_700_000_000);
    val salt = 0xA11E3;
    val (escrow, nftItem, seller, buyer) = createFixture(salt);
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });

    activateDeal(escrow, seller, salt);
    depositExpectedNft(escrow, nftItem, seller, salt);
    val funding = escrow.sendFundDeal(
        buyer.address,
        1001,
        salt,
        { value: grams("1.5"), bounce: true },
    );
    expect(funding).toHaveSuccessfulTx<FundDeal>({ to: escrow.address });
    val accepted = escrow.sendAcceptDeal(
        buyer.address,
        1003,
        salt,
        { value: grams("0.03"), bounce: true },
    );
    expect(accepted).toHaveSuccessfulTx<AcceptDeal>({ to: escrow.address });

    val delivery = buildTestOracleAttestation(
        escrow, salt, ORACLE_ACTION_NFT_DELIVERED, 1,
        nftItem.address, escrow.address, buyer.address, 0, 1, 0x501, 41, 41,
    );
    val deliveryConfirmed = escrow.sendAny(
        testing.treasury("post-buyer-initial-delivery-oracle").address,
        delivery.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(deliveryConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_DELIVERED_DISPUTE_WINDOW);

    val reasonHash = 0xA11E3A;
    val dispute = escrow.sendAny(
        buyer.address,
        OpenDispute {
            queryId: 9401,
            dealSalt: salt,
            reasonHash,
        }.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(dispute).toHaveSuccessfulTx<OpenDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_DISPUTED);
    expect(escrow.getProgress().disputePhase).toEqual(DISPUTE_PHASE_POST_DELIVERY);

    val buyerReturn = nftItem.sendAny(
        buyer.address,
        buildDepositBody(escrow.address, buyer.address, 1004, salt),
        { value: grams("0.12"), bounce: true },
    );
    expect(buyerReturn).toHaveSuccessfulTx<NftTransfer>({ to: nftItem.address });
    expect(buyerReturn).toHaveTx<NotificationForNewOwner>({
        from: nftItem.address,
        to: escrow.address,
    });
    expect(nftItem.getOwner()).toEqual(escrow.address);
    expect(escrow.getProgress().nftInEscrow).toEqual(true);

    val resolution = buildTestResolverDecision(
        escrow,
        salt,
        DISPUTE_PHASE_POST_DELIVERY,
        RESOLUTION_BUYER_WINS,
        1,
        reasonHash,
    );
    val acceptedResolution = escrow.sendAny(
        testing.treasury("post-delivery-buyer-resolver").address,
        resolution.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(acceptedResolution).toHaveSuccessfulTx<ResolveDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_NFT_RETURN_PENDING);
    expect(nftItem.getOwner()).toEqual(seller.address);

    val nftReturned = buildTestOracleAttestation(
        escrow, salt, ORACLE_ACTION_NFT_RETURNED_TO_SELLER, 2,
        nftItem.address, escrow.address, seller.address, 0, 2, 0x502, 42, 42,
    );
    val nftReturnConfirmed = escrow.sendAny(
        testing.treasury("post-delivery-buyer-return-oracle").address,
        nftReturned.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(nftReturnConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_BUYER_REFUND_PENDING);

    val refund = buildTestOracleAttestation(
        escrow, salt, ORACLE_ACTION_BUYER_REFUND, 3,
        nftItem.address, escrow.address, buyer.address, grams("1"), 3, 0x503, 43, 43,
    );
    val refundConfirmed = escrow.sendAny(
        testing.treasury("post-delivery-buyer-refund-oracle").address,
        refund.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(refundConfirmed).toHaveSuccessfulTx<OracleAttestation>({ to: escrow.address });

    expect(escrow.getState()).toEqual(STATE_REFUNDED);
    expect(escrow.getProgress().principalLocked).toEqual(false);
    expect(escrow.getProgress().nftInEscrow).toEqual(false);
    expect(nftItem.getOwner()).toEqual(seller.address);
}


get fun `test bounced message cannot overwrite an already terminal state`() {
    val (escrow, _, seller, _) = createFixture(
        0xA11DC,
        STATE_SETTLED,
        0,
        0,
        false,
        false,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_SETTLED);

    val bounceOrigin = testing.treasury("terminal-bounce-origin");
    val bouncedMessage = createMessage({
        bounce: BounceMode.RichBounce,
        value: grams("0.03"),
        dest: escrow.address,
        body: SettlementMessage {
            queryId: 1,
            dealSalt: 0xA11DC,
            action: SETTLEMENT_ACTION_SELLER_DEPLOYMENT_REFUND,
        },
    }).bounced();
    val result = net.send(bounceOrigin.address, bouncedMessage);
    expect(result).toHaveSuccessfulTx({ to: escrow.address });

    // A secondary refund bounce cannot erase a reconciled terminal result.
    expect(escrow.getState()).toEqual(STATE_SETTLED);
}

get fun `test bounced secondary action preserves refunded terminal state`() {
    val salt = 0xA11DD1;
    val (escrow, _, seller, _) = createFixture(
        salt,
        STATE_REFUNDED,
        0,
        0,
        false,
        false,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_REFUNDED);

    val bounceOrigin = testing.treasury("refunded-terminal-bounce-origin");
    val bouncedMessage = createMessage({
        bounce: BounceMode.RichBounce,
        value: grams("0.03"),
        dest: escrow.address,
        body: SettlementMessage {
            queryId: 2,
            dealSalt: salt,
            action: SETTLEMENT_ACTION_SELLER_DEPLOYMENT_REFUND,
        },
    }).bounced();
    val result = net.send(bounceOrigin.address, bouncedMessage);
    expect(result).toHaveSuccessfulTx({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_REFUNDED);
}


get fun `test bounced secondary action preserves expired terminal state`() {
    val salt = 0xA11DD2;
    val (escrow, _, seller, _) = createFixture(
        salt,
        STATE_EXPIRED,
        0,
        0,
        false,
        false,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_EXPIRED);

    val bounceOrigin = testing.treasury("expired-terminal-bounce-origin");
    val bouncedMessage = createMessage({
        bounce: BounceMode.RichBounce,
        value: grams("0.03"),
        dest: escrow.address,
        body: SettlementMessage {
            queryId: 3,
            dealSalt: salt,
            action: SETTLEMENT_ACTION_SELLER_DEPLOYMENT_REFUND,
        },
    }).bounced();
    val result = net.send(bounceOrigin.address, bouncedMessage);
    expect(result).toHaveSuccessfulTx({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_EXPIRED);
}

