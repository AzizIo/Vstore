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
} from "../wrappers-ts/DealEscrow.gen.ts";

const raw = (byte: string) => Address.parseRaw(`0:${byte.repeat(64 / byte.length)}`);
const seller = raw("11");
const buyer = raw("22");
const collection = raw("33");
const item = raw("44");
const salt = BigInt("0x" + "01".repeat(32));

const roles = DealRoles.toCell(DealRoles.create({ seller, buyer }));
const asset = DealAsset.toCell(DealAsset.create({
  itemAddress: item,
  collectionAddress: collection,
  dealSalt: salt,
}));
const money = DealMoney.toCell(DealMoney.create({
  principalNanotons: 1_000_000_000n,
  executionReserve: 500_000_000n,
  sellerDeploymentRefundNanotons: 50_000_000n,
  nftTransferValue: 80_000_000n,
  fundQueryId: 1001n,
  nftDepositQueryId: 1002n,
  nftReleaseQueryId: 1003n,
  nftReturnToEscrowQueryId: 1004n,
}));
const oracle = AuthorityKeys.toCell(AuthorityKeys.create({
  keyA: 1n, keyB: 2n, keyC: 3n,
}));
const resolver = AuthorityKeys.toCell(AuthorityKeys.create({
  keyA: 4n, keyB: 5n, keyC: 6n,
}));
const security = DealSecurity.toCell(DealSecurity.create({
  oracleKeys: { ref: oracle },
  resolverKeys: { ref: resolver },
}));
const terms = DealTerms.toCell(DealTerms.create({
  roles: { ref: roles },
  asset: { ref: asset },
  money: { ref: money },
  security: { ref: security },
  networkId: -3n,
  protocolVersion: 1n,
}));
const evidence = DealEvidence.toCell(DealEvidence.create({
  lastEvidenceHash: 0n,
  disputeReasonHash: 0n,
}));
const recovery = DealRecovery.toCell(DealRecovery.create({
  unexpectedPreviousOwner: null,
  unexpectedItemAddress: null,
}));
const progress = DealProgress.toCell(DealProgress.create({
  state: 0n,
  deadlineUnix: 0n,
  disputePhase: 0n,
  pendingAction: 0n,
  nftInEscrow: false,
  principalLocked: false,
  oracleAttemptId: 0n,
  disputeAttemptId: 0n,
  evidence: { ref: evidence },
  recovery: { ref: recovery },
}));
const data = DealEscrow.fromStorage({
  terms: { ref: terms },
  progress: { ref: progress },
});
if (!data.init) throw new Error("Generated Acton wrapper did not return StateInit");
const stateInit = beginCell()
  .storeBit(0) // split_depth = None
  .storeBit(0) // special = None
  .storeBit(1).storeRef(data.init.code) // code = Some(^Cell)
  .storeBit(1).storeRef(data.init.data) // data = Some(^Cell)
  .storeBit(0) // library = empty HashmapE
  .endCell();
if (!stateInit.hash().equals(data.address.hash)) {
  throw new Error("StateInit hash differs from generated Acton wrapper address");
}
if (data.init.code.hash().toString("hex").toUpperCase() !==
    "E9358DAA6FFCC8FCEC979FBD631C7FC0BE336347D1DD44F3F06113E7B2A37548") {
  throw new Error("Generated Acton CodeCell does not match pinned manifest");
}
console.log(JSON.stringify({
  vector: "deal-escrow-v1-testnet-fixed-terms-01",
  address: data.address.toRawString(),
  state_init_hash: stateInit.hash().toString("hex"),
  data_hash: data.init.data.hash().toString("hex"),
  code_hash: data.init.code.hash().toString("hex").toUpperCase(),
}));
