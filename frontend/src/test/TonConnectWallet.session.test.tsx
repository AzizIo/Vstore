import { render, screen, waitFor } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

const mocks = vi.hoisted(() => ({
  wallet: null as null | { account: { address: string; chain: string } },
  fetchMyWallets: vi.fn(),
  createWalletProofChallenge: vi.fn(),
  setPrimaryWallet: vi.fn(),
  unlinkWallet: vi.fn(),
  verifyConnectedWallet: vi.fn(),
}));

vi.mock("@tonconnect/ui-react", () => ({
  CHAIN: { MAINNET: "-239", TESTNET: "-3" },
  TonConnectUIProvider: ({ children }: { children: import("react").ReactNode }) => children,
  useTonConnectUI: () => [{
    setConnectRequestParameters: vi.fn(),
    openModal: vi.fn(),
    disconnect: vi.fn(),
  }],
  useTonWallet: () => mocks.wallet,
}));

vi.mock("../wallet/api", () => ({
  fetchMyWallets: mocks.fetchMyWallets,
  createWalletProofChallenge: mocks.createWalletProofChallenge,
  setPrimaryWallet: mocks.setPrimaryWallet,
  unlinkWallet: mocks.unlinkWallet,
  verifyConnectedWallet: mocks.verifyConnectedWallet,
}));

import TonConnectWallet from "../wallet/TonConnectWallet";

const walletAddress = `0:${"a".repeat(64)}`;

const verifiedWallet = {
  id: "wallet-user-a",
  address: walletAddress,
  network: "mainnet",
  is_verified: true,
  is_primary: true,
};

describe("TonConnectWallet session isolation", () => {
  beforeEach(() => {
    mocks.wallet = { account: { address: walletAddress, chain: "-239" } };
    mocks.fetchMyWallets.mockReset();
    mocks.createWalletProofChallenge.mockReset();
    mocks.setPrimaryWallet.mockReset();
    mocks.unlinkWallet.mockReset();
    mocks.verifyConnectedWallet.mockReset();
  });

  afterEach(() => {
    vi.clearAllMocks();
  });

  it("does not carry a previous account's verified wallet into a new session", async () => {
    mocks.fetchMyWallets
      .mockResolvedValueOnce([verifiedWallet])
      .mockResolvedValueOnce([]);

    const onSelectedWalletChange = vi.fn();
    const { rerender } = render(
      <TonConnectWallet
        manifestUrl="https://miniapp.example/tonconnect-manifest.json"
        accessToken="user-a-token"
        onSelectedWalletChange={onSelectedWalletChange}
      />,
    );

    expect(await screen.findByText("Кошелёк подтверждён VILTARA")).toBeInTheDocument();
    await waitFor(() => expect(onSelectedWalletChange).toHaveBeenLastCalledWith(verifiedWallet));

    rerender(
      <TonConnectWallet
        manifestUrl="https://miniapp.example/tonconnect-manifest.json"
        accessToken="user-b-token"
        onSelectedWalletChange={onSelectedWalletChange}
      />,
    );

    expect(await screen.findByText("Подключён · требуется подтверждение владения")).toBeInTheDocument();
    await waitFor(() => expect(onSelectedWalletChange).toHaveBeenLastCalledWith(null));
    expect(mocks.fetchMyWallets).toHaveBeenNthCalledWith(2, "user-b-token", expect.any(AbortSignal));
  });
});
