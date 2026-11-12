import { describe, expect, it } from "vitest";
import { Address, Cell } from "@ton/core";

import { getTransferPayload } from "../orders/DeliveryWorkspace";
import type { DeliveryAttempt } from "../api/orders";

const rawAddress = (digit: string) => `0:${digit.repeat(64)}`;

function preparedAttempt(overrides: Partial<DeliveryAttempt> = {}): DeliveryAttempt {
  return {
    id: "attempt-1",
    status: "prepared",
    network: "testnet",
    item_address: rawAddress("3"),
    seller_address: rawAddress("1"),
    buyer_address: rawAddress("2"),
    query_id: "18446744073709551615",
    prepared_at: "2026-11-12T10:00:00Z",
    deadline: "2026-11-12T10:15:00Z",
    submitted_at: null,
    candidate_transaction_hash: null,
    transaction_hash: null,
    trace_id: null,
    masterchain_seqno: null,
    verified_at: null,
    ...overrides,
  };
}

describe("getTransferPayload", () => {
  it("encodes the exact TEP-62 opcode, persisted query_id and snapshotted recipient/source", async () => {
    const attempt = preparedAttempt();
    const payload = await getTransferPayload(attempt);
    const slice = Cell.fromBase64(payload).beginParse();

    expect(slice.loadUint(32)).toBe(0x5fcc3d14);
    expect(slice.loadUintBig(64)).toBe(18446744073709551615n);
    expect(slice.loadAddress()?.toRawString()).toBe(Address.parse(attempt.buyer_address).toRawString());
    expect(slice.loadAddress()?.toRawString()).toBe(Address.parse(attempt.seller_address).toRawString());
    expect(slice.loadBit()).toBe(false); // no custom payload
    expect(slice.loadCoins()).toBe(0n); // no forward amount
    expect(slice.loadBit()).toBe(false); // empty inline forward payload
    expect(slice.remainingBits).toBe(0);
    expect(slice.remainingRefs).toBe(0);
  });

  it("rejects a query_id outside the unsigned 64-bit range", async () => {
    await expect(getTransferPayload(preparedAttempt({ query_id: "18446744073709551616" })))
      .rejects.toThrow("invalid query ID");
  });
});
