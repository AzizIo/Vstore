import { readFileSync } from "node:fs";
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
const manifest = JSON.parse(
  readFileSync("artifacts/frozen/manifest.json", "utf8"),
) as {
  compiled_code_hash: string;
  state_init_hash: string;
  raw_address: string;
  data_hash: string;
};
const actualVector = {
  vector: "deal-escrow-v1-testnet-fixed-terms-01",
  address: deployed.address.toRawString(),
  state_init_hash: stateInit.hash().toString("hex"),
  data_hash: deployed.init.data.hash().toString("hex"),
  code_hash: deployed.init.code.hash().toString("hex").toUpperCase(),
};
// stdout is redirected by Contract CI into build/state_init_vector.json.
// Emit exactly one JSON object so the following message-vector verifier can parse it
// even if a frozen golden mismatch makes this script exit non-zero.
console.log(JSON.stringify(actualVector));

if (!stateInit.hash().equals(deployed.address.hash)) {
  throw new Error("StateInit hash differs from generated Acton wrapper address");
}
if (deployed.init.code.hash().toString("hex").toUpperCase() !== manifest.compiled_code_hash) {
  throw new Error("Generated Acton CodeCell does not match pinned manifest");
}
if (
  typeof manifest.state_init_hash !== "string"
  || !/^[0-9a-f]{64}$/.test(manifest.state_init_hash)
) {
  throw new Error("Frozen manifest must pin a valid StateInit hash");
}
if (
  typeof manifest.raw_address !== "string"
  || manifest.raw_address !== `0:${manifest.state_init_hash}`
) {
  throw new Error("Frozen manifest must pin the matching basechain raw address");
}
if (
  typeof manifest.data_hash !== "string"
  || !/^[0-9a-f]{64}$/.test(manifest.data_hash)
) {
  throw new Error("Frozen manifest must pin a valid initial data hash");
}
if (stateInit.hash().toString("hex") !== manifest.state_init_hash) {
  throw new Error("Generated fixed StateInit hash differs from frozen golden vector");
}
if (deployed.address.toRawString() !== manifest.raw_address) {
  throw new Error("Generated fixed DealEscrow address differs from frozen golden vector");
}
if (deployed.init.data.hash().toString("hex") !== manifest.data_hash) {
  throw new Error("Generated initial storage cell differs from frozen golden vector");
}

