import { useEffect, useRef, useState } from "react";
import {
  CHAIN,
  TonConnectUIProvider,
  useTonConnectUI,
  useTonWallet,
} from "@tonconnect/ui-react";

import {
  createWalletProofChallenge,
  fetchMyWallets,
  setPrimaryWallet,
  unlinkWallet,
  verifyConnectedWallet,
  type WalletRecord,
} from "./api";

export default function TonConnectWallet({
  manifestUrl,
  accessToken,
}: {
  manifestUrl: string;
  accessToken: string;
}) {
  return (
    <TonConnectUIProvider manifestUrl={manifestUrl}>
      <WalletControls accessToken={accessToken} />
    </TonConnectUIProvider>
  );
}

function WalletControls({ accessToken }: { accessToken: string }) {
  const wallet = useTonWallet();
  const [tonConnectUI] = useTonConnectUI();
  const challengeRef = useRef<string | null>(null);
  const [wallets, setWallets] = useState<WalletRecord[]>([]);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isSettingPrimary, setIsSettingPrimary] = useState(false);
  const [isUnlinking, setIsUnlinking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const controller = new AbortController();
    void fetchMyWallets(accessToken, controller.signal)
      .then((records) => setWallets((current) => [
        ...records,
        ...current.filter((item) => !records.some((record) => record.id === item.id)),
      ]))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Could not load linked wallets.");
        }
      });
    return () => controller.abort();
  }, [accessToken]);

  useEffect(() => {
    if (!wallet || !challengeRef.current) return;

    const expectedPayload = challengeRef.current;
    const proofReply = wallet.connectItems?.tonProof;
    challengeRef.current = null;
    tonConnectUI.setConnectRequestParameters({ state: "loading" });

    if (!proofReply || !("proof" in proofReply)) {
      setError("This wallet did not return TON Proof. Reconnect with a wallet that supports proof authentication.");
      return;
    }
    if (proofReply.proof.payload !== expectedPayload) {
      setError("The wallet returned a proof for a different login challenge. Reconnect and try again.");
      return;
    }

    setIsVerifying(true);
    setError("");
    const expectedNetwork = wallet.account.chain === CHAIN.MAINNET
      ? "mainnet"
      : wallet.account.chain === CHAIN.TESTNET
        ? "testnet"
        : null;
    void verifyConnectedWallet(accessToken, wallet.account, proofReply.proof)
      .then((record) => {
        if (
          expectedNetwork &&
          record.is_verified &&
          record.address === wallet.account.address &&
          record.network === expectedNetwork
        ) {
          setWallets((current) => [
            ...current.filter((item) => item.id !== record.id),
            record,
          ]);
        } else {
          setError("The backend did not confirm this wallet.");
        }
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Wallet proof verification failed.");
      })
      .finally(() => setIsVerifying(false));
  }, [wallet, accessToken]);

  async function connectAndVerify() {
    setError("");
    setIsPreparing(true);
    challengeRef.current = null;
    try {
      tonConnectUI.setConnectRequestParameters({ state: "loading" });
      const challenge = await createWalletProofChallenge(accessToken);
      const challengeExpiresAt = Date.parse(challenge.expires_at);
      if (!Number.isFinite(challengeExpiresAt) || challengeExpiresAt <= Date.now()) {
        throw new Error("Wallet proof challenge expired. Please try again.");
      }

      // Restored sessions do not contain a fresh proof. Disconnect first so the
      // next connection is explicitly bound to the challenge just issued.
      if (wallet) await tonConnectUI.disconnect();

      challengeRef.current = challenge.payload;
      tonConnectUI.setConnectRequestParameters({
        state: "ready",
        value: { tonProof: challenge.payload },
      });
      await tonConnectUI.openModal();
    } catch (reason) {
      challengeRef.current = null;
      tonConnectUI.setConnectRequestParameters({ state: "loading" });
      setError(reason instanceof Error ? reason.message : "Could not start wallet verification.");
    } finally {
      setIsPreparing(false);
    }
  }

  async function makePrimary() {
    const current = wallets.find(
      (item) => item.address === wallet?.account.address && item.network === network && item.is_verified,
    );
    if (!current) return;
    setError("");
    setIsSettingPrimary(true);
    try {
      const updated = await setPrimaryWallet(accessToken, current.id);
      setWallets((items) => items.map((item) => ({ ...item, is_primary: item.id === updated.id })));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not update the primary wallet.");
    } finally {
      setIsSettingPrimary(false);
    }
  }

  async function unlinkCurrentWallet() {
    const current = wallets.find(
      (item) =>
        item.address === wallet?.account.address &&
        item.network === network &&
        item.is_verified,
    );
    if (!current) return;

    setError("");
    setIsUnlinking(true);
    try {
      await unlinkWallet(accessToken, current.id);
      setWallets((items) => items.filter((item) => item.id !== current.id));
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not unlink this wallet.");
      setIsUnlinking(false);
      return;
    }

    try {
      await tonConnectUI.disconnect();
    } catch {
      setError("The wallet was unlinked, but the TonConnect session could not be disconnected.");
    } finally {
      setIsUnlinking(false);
    }
  }

  async function disconnectWallet() {
    setError("");
    challengeRef.current = null;
    tonConnectUI.setConnectRequestParameters({ state: "loading" });
    try {
      await tonConnectUI.disconnect();
    } catch {
      setError("Could not disconnect the wallet. Please try again.");
    }
  }

  const network = wallet?.account.chain === CHAIN.MAINNET
    ? "mainnet"
    : wallet?.account.chain === CHAIN.TESTNET
      ? "testnet"
      : null;
  const verified = Boolean(
    wallet &&
    network &&
    wallets.some(
      (item) =>
        item.is_verified &&
        item.address === wallet.account.address &&
        item.network === network,
    ),
  );

  if (!wallet) {
    return (
      <div id="wallet-connect" className="wallet-control">
        <button
          className="wallet-button"
          type="button"
          onClick={() => void connectAndVerify()}
          disabled={isPreparing || isVerifying}
        >
          {isPreparing ? "Preparing..." : "Connect & verify"}
        </button>
        {error && <span className="wallet-error" role="alert">{error}</span>}
      </div>
    );
  }

  const address = wallet.account.address;
  const shortAddress = `${address.slice(0, 6)}…${address.slice(-4)}`;
  const networkLabel = network === "mainnet"
    ? "Mainnet"
    : network === "testnet"
      ? "Testnet"
      : "Unsupported network";

  return (
    <div id="wallet-connect" className="wallet-control">
      <span className="wallet-account" role="status">
        <span className="wallet-address">{shortAddress}</span>
        <span className="wallet-network">{networkLabel}</span>
        <span className="wallet-disclaimer">
          {verified ? "Wallet verified by VILTARA" : "Connected only · proof verification required"}
        </span>
      </span>
      <button
        className="wallet-button"
        type="button"
        onClick={() => void connectAndVerify()}
        disabled={isPreparing || isVerifying}
      >
        {isPreparing ? "Preparing..." : isVerifying ? "Verifying..." : verified ? "Reconnect" : "Reconnect & verify"}
      </button>
      {verified && !wallets.some(
        (item) => item.address === wallet.account.address && item.network === network && item.is_primary,
      ) && (
        <button
          className="wallet-button"
          type="button"
          onClick={() => void makePrimary()}
          disabled={isSettingPrimary}
        >
          {isSettingPrimary ? "Updating..." : "Make primary"}
        </button>
      )}
      {verified && (
        <button
          className="wallet-button wallet-disconnect"
          type="button"
          onClick={() => void unlinkCurrentWallet()}
          disabled={isUnlinking}
        >
          {isUnlinking ? "Unlinking..." : "Unlink wallet"}
        </button>
      )}
      <button
        className="wallet-button wallet-disconnect"
        type="button"
        onClick={() => void disconnectWallet()}
      >
        Disconnect
      </button>
      {error && <span className="wallet-error" role="alert">{error}</span>}
    </div>
  );
}
