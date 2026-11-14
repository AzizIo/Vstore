import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PreparedEscrowTransaction } from "../../api/escrow";
import {
  createTonConnectEscrowAdapter,
  TON_TESTNET_CHAIN_ID,
} from "../../escrow/TonConnectEscrowAdapter";

const sellerAddress = `0:${"1".repeat(64)}`;
const wrongAddress = `0:${"2".repeat(64)}`;

function preparedTransaction(overrides: Partial<PreparedEscrowTransaction> = {}): PreparedEscrowTransaction {
  return {
    id: "operation-1",
    action: "nft_deposit",
    network: "testnet",
    contract_address: `0:${"3".repeat(64)}`,
    nft_item_address: `0:${"4".repeat(64)}`,
    amount_ton: "0.05",
    fee_ton: "0",
    network_fee_ton: "0.02",
    valid_until: "2099-01-01T00:00:00.000Z",
    display_summary: "Внести NFT в testnet escrow",
    messages: [{
      address: `0:${"3".repeat(64)}`,
      amount_nanotons: "70000000",
      payload_boc: "server-prepared-payload-boc",
      state_init_boc: null,
    }],
    ...overrides,
  };
}

describe("TON Connect escrow adapter", () => {
  const sendTransaction = vi.fn(async () => ({ boc: "c2VydmVyLXNpZ25lZC1ib2M=" }));
  const now = () => Date.parse("2026-11-14T12:00:00.000Z");

  beforeEach(() => sendTransaction.mockClear());

  it("is disabled unless an explicit opt-in and sender are supplied", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
    });

    expect(adapter.signingEnabled).toBe(false);
    await expect(adapter.sendPreparedTransaction(preparedTransaction(), sellerAddress))
      .rejects.toThrow(/отключено/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });

  it("rejects a mainnet wallet even when the adapter is explicitly enabled", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: "-239" },
      sendTransaction,
      enabled: true,
      now,
    });

    await expect(adapter.sendPreparedTransaction(preparedTransaction(), sellerAddress))
      .rejects.toThrow(/testnet/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });

  it("rejects a wallet that differs from the persisted verified wallet", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: wrongAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });

    await expect(adapter.sendPreparedTransaction(preparedTransaction(), sellerAddress))
      .rejects.toThrow(/не совпадает/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });

  it("rejects an expired prepared transaction", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });

    await expect(adapter.sendPreparedTransaction(
      preparedTransaction({ valid_until: "2026-11-14T11:59:59.000Z" }),
      sellerAddress,
    )).rejects.toThrow(/истёк/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });

  it("forwards only the Backend-prepared messages and testnet network", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });

    await adapter.sendPreparedTransaction(preparedTransaction(), sellerAddress);

    expect(sendTransaction).toHaveBeenCalledWith({
      validUntil: Math.floor(Date.parse("2099-01-01T00:00:00.000Z") / 1000),
      network: TON_TESTNET_CHAIN_ID,
      messages: [{
        address: `0:${"3".repeat(64)}`,
        amount: "70000000",
        payload: "server-prepared-payload-boc",
      }],
    });
  });

  it("rejects invalid or mainnet prepared transaction data", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });

    await expect(adapter.sendPreparedTransaction(
      preparedTransaction({ network: "mainnet" as "testnet" }),
      sellerAddress,
    )).rejects.toThrow(/неподтверждённый формат|основную сеть/i);

    await expect(adapter.sendPreparedTransaction(
      preparedTransaction({ messages: [] }),
      sellerAddress,
    )).rejects.toThrow(/неподтверждённый формат/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });
});
