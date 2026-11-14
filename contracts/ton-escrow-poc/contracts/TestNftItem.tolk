// Test-only TEP-62 item used by the Acton emulator suite.
// Never deploy this mock as an NFT collection/item on a public network.

import "types"

struct TestNftStorage {
    ownerAddress: address
    fixtureSalt: uint256
}

type TestNftMessage = NftTransfer

contract TestNftItem {
    author: "AzizIo"
    version: "1.0.0"
    description: "Test-only TEP-62 item mock"
    storage: TestNftStorage
    incomingMessages: TestNftMessage
}

fun TestNftStorage.load(): TestNftStorage {
    return TestNftStorage.fromCell(contract.getData());
}

fun TestNftStorage.save(self) {
    contract.setData(self.toCell());
}

fun onInternalMessage(in: InMessage) {
    if (in.body.isEmpty()) {
        return;
    }
    val msg = lazy TestNftMessage.fromSlice(in.body);
    match (msg) {
        NftTransfer => {
            var storage = TestNftStorage.load();
            assert (in.senderAddress == storage.ownerAddress) throw 401;
            assert (msg.forwardTonAmount > 0) throw 402;
            val previousOwner = storage.ownerAddress;
            storage.ownerAddress = msg.newOwnerAddress;
            storage.save();

            val notification = createMessage({
                bounce: BounceMode.NoBounce,
                value: msg.forwardTonAmount,
                dest: msg.newOwnerAddress,
                body: NotificationForNewOwner {
                    queryId: msg.queryId,
                    oldOwnerAddress: previousOwner,
                    payload: msg.forwardPayload,
                },
            });
            notification.send(SEND_MODE_PAY_FEES_SEPARATELY);
        }
        else => {
            assert (in.body.isEmpty()) throw 0xFFFF;
        }
    }
}

get fun get_owner(): address {
    return TestNftStorage.load().ownerAddress;
}
