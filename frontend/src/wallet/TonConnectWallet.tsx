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
  onSelectedWalletChange,
}: {
  manifestUrl: string;
  accessToken: string;
  onSelectedWalletChange: (wallet: WalletRecord | null) => void;
}) {
  return (
    <TonConnectUIProvider manifestUrl={manifestUrl}>
      <WalletControls
        accessToken={accessToken}
        onSelectedWalletChange={onSelectedWalletChange}
      />
    </TonConnectUIProvider>
  );
}

function WalletControls({
  accessToken,
  onSelectedWalletChange,
}: {
  accessToken: string;
  onSelectedWalletChange: (wallet: WalletRecord | null) => void;
}) {
  const wallet = useTonWallet();
  const [tonConnectUI] = useTonConnectUI();
  const network = wallet?.account.chain === CHAIN.MAINNET
    ? "mainnet"
    : wallet?.account.chain === CHAIN.TESTNET
      ? "testnet"
      : null;
  const connectedAddress = wallet?.account.address ?? null;
  const challengeRef = useRef<string | null>(null);
  const connectedAccountRef = useRef<{ address: string; chain: string } | null>(null);
  connectedAccountRef.current = wallet
    ? { address: wallet.account.address, chain: wallet.account.chain }
    : null;
  const [wallets, setWallets] = useState<WalletRecord[]>([]);
  const [isPreparing, setIsPreparing] = useState(false);
  const [isVerifying, setIsVerifying] = useState(false);
  const [isSettingPrimary, setIsSettingPrimary] = useState(false);
  const [isUnlinking, setIsUnlinking] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    const selectedWallet = connectedAddress && network
      ? wallets.find(
          (item) =>
            item.is_verified &&
            item.address === connectedAddress &&
            item.network === network,
        ) ?? null
      : null;
    onSelectedWalletChange(selectedWallet);
  }, [connectedAddress, network, wallets, onSelectedWalletChange]);

  useEffect(() => {
    const controller = new AbortController();
    void fetchMyWallets(accessToken, controller.signal)
      .then((records) => setWallets((current) => [
        ...records,
        ...current.filter((item) => !records.some((record) => record.id === item.id)),
      ]))
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Не удалось загрузить подключённые кошельки.");
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
      setError("Кошелёк не вернул TON Proof. Подключите кошелёк с поддержкой подтверждения владения.");
      return;
    }
    if (proofReply.proof.payload !== expectedPayload) {
      setError("Кошелёк вернул подтверждение для другого запроса. Подключитесь повторно и попробуйте ещё раз.");
      return;
    }

    setIsVerifying(true);
    setError("");
    const expectedNetwork = wallet.account.chain === CHAIN.MAINNET
      ? "mainnet"
      : wallet.account.chain === CHAIN.TESTNET
        ? "testnet"
        : null;
    const expectedAccount = {
      address: wallet.account.address,
      chain: wallet.account.chain,
    };
    void verifyConnectedWallet(accessToken, wallet.account, proofReply.proof)
      .then(async (record) => {
        if (
          !expectedNetwork ||
          !record.is_verified ||
          record.address !== expectedAccount.address ||
          record.network !== expectedNetwork
        ) {
          throw new Error("Сервер не подтвердил этот кошелёк.");
        }

        // Re-fetch the persisted record after proof verification. The POST response
        // alone is not the UI's durable source of truth.
        const records = await fetchMyWallets(accessToken);
        const activeAccount = connectedAccountRef.current;
        if (
          !activeAccount ||
          activeAccount.address !== expectedAccount.address ||
          activeAccount.chain !== expectedAccount.chain
        ) {
          return;
        }
        const confirmed = records.find(
          (item) =>
            item.id === record.id &&
            item.is_verified &&
            item.address === expectedAccount.address &&
            item.network === expectedNetwork,
        );
        if (!confirmed) {
          throw new Error("Сервер не нашёл подтверждённый кошелёк в списке подключённых.");
        }
        setWallets((current) => [
          ...current.filter((item) => item.id !== confirmed.id),
          confirmed,
        ]);
      })
      .catch((reason: unknown) => {
        setError(reason instanceof Error ? reason.message : "Не удалось подтвердить владение кошельком.");
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
        throw new Error("Срок действия запроса TON Proof истёк. Попробуйте ещё раз.");
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
      setError(reason instanceof Error ? reason.message : "Не удалось начать проверку кошелька.");
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
      setError(reason instanceof Error ? reason.message : "Не удалось изменить основной кошелёк.");
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
      setError(reason instanceof Error ? reason.message : "Не удалось отвязать этот кошелёк.");
      setIsUnlinking(false);
      return;
    }

    try {
      await tonConnectUI.disconnect();
    } catch {
      setError("Кошелёк отвязан, но завершить сессию TonConnect не удалось.");
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
      setError("Не удалось отключить кошелёк. Попробуйте ещё раз.");
    }
  }

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
          {isPreparing ? "Подготавливаем…" : "Подключить и подтвердить"}
        </button>
        {error && <span className="wallet-error" role="alert">{error}</span>}
      </div>
    );
  }

  const address = wallet.account.address;
  const shortAddress = `${address.slice(0, 6)}…${address.slice(-4)}`;
  const networkLabel = network === "mainnet"
    ? "Основная сеть"
    : network === "testnet"
      ? "Тестовая сеть"
      : "Неподдерживаемая сеть";

  return (
    <div id="wallet-connect" className="wallet-control">
      <span className="wallet-account" role="status">
        <span className="wallet-address">{shortAddress}</span>
        <span className="wallet-network">{networkLabel}</span>
        <span className="wallet-disclaimer">
          {verified ? "Кошелёк подтверждён VILTARA" : "Подключён · требуется подтверждение владения"}
        </span>
      </span>
      <button
        className="wallet-button"
        type="button"
        onClick={() => void connectAndVerify()}
        disabled={isPreparing || isVerifying}
      >
        {isPreparing ? "Подготавливаем…" : isVerifying ? "Проверяем…" : verified ? "Подключить повторно" : "Подключить и подтвердить"}
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
          {isSettingPrimary ? "Обновляем…" : "Сделать основным"}
        </button>
      )}
      {verified && (
        <button
          className="wallet-button wallet-disconnect"
          type="button"
          onClick={() => void unlinkCurrentWallet()}
          disabled={isUnlinking}
        >
          {isUnlinking ? "Отвязываем…" : "Отвязать кошелёк"}
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
