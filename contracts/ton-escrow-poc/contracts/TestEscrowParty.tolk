// Test-only TON recipient/participant for exercising real escrow outbound failures.
// Never deploy this mock to a public network.
import "types"

struct TestEscrowPartyStorage {
    controllerAddress: address
    rejectSettlementAction: uint8
}

struct (0x5645f101) PartyActivateEscrow {
    escrowAddress: address
    dealSalt: uint256
}

struct (0x5645f102) PartyDepositNft {
    escrowAddress: address
    itemAddress: address
    dealSalt: uint256
    queryId: uint64
}

struct (0x5645f103) PartyFundEscrow {
    escrowAddress: address
    dealSalt: uint256
    queryId: uint64
    fundingValue: coins
}

struct (0x5645f104) PartyAcceptEscrow {
    escrowAddress: address
    dealSalt: uint256
    queryId: uint64
}

struct (0x5645f105) PartyRetryOutbound {
    escrowAddress: address
    dealSalt: uint256
    queryId: uint64
}

struct (0x5645f106) PartySetRejectAction {
    rejectSettlementAction: uint8
}

type TestEscrowPartyMessage =
    | PartyActivateEscrow
    | PartyDepositNft
    | PartyFundEscrow
    | PartyAcceptEscrow
    | PartyRetryOutbound
    | PartySetRejectAction
    | SettlementMessage
    | NotificationForNewOwner

contract TestEscrowParty {
    author: "AzizIo"
    version: "1.0.0"
    description: "Test-only recipient capable of rejecting one escrow settlement action"
    storage: TestEscrowPartyStorage
    incomingMessages: TestEscrowPartyMessage
}

fun TestEscrowPartyStorage.load(): TestEscrowPartyStorage {
    return TestEscrowPartyStorage.fromCell(contract.getData());
}

fun TestEscrowPartyStorage.save(self) {
    contract.setData(self.toCell());
}

fun onInternalMessage(in: InMessage) {
    if (in.body.isEmpty()) {
        return;
    }
    val msg = lazy TestEscrowPartyMessage.fromSlice(in.body);
    match (msg) {
        PartyActivateEscrow => {
            val storage = TestEscrowPartyStorage.load();
            assert (in.senderAddress == storage.controllerAddress) throw 910;
            val out = createMessage({
                bounce: BounceMode.RichBounce,
                value: grams("0.03"),
                dest: msg.escrowAddress,
                body: ActivateDeal {
                    queryId: 1,
                    dealSalt: msg.dealSalt,
                },
            });
            out.send(SEND_MODE_PAY_FEES_SEPARATELY);
        }
        PartyDepositNft => {
            val storage = TestEscrowPartyStorage.load();
            assert (in.senderAddress == storage.controllerAddress) throw 910;
            val payload = beginCell()
                .storeBool(false)
                .storeUint(NFT_FORWARD_MAGIC, 32)
                .storeUint(msg.dealSalt, 256)
                .toSlice();
            val transfer = createMessage({
                bounce: BounceMode.RichBounce,
                value: grams("0.15"),
                dest: msg.itemAddress,
                body: NftTransfer {
                    queryId: msg.queryId,
                    newOwnerAddress: msg.escrowAddress,
                    sendExcessesTo: contract.getAddress(),
                    customPayload: null,
                    forwardTonAmount: grams("0.01"),
                    forwardPayload: payload,
                },
            });
            transfer.send(SEND_MODE_PAY_FEES_SEPARATELY + SEND_MODE_BOUNCE_ON_ACTION_FAIL);
        }
        PartyFundEscrow => {
            val storage = TestEscrowPartyStorage.load();
            assert (in.senderAddress == storage.controllerAddress) throw 910;
            val fund = createMessage({
                bounce: BounceMode.RichBounce,
                value: msg.fundingValue,
                dest: msg.escrowAddress,
                body: FundDeal {
                    queryId: msg.queryId,
                    dealSalt: msg.dealSalt,
                },
            });
            fund.send(SEND_MODE_PAY_FEES_SEPARATELY);
        }
        PartyAcceptEscrow => {
            val storage = TestEscrowPartyStorage.load();
            assert (in.senderAddress == storage.controllerAddress) throw 910;
            val accept = createMessage({
                bounce: BounceMode.RichBounce,
                value: grams("0.03"),
                dest: msg.escrowAddress,
                body: AcceptDeal {
                    queryId: msg.queryId,
                    dealSalt: msg.dealSalt,
                },
            });
            accept.send(SEND_MODE_PAY_FEES_SEPARATELY);
        }
        PartyRetryOutbound => {
            val storage = TestEscrowPartyStorage.load();
            assert (in.senderAddress == storage.controllerAddress) throw 910;
            val retry = createMessage({
                bounce: BounceMode.RichBounce,
                value: grams("0.03"),
                dest: msg.escrowAddress,
                body: RetryFailedOutboundAction {
                    queryId: msg.queryId,
                    dealSalt: msg.dealSalt,
                },
            });
            retry.send(SEND_MODE_PAY_FEES_SEPARATELY);
        }
        PartySetRejectAction => {
            var storage = TestEscrowPartyStorage.load();
            assert (in.senderAddress == storage.controllerAddress) throw 910;
            storage.rejectSettlementAction = msg.rejectSettlementAction;
            storage.save();
        }
        SettlementMessage => {
            val storage = TestEscrowPartyStorage.load();
            assert (msg.action != storage.rejectSettlementAction) throw 911;
            // Accept all other TON escrow settlements. The incoming value stays
            // in this test recipient's balance and can be observed by the test.
        }
        NotificationForNewOwner => {
            // The test recipient can be the new owner of the configured NFT.
            // No state transition is needed for the notification in these tests.
        }
        else => {
            // Ignore TEP-62 excesses and unrelated non-financial notifications.
            return;
        }
    }
}

get fun get_reject_settlement_action(): uint8 {
    return TestEscrowPartyStorage.load().rejectSettlementAction;
}
