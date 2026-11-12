import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { Address, Cell } from "@ton/core";

import type { DeliveryAttempt, MarketplaceOrder, OrderDeliveryState } from "../api/orders";
import { DeliveryWorkspace } from "../orders/DeliveryWorkspace";

const mocks = vi.hoisted(() => ({
  wallet: null as { account: { address: string; chain: string } } | null,
  sendTransaction: vi.fn(),
  openModal: vi.fn(),
  fetchDeliveryState: vi.fn(),
  prepareDelivery: vi.fn(),
  submitDeliveryCandidate: vi.fn(),
  fetchMyWallets: vi.fn(),
}));

vi.mock("@tonconnect/ui-react", () => ({
  CHAIN: { MAINNET: "-239", TESTNET: "-3" },
  TonConnectUIProvider: ({ children }: { children: React.ReactNode }) => children,
  useTonWallet: () => mocks.wallet,
  useTonConnectUI: () => [{ sendTransaction: mocks.sendTransaction, openModal: mocks.openModal }],
}));

vi.mock("../api/orders", async (importOriginal) => {
  const actual = await importOriginal<typeof import("../api/orders")>();
  return {
    ...actual,
    fetchDeliveryState: mocks.fetchDeliveryState,
    prepareDelivery: mocks.prepareDelivery,
    submitDeliveryCandidate: mocks.submitDeliveryCandidate,
  };
});

vi.mock("../wallet/api", () => ({ fetchMyWallets: mocks.fetchMyWallets }));

const rawAddress = (digit: string) => `0:${digit.repeat(64)}`;

function attempt(overrides: Partial<DeliveryAttempt> = {}): DeliveryAttempt {
  return {
    id: "attempt-123",
    status: "prepared",
    network: "testnet",
    item_address: rawAddress("3"),
    seller_address: rawAddress("1"),
    buyer_address: rawAddress("2"),
    query_id: "123456789",
    prepared_at: new Date(Date.now() - 1000).toISOString(),
    deadline: new Date(Date.now() + 10 * 60_000).toISOString(),
    submitted_at: null,
    candidate_transaction_hash: null,
    transaction_hash: null,
    trace_id: null,
    masterchain_seqno: null,
    verified_at: null,
    ...overrides,
  };
}

function order(status: MarketplaceOrder["status"]): MarketplaceOrder {
  return {
    id: "order-123",
    listing_id: "listing-123",
    buyer_id: "buyer-123",
    seller_id: "seller-123",
    status,
    price_amount: "1",
    price_currency: "TON",
    title: "Test NFT",
    asset_name: "Test NFT",
    asset_type: "ton_nft",
    expires_at: new Date(Date.now() + 30 * 60_000).toISOString(),
    created_at: new Date().toISOString(),
    updated_at: new Date().toISOString(),
    events: [],
  };
}

function deliveryState(
  status: MarketplaceOrder["status"],
  preparedAttempt: DeliveryAttempt | null,
): OrderDeliveryState {
  return { order_id: "order-123", order_status: status, attempt: preparedAttempt };
}

beforeEach(() => {
  vi.clearAllMocks();
  mocks.wallet = { account: { address: rawAddress("1"), chain: "-3" } };
  mocks.fetchDeliveryState.mockResolvedValue(deliveryState("awaiting_transfer", attempt()));
  mocks.fetchMyWallets.mockResolvedValue([{
    id: "seller-wallet",
    address: rawAddress("1"),
    network: "testnet",
    is_verified: true,
    is_primary: true,
  }]);
  mocks.prepareDelivery.mockResolvedValue(deliveryState("awaiting_transfer", attempt()));
  mocks.submitDeliveryCandidate.mockResolvedValue(deliveryState("observing_transfer", attempt({
    status: "observing",
    submitted_at: new Date().toISOString(),
    candidate_transaction_hash: "ab".repeat(32),
  })));
  mocks.sendTransaction.mockResolvedValue({ boc: btoa("signed external message BOC") });
  vi.stubGlobal("crypto", {
    randomUUID: () => "stable-prepare-idempotency-key",
    subtle: { digest: vi.fn().mockResolvedValue(new Uint8Array(32).buffer) },
  });
});

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("DeliveryWorkspace", () => {
  it("builds the exact prepared transfer and submits only an untrusted wallet reference", async () => {
    const onRefreshOrder = vi.fn();
    render(
      <DeliveryWorkspace
        order={order("awaiting_transfer")}
        role="seller"
        accessToken="test-token"
        onRefreshOrder={onRefreshOrder}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Review and sign in wallet" }));

    await waitFor(() => expect(mocks.sendTransaction).toHaveBeenCalledTimes(1));
    const request = mocks.sendTransaction.mock.calls[0][0];
    expect(request.network).toBe("-3");
    expect(request.validUntil).toBe(Math.floor(Date.parse(attempt().deadline) / 1000));
    expect(request.messages).toHaveLength(1);
    expect(request.messages[0].address).toBe(Address.parse(rawAddress("3")).toString({
      urlSafe: true, bounceable: true, testOnly: true,
    }));
    expect(request.messages[0].amount).toBe("50000000");

    const slice = Cell.fromBase64(request.messages[0].payload).beginParse();
    expect(slice.loadUint(32)).toBe(0x5fcc3d14);
    expect(slice.loadUintBig(64)).toBe(123456789n);
    expect(slice.loadAddress()?.toRawString()).toBe(rawAddress("2"));
    expect(slice.loadAddress()?.toRawString()).toBe(rawAddress("1"));

    await waitFor(() => expect(mocks.submitDeliveryCandidate).toHaveBeenCalledTimes(1));
    const [submittedOrderId, reference, token] = mocks.submitDeliveryCandidate.mock.calls[0];
    expect(submittedOrderId).toBe("order-123");
    expect(reference).toMatch(/^[a-f0-9]{64}$/);
    expect(token).toBe("test-token");
    expect(screen.getByText(/Transfer submitted · verifying/)).toBeTruthy();
    expect(screen.queryByText(/Transfer independently verified/)).toBeNull();
    expect(onRefreshOrder).toHaveBeenCalled();
  });

  it("does not submit a candidate when the seller rejects the wallet request", async () => {
    mocks.sendTransaction.mockRejectedValue(Object.assign(new Error("User rejected the request"), { code: 300 }));
    render(
      <DeliveryWorkspace
        order={order("awaiting_transfer")}
        role="seller"
        accessToken="test-token"
        onRefreshOrder={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Review and sign in wallet" }));
    expect(await screen.findByText(/wallet request was rejected or cancelled/i)).toBeTruthy();
    expect(mocks.submitDeliveryCandidate).not.toHaveBeenCalled();
  });

  it("blocks another wallet request after an uncertain wallet result", async () => {
    mocks.sendTransaction.mockRejectedValue(new Error("connection timed out"));
    render(
      <DeliveryWorkspace
        order={order("awaiting_transfer")}
        role="seller"
        accessToken="test-token"
        onRefreshOrder={vi.fn()}
      />,
    );

    const action = await screen.findByRole("button", { name: "Review and sign in wallet" });
    fireEvent.click(action);
    await waitFor(() => expect(action).toBeDisabled());
    expect(screen.getByText(/wallet result is uncertain/i)).toBeTruthy();
    expect(mocks.submitDeliveryCandidate).not.toHaveBeenCalled();
  });

  it("only opens the wallet connection UI when the seller is disconnected", async () => {
    mocks.wallet = null;
    render(
      <DeliveryWorkspace
        order={order("awaiting_transfer")}
        role="seller"
        accessToken="test-token"
        onRefreshOrder={vi.fn()}
      />,
    );

    fireEvent.click(await screen.findByRole("button", { name: "Connect seller wallet" }));
    expect(mocks.openModal).toHaveBeenCalledTimes(1);
    expect(mocks.submitDeliveryCandidate).not.toHaveBeenCalled();
  });
});
