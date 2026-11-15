import { beginCell, Address } from "@ton/core";
import {
  AuthorityKeys,
  DealAsset,
  DealEscrow,
  DealEvidence,
  DealMoney,
  DealProgress,
  DealRecovery,
  DealRoles,
  DealSecurity,
  DealTerms,
  OutboundActionSet,
} from "../wrappers-ts/DealEscrow.gen.ts";

const raw = (byte: string) => Address.parseRaw(`0:${byte.repeat(64 / byte.length)}`);
const seller = raw("11");
const buyer = raw("22");
const collection = raw("33");
const item = raw("44");
const salt = BigInt("0x" + "01".repeat(32));

const roles = DealRoles.create({ seller, buyer });
const asset = DealAsset.create({
  itemAddress: item,
  collectionAddress: collection,
  dealSalt: salt,
});
const money = DealMoney.create({
  principalNanotons: 1_000_000_000n,
  executionReserve: 500_000_000n,
  sellerDeploymentRefundNanotons: 50_000_000n,
  nftTransferValue: 80_000_000n,
  fundQueryId: 1001n,
  nftDepositQueryId: 1002n,
  nftReleaseQueryId: 1003n,
  nftReturnToEscrowQueryId: 1004n,
});
const security = DealSecurity.create({
  oracleKeys: { ref: AuthorityKeys.create({ keyA: 1n, keyB: 2n, keyC: 3n }) },
  resolverKeys: { ref: AuthorityKeys.create({ keyA: 4n, keyB: 5n, keyC: 6n }) },
});
const terms = DealTerms.create({
  roles: { ref: roles },
  asset: { ref: asset },
  money: { ref: money },
  security: { ref: security },
  networkId: -3n,
  protocolVersion: 1n,
});
const progress = DealProgress.create({
  state: 0n,
  deadlineUnix: 0n,
  disputePhase: 0n,
  pendingAction: 0n,
  nftInEscrow: false,
  principalLocked: false,
  oracleAttemptId: 0n,
  disputeAttemptId: 0n,
  evidence: { ref: DealEvidence.create({ lastEvidenceHash: 0n, disputeReasonHash: 0n }) },
  recovery: { ref: DealRecovery.create({
    unexpectedPreviousOwner: null,
    unexpectedItemAddress: null,
  }) },
  outboundActions: { ref: OutboundActionSet.create({ first: null, second: null }) },
});
const deployed = DealEscrow.fromStorage({
  terms: { ref: terms },
  progress: { ref: progress },
});
if (!deployed.init) throw new Error("Generated Acton wrapper did not return StateInit");
const stateInit = beginCell()
  .storeBit(0) // split_depth = None
  .storeBit(0) // special = None
  .storeBit(1).storeRef(deployed.init.code) // code = Some(^Cell)
  .storeBit(1).storeRef(deployed.init.data) // data = Some(^Cell)
  .storeBit(0) // library = empty HashmapE
  .endCell();
const EXPECTED_CODE_HASH =
  "61348A9F67A31753622AB3E9E204AF67FBC1ED8736B05510DD9DF93E0F49366B";
const EXPECTED_STATE_INIT_HASH =
  "e97848a3d9e691bd0b78c7a6085d836821e459b347b15ecd0d10c645427768c6";
const EXPECTED_RAW_ADDRESS =
  "0:024ec492b97607ed98a2c3f93a36533053d5a8cb4bb4c31c951c820e8aefdaf9";
const EXPECTED_DATA_HASH =
  "faf8907c9fc1b2d78670b085b1976465533463647a7357fdb498ba223fef7e5b";

if (!stateInit.hash().equals(deployed.address.hash)) {
  throw new Error("StateInit hash differs from generated Acton wrapper address");
}
if (deployed.init.code.hash().toString("hex").toUpperCase() !== EXPECTED_CODE_HASH) {
  throw new Error("Generated Acton CodeCell does not match pinned manifest");
}
if (stateInit.hash().toString("hex") !== EXPECTED_STATE_INIT_HASH) {
  throw new Error("Generated fixed StateInit hash differs from frozen golden vector");
}
if (deployed.address.toRawString() !== EXPECTED_RAW_ADDRESS) {
  throw new Error("Generated fixed DealEscrow address differs from frozen golden vector");
}
if (deployed.init.data.hash().toString("hex") !== EXPECTED_DATA_HASH) {
  throw new Error("Generated initial storage cell differs from frozen golden vector");
}
console.log(JSON.stringify({
  vector: "deal-escrow-v1-testnet-fixed-terms-01",
  address: deployed.address.toRawString(),
  state_init_hash: stateInit.hash().toString("hex"),
  data_hash: deployed.init.data.hash().toString("hex"),
  code_hash: deployed.init.code.hash().toString("hex").toUpperCase(),
}));
