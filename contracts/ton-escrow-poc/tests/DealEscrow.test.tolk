import "@acton/emulation/config"
import "@acton/emulation/network"
import "@acton/emulation/testing"
import "@acton/testing/expect"
import "@acton/types/transaction"

import "@contracts/types"
import "@contracts/signatures"
import "@wrappers/DealEscrow.gen"
import "@wrappers/TestNftItem.gen"

const TEST_KEY_A = 0x11
const TEST_KEY_B = 0x22
const TEST_KEY_C = 0x33
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
): (DealEscrow, TestNftItem, Treasury, Treasury) {
    configureTestnet();
    val seller = testing.treasury("seller");
    val buyer = testing.treasury("buyer");
    val collection = testing.treasury("test-collection");
    val nftItem = TestNftItem.fromStorage({ ownerAddress: seller.address, fixtureSalt: salt });

    val roles: DealRoles = {
        seller: seller.address,
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
            keyA: TEST_KEY_A,
            keyB: TEST_KEY_B,
            keyC: TEST_KEY_C,
        }.toCell(),
        resolverKeys: AuthorityKeys {
            keyA: 0x101,
            keyB: 0x202,
            keyC: 0x303,
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
    val dummySignature = Signature { data: ZERO_SIGNATURE_BITS }.toCell();
    val payoutAttestation = OracleAttestation {
        data: payoutData.toCell(),
        signatures: OracleSignatureSet {
            signatureA: dummySignature,
            signatureB: dummySignature,
            signatureC: dummySignature,
        }.toCell(),
    };

    // The emulator bypass is intentionally scoped to this test. The separate
    // crypto fixture tests exercise real Ed25519 verification.
    testing.setChecksigIgnore(true);
    val acceptedPayout = escrow.sendAny(
        keeper.address,
        payoutAttestation.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    expect(acceptedPayout).toHaveSuccessfulTx<OracleAttestation>({
        from: keeper.address,
        to: escrow.address,
    });
    testing.setChecksigIgnore(false);

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

get fun `test bounced internal action forces manual review`() {
    val (escrow, _, seller, _) = createFixture(
        0xA11D9,
        STATE_NFT_RELEASE_PENDING,
        1,
    );
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

    val keeper = testing.treasury("bounce-recovery-keeper");
    val bouncedMessage = createMessage({
        bounce: false,
        value: grams("0.03"),
        dest: escrow.address,
        body: TimeoutDeal {
            queryId: 1,
            dealSalt: 0xA11D9,
        },
    }).bounced();
    val bounceResult = net.send(keeper.address, bouncedMessage);
    expect(bounceResult).toHaveSuccessfulTx({
        from: keeper.address,
        to: escrow.address,
    });
    expect(escrow.getState()).toEqual(STATE_MANUAL_REVIEW);
}


get fun `test expired oracle attestation is still accepted before timeout transaction`() {
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
    val dummySignature = Signature { data: ZERO_SIGNATURE_BITS }.toCell();
    val attestation = OracleAttestation {
        data: data.toCell(),
        signatures: OracleSignatureSet {
            signatureA: dummySignature,
            signatureB: dummySignature,
            signatureC: dummySignature,
        }.toCell(),
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

get fun `test expired resolver decision is still accepted before timeout transaction`() {
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
    val dummySignature = Signature { data: ZERO_SIGNATURE_BITS }.toCell();
    val resolution = ResolveDispute {
        data: decision.toCell(),
        signatures: ResolverSignatureSet {
            signatureA: dummySignature,
            signatureB: dummySignature,
            signatureC: dummySignature,
        }.toCell(),
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
    val dummySignature = Signature { data: ZERO_SIGNATURE_BITS }.toCell();
    val attestation = OracleAttestation {
        data: data.toCell(),
        signatures: OracleSignatureSet {
            signatureA: dummySignature,
            signatureB: dummySignature,
            signatureC: dummySignature,
        }.toCell(),
    };

    testing.setChecksigIgnore(true);
    val result = escrow.sendAny(
        testing.treasury("exact-deadline-oracle").address,
        attestation.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    testing.setChecksigIgnore(false);

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
    val dummySignature = Signature { data: ZERO_SIGNATURE_BITS }.toCell();
    val resolution = ResolveDispute {
        data: decision.toCell(),
        signatures: ResolverSignatureSet {
            signatureA: dummySignature,
            signatureB: dummySignature,
            signatureC: dummySignature,
        }.toCell(),
    };

    testing.setChecksigIgnore(true);
    val result = escrow.sendAny(
        testing.treasury("exact-deadline-resolver").address,
        resolution.toCell(),
        { value: grams("0.03"), bounce: true },
    );
    testing.setChecksigIgnore(false);

    expect(result).toHaveSuccessfulTx<ResolveDispute>({ to: escrow.address });
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
    expect(nftItem.getOwner()).toEqual(buyer.address);
}


get fun `test bounced message can overwrite an already terminal state`() {
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
        bounce: false,
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
