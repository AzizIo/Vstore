import "@acton/emulation/config"
import "@acton/emulation/network"
import "@acton/emulation/testing"
import "@acton/testing/expect"

import "@contracts/types"
import "@wrappers/DealEscrow.gen"
import "@wrappers/TestNftItem.gen"

const TEST_KEY_A = 0x11
const TEST_KEY_B = 0x22
const TEST_KEY_C = 0x33

fun configureTestnet() {
    val config = testing.getConfig();
    config.setParamRaw(19, beginCell().storeInt(TESTNET_GLOBAL_ID, 32).endCell());
    assert (testing.setConfig(config)) throw Errors.NotTestnet;
}

fun createFixture(): (DealEscrow, TestNftItem, Treasury, Treasury) {
    configureTestnet();
    val seller = testing.treasury("seller");
    val buyer = testing.treasury("buyer");
    val collection = testing.treasury("test-collection");
    val nftItem = TestNftItem.fromStorage({ ownerAddress: seller.address });

    val roles: DealRoles = {
        seller: seller.address,
        buyer: buyer.address,
    };
    val asset: DealAsset = {
        itemAddress: nftItem.address,
        collectionAddress: collection.address,
        dealSalt: 0xA11CE,
    };
    val money: DealMoney = {
        principalNanotons: grams("1"),
        executionReserve: grams("0.5"),
        nftTransferValue: grams("0.08"),
        fundQueryId: 1001,
        nftDepositQueryId: 1002,
        nftReleaseQueryId: 1003,
        nftReturnToEscrowQueryId: 1004,
        nftReturnToSellerQueryId: 1005,
        sellerPayoutQueryId: 1006,
        buyerRefundQueryId: 1007,
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
        state: STATE_INTENT_CREATED,
        deadlineUnix: 0,
        disputePhase: DISPUTE_PHASE_NONE,
        pendingAction: PENDING_NONE,
        nftInEscrow: false,
        principalLocked: false,
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

fun deployAndActivate(
    escrow: DealEscrow,
    seller: Treasury,
    salt: uint256,
) {
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

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
) {
    val deposit = nftItem.sendAny(
        seller.address,
        buildDepositBody(escrow.address, seller.address, 1002, 0xA11CE),
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
    val (escrowA, _, seller, _) = createFixture();
    val (escrowB, _, _, _) = createFixture();

    expect(escrowA.address).toEqual(escrowB.address);
    val deployResult = escrowA.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrowA.address });
    expect(escrowA.getState()).toEqual(STATE_INTENT_CREATED);
}

get fun `test seller activates a per-deal escrow`() {
    val (escrow, _, seller, _) = createFixture();
    deployAndActivate(escrow, seller, 0xA11CE);
    expect(escrow.getState()).toEqual(STATE_AWAITING_NFT);
}

get fun `test only the snapshotted seller can activate the deal`() {
    val (escrow, _, seller, buyer) = createFixture();
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });

    val badActivation = escrow.sendActivateDeal(
        buyer.address,
        1,
        0xA11CE,
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
    val (escrow, nftItem, seller, _) = createFixture();
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });

    deployAndActivate(escrow, seller, 0xA11CE);
    depositExpectedNft(escrow, nftItem, seller);
    expect(escrow.getState()).toEqual(STATE_AWAITING_BUYER_FUNDS);
}

get fun `test a different NFT item sender cannot unlock buyer funding`() {
    val (escrow, nftItem, seller, _) = createFixture();
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val realItemDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(realItemDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });
    deployAndActivate(escrow, seller, 0xA11CE);

    val fakeOwner = testing.treasury("fake-item-owner");
    val fakeItem = TestNftItem.fromStorage({ ownerAddress: fakeOwner.address });
    val fakeDeploy = fakeItem.deploy(fakeOwner.address, { value: grams("0.05"), bounce: false });
    expect(fakeDeploy).toHaveSuccessfulDeploy({ to: fakeItem.address });
    val fakeDeposit = fakeItem.sendAny(
        fakeOwner.address,
        buildDepositBody(escrow.address, fakeOwner.address, 1002, 0xA11CE),
        { value: grams("0.12"), bounce: true },
    );
    expect(fakeDeposit).toHaveSuccessfulTx<NftTransfer>({
        from: fakeOwner.address,
        to: fakeItem.address,
    });
    expect(escrow.getState()).toEqual(STATE_AWAITING_NFT);
}

get fun `test buyer must attach exact principal plus execution reserve`() {
    val (escrow, nftItem, seller, buyer) = createFixture();
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });
    deployAndActivate(escrow, seller, 0xA11CE);
    depositExpectedNft(escrow, nftItem, seller);

    val invalidFunding = escrow.sendFundDeal(
        buyer.address,
        1001,
        0xA11CE,
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
        0xA11CE,
        { value: grams("1.5"), bounce: true },
    );
    expect(funding).toHaveSuccessfulTx<FundDeal>({
        from: buyer.address,
        to: escrow.address,
    });
    expect(escrow.getState()).toEqual(STATE_FUNDED_REVIEW);
}

get fun `test buyer acceptance is pre-delivery and participant scoped`() {
    val (escrow, nftItem, seller, buyer) = createFixture();
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });
    deployAndActivate(escrow, seller, 0xA11CE);
    depositExpectedNft(escrow, nftItem, seller);
    escrow.sendFundDeal(buyer.address, 1001, 0xA11CE, { value: grams("1.5"), bounce: true });

    val rejected = escrow.sendAcceptDeal(
        seller.address,
        1003,
        0xA11CE,
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
        0xA11CE,
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
    val (escrow, nftItem, seller, buyer) = createFixture();
    val deployResult = escrow.deploy(seller.address, { value: grams("0.2"), bounce: false });
    expect(deployResult).toHaveSuccessfulDeploy({ to: escrow.address });
    val nftDeploy = nftItem.deploy(seller.address, { value: grams("0.05"), bounce: false });
    expect(nftDeploy).toHaveSuccessfulDeploy({ to: nftItem.address });
    deployAndActivate(escrow, seller, 0xA11CE);
    depositExpectedNft(escrow, nftItem, seller);
    escrow.sendFundDeal(buyer.address, 1001, 0xA11CE, { value: grams("1.5"), bounce: true });
    escrow.sendAcceptDeal(buyer.address, 1003, 0xA11CE, { value: grams("0.03"), bounce: true });

    expect(nftItem.getOwner()).toEqual(buyer.address);
    expect(escrow.getState()).toEqual(STATE_NFT_RELEASE_PENDING);
}
