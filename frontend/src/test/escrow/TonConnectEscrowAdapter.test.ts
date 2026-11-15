import { beforeEach, describe, expect, it, vi } from "vitest";

import type { PreparedEscrowTransaction } from "../../api/escrow";
import {
  createTonConnectEscrowAdapter,
  TON_TESTNET_CHAIN_ID,
} from "../../escrow/TonConnectEscrowAdapter";

const sellerAddress = "0:" + "1".repeat(64);
const wrongAddress = "0:" + "2".repeat(64);
const itemAddress = "0:" + "3".repeat(64);
const escrowAddress = "0:" + "4".repeat(64);

function preparedTransaction(
  action: PreparedEscrowTransaction["action"] = "fund_deal",
  overrides: Partial<PreparedEscrowTransaction> = {},
): PreparedEscrowTransaction {
  const deploymentAction = action === "create_deal_escrow";
  const nftAction = action === "deposit_nft" || action === "return_nft_to_escrow";
  const destination = nftAction ? itemAddress : escrowAddress;
  return {
    action_id: "operation-1",
    action,
    network: "testnet",
    factory_address: null,
    escrow_address: escrowAddress,
    nft_item_address: itemAddress,
    price_nano: "2500000000",
    fee_bps: 0,
    execution_reserve_nano: "20000000",
    valid_until: "2099-01-01T00:00:00.000Z",
    display_purpose: "Проверьте параметры escrow-операции",
    messages: [{
      address: destination,
      amount_nano: "2520000000",
      payload_boc: deploymentAction ? null : "server-prepared-payload-boc",
      state_init_boc: deploymentAction ? "server-prepared-state-init-boc" : null,
    }],
    ...overrides,
  };
}

describe("TON Connect escrow adapter", () => {
  const sendTransaction = vi.fn(async () => ({ boc: "c2VydmVyLXNpZ25lZC1ib2M=" }));
  const now = () => Date.parse("2026-11-14T12:00:00.000Z");

  beforeEach(() => sendTransaction.mockClear());

  it("is disabled unless explicit testnet opt-in and a sender are supplied", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
    });

    expect(adapter.signingEnabled).toBe(false);
    await expect(adapter.sendPreparedTransaction(preparedTransaction(), sellerAddress))
      .rejects.toThrow(/отключено/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });

  it("rejects a mainnet wallet when the adapter is enabled", async () => {
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

  it("rejects a connected wallet that differs from the Backend-verified wallet", async () => {
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
      preparedTransaction("fund_deal", { valid_until: "2026-11-14T11:59:59.000Z" }),
      sellerAddress,
    )).rejects.toThrow(/истёк/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });

  it("forwards a direct per-deal StateInit deployment unchanged after checking its DealEscrow recipient", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });

    const transaction = preparedTransaction("create_deal_escrow");
    await adapter.sendPreparedTransaction(transaction, sellerAddress);

    expect(sendTransaction).toHaveBeenCalledWith({
      validUntil: Math.floor(Date.parse(transaction.valid_until) / 1000),
      network: TON_TESTNET_CHAIN_ID,
      messages: [{
        address: escrowAddress,
        amount: "2520000000",
        stateInit: "server-prepared-state-init-boc",
      }],
    });
  });

  it.each([
    ["deposit_nft", itemAddress],
    ["fund_deal", escrowAddress],
    ["accept_deal", escrowAddress],
    ["open_dispute", escrowAddress],
    ["return_nft_to_escrow", itemAddress],
    ["withdraw_unsold_nft", escrowAddress],
  ] as const)("allows %s only to its action-specific recipient", async (action, recipient) => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });
    const transaction = preparedTransaction(action);
    await adapter.sendPreparedTransaction(transaction, sellerAddress);
    expect(sendTransaction).toHaveBeenCalledWith(expect.objectContaining({
      messages: [expect.objectContaining({ address: recipient })],
    }));
  });

  it("rejects a message destination that does not match the action allowlist", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });

    await expect(adapter.sendPreparedTransaction(
      preparedTransaction("fund_deal", {
        messages: [{
          address: itemAddress,
          amount_nano: "2520000000",
          payload_boc: null,
          state_init_boc: null,
        }],
      }),
      sellerAddress,
    )).rejects.toThrow(/получатель TON-сообщения/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });

  it("rejects a direct deployment without its backend-derived StateInit", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });

    await expect(adapter.sendPreparedTransaction(
      preparedTransaction("create_deal_escrow", {
        messages: [{
          address: escrowAddress,
          amount_nano: "2520000000",
          payload_boc: null,
          state_init_boc: null,
        }],
      }),
      sellerAddress,
    )).rejects.toThrow(/неподтверждённый формат/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });

  it("rejects an obsolete Factory deployment payload", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });

    await expect(adapter.sendPreparedTransaction(
      preparedTransaction("create_deal_escrow", {
        factory_address: ("0:" + "5".repeat(64)) as unknown as null,
      }),
      sellerAddress,
    )).rejects.toThrow(/неподтверждённый формат/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });

  it("rejects malformed and non-testnet prepared transactions", async () => {
    const adapter = createTonConnectEscrowAdapter({
      connectedWallet: { address: sellerAddress, chain: TON_TESTNET_CHAIN_ID },
      sendTransaction,
      enabled: true,
      now,
    });

    await expect(adapter.sendPreparedTransaction(
      preparedTransaction("fund_deal", { network: "mainnet" as "testnet" }),
      sellerAddress,
    )).rejects.toThrow(/неподтверждённый формат/i);

    await expect(adapter.sendPreparedTransaction(
      preparedTransaction("fund_deal", { fee_bps: 1 as 0 }),
      sellerAddress,
    )).rejects.toThrow(/неподтверждённый формат/i);

    await expect(adapter.sendPreparedTransaction(
      preparedTransaction("fund_deal", { messages: [] }),
      sellerAddress,
    )).rejects.toThrow(/неподтверждённый формат/i);
    expect(sendTransaction).not.toHaveBeenCalled();
  });
});
