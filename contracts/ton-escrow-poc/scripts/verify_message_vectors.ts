import { createHash } from "node:crypto";
import { beginCell, Address } from "@ton/core";
import {
  ActivateDeal,
  AcceptDeal,
  FundDeal,
  NftTransfer,
  OpenDispute,
  PayloadInline,
  RecoverUnexpectedNft,
  TimeoutDeal,
} from "../wrappers-ts/DealEscrow.gen.ts";

const salt = BigInt("0x" + "01".repeat(32));
const reasonHash = BigInt("0x" + "ab".repeat(32));
const seller = Address.parseRaw("0:" + "11".repeat(32));
const buyer = Address.parseRaw("0:" + "22".repeat(32));
const escrow = Address.parseRaw(
  "0:31ffca176042bdc4aa82e21949f900d2c068634306da76b1ebb335e64bd5cf52",
);
const forwardPayload = PayloadInline.create({
  value: beginCell()
    .storeUint(0x56454e46, 32)
    .storeUint(salt, 256)
    .endCell()
    .beginParse(),
});
const nftDeposit = NftTransfer.toCell(NftTransfer.create({
  queryId: 1002n,
  newOwnerAddress: escrow,
  sendExcessesTo: seller,
  customPayload: null,
  forwardTonAmount: 10_000_000n,
  forwardPayload,
}));
const nftReturn = NftTransfer.toCell(NftTransfer.create({
  queryId: 1004n,
  newOwnerAddress: escrow,
  sendExcessesTo: buyer,
  customPayload: null,
  forwardTonAmount: 10_000_000n,
  forwardPayload,
}));
const bodies = {
  activate: ActivateDeal.toCell(ActivateDeal.create({ queryId: 1000n, dealSalt: salt })),
  fund: FundDeal.toCell(FundDeal.create({ queryId: 1001n, dealSalt: salt })),
  accept: AcceptDeal.toCell(AcceptDeal.create({ queryId: 1003n, dealSalt: salt })),
  dispute: OpenDispute.toCell(OpenDispute.create({
    queryId: 2001n, dealSalt: salt, reasonHash,
  })),
  timeout: TimeoutDeal.toCell(TimeoutDeal.create({ queryId: 2002n, dealSalt: salt })),
  recovery: RecoverUnexpectedNft.toCell(RecoverUnexpectedNft.create({
    queryId: 2003n, dealSalt: salt,
  })),
  nft_deposit: nftDeposit,
  nft_return: nftReturn,
};
const result = Object.fromEntries(
  Object.entries(bodies).map(([name, cell]) => {
    const boc = cell.toBoc({ idx: false, crc32: true });
    return [name, {
      cell_hash: cell.hash().toString("hex"),
      boc_sha256: createHash("sha256").update(boc).digest("hex"),
      boc_base64: boc.toString("base64"),
    }];
  }),
);
console.log(JSON.stringify({
  vector: "deal-escrow-v1-message-fixed-terms-01",
  salt: salt.toString(16).padStart(64, "0"),
  reason_hash: reasonHash.toString(16).padStart(64, "0"),
  messages: result,
}));
