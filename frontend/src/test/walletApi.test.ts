import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import {
  createWalletProofChallenge,
  unlinkWallet,
  verifyConnectedWallet,
} from "../wallet/api";

const fetchMock = vi.fn();

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    json: async () => body,
  } as Response;
}

describe("wallet proof API", () => {
  beforeEach(() => {
    fetchMock.mockReset();
    vi.stubGlobal("fetch", fetchMock);
  });

  afterEach(() => {
    vi.unstubAllGlobals();
  });

  it("requests a fresh challenge with the authenticated Telegram session", async () => {
    fetchMock.mockResolvedValue(jsonResponse({
      payload: "one-time-server-nonce",
      expires_at: "2099-01-01T00:00:00Z",
    }));

    const result = await createWalletProofChallenge("telegram-access-token");

    expect(result.payload).toBe("one-time-server-nonce");
    expect(fetchMock).toHaveBeenCalledWith(
      "/api/wallets/proof/challenge",
      expect.objectContaining({
        method: "POST",
        headers: expect.objectContaining({
          Authorization: "Bearer telegram-access-token",
          "Content-Type": "application/json",
        }),
      }),
    );
  });

  it("submits the raw account, chain and wallet state init with the returned proof", async () => {
    const linkedWallet = {
      id: "wallet-id",
      address: `0:${"a".repeat(64)}`,
      network: "mainnet",
      is_verified: true,
      is_primary: true,
    };
    fetchMock.mockResolvedValue(jsonResponse(linkedWallet));

    const result = await verifyConnectedWallet(
      "telegram-access-token",
      {
        address: linkedWallet.address,
        chain: "-239",
        walletStateInit: "base64-state-init",
      },
      {
        timestamp: 1_794_238_000,
        domain: { lengthBytes: 15, value: "app.example.com" },
        signature: "base64-signature",
        payload: "one-time-server-nonce",
      },
    );

    expect(result).toEqual(linkedWallet);
    const [url, options] = fetchMock.mock.calls[0] as [string, RequestInit];
    expect(url).toBe("/api/wallets/proof/verify");
    expect(options.method).toBe("POST");
    expect(JSON.parse(String(options.body))).toEqual({
      address: linkedWallet.address,
      network: "-239",
      proof: {
        timestamp: 1_794_238_000,
        domain: { lengthBytes: 15, value: "app.example.com" },
        signature: "base64-signature",
        payload: "one-time-server-nonce",
        state_init: "base64-state-init",
      },
    });
  });

  it("unlinks the wallet through the authenticated wallet lifecycle endpoint", async () => {
    fetchMock.mockResolvedValue({ ok: true, status: 204 } as Response);

    await expect(unlinkWallet("telegram-access-token", "wallet-id")).resolves.toBeUndefined();

    expect(fetchMock).toHaveBeenCalledWith(
      "/api/users/me/wallets/wallet-id",
      expect.objectContaining({
        method: "DELETE",
        headers: expect.objectContaining({
          Authorization: "Bearer telegram-access-token",
        }),
      }),
    );
  });

  it("surfaces the backend conflict when a wallet is still used by live activity", async () => {
    fetchMock.mockResolvedValue({
      ok: false,
      status: 409,
      json: async () => ({ detail: "Close active listings and pending orders before unlinking a wallet." }),
    } as Response);

    await expect(
      unlinkWallet("telegram-access-token", "wallet-id"),
    ).rejects.toThrow("Close active listings and pending orders before unlinking a wallet.");
  });

});