import "./DeliveryWorkspace.css";
import { useCallback, useEffect, useRef, useState } from "react";
import {
  CHAIN,
  TonConnectUIProvider,
  useTonConnectUI,
  useTonWallet,
} from "@tonconnect/ui-react";
import {
  fetchDeliveryState,
  prepareDelivery,
  submitDeliveryCandidate,
  type DeliveryAttempt,
  type OrderDeliveryState,
  type MarketplaceOrder,
  type OrderRole,
} from "../api/orders";
import { fetchMyWallets } from "../wallet/api";

async function loadTonCore() {
  const { Buffer } = await import("buffer");
  const runtime = globalThis as typeof globalThis & { Buffer?: typeof Buffer };
  runtime.Buffer ??= Buffer;
  return import("@ton/core");
}

type LocalTonConnectTestBoundary = {
  wallet?: { account: { address: string; chain: string } } | null;
  sendTransaction?: (request: {
    validUntil: number;
    network: string;
    messages: Array<{ address: string; amount: string; payload: string }>;
  }) => Promise<{ boc: string }>;
};

function localTonConnectTestBoundary(): LocalTonConnectTestBoundary | null {
  // This loopback-only seam mocks the external wallet boundary in API-backed
  // E2E. Its callback/reference is never trusted by the API or observer.
  if (typeof window === "undefined" || !["127.0.0.1", "localhost"].includes(window.location.hostname)) {
    return null;
  }
  return (window as Window & { __VILTARA_TON_CONNECT_TEST__?: LocalTonConnectTestBoundary })
    .__VILTARA_TON_CONNECT_TEST__ ?? null;
}

function networkForChain(chain: string): "mainnet" | "testnet" | null {
  if (chain === CHAIN.MAINNET) return "mainnet";
  if (chain === CHAIN.TESTNET) return "testnet";
  return null;
}

export async function getTransferPayload(attempt: DeliveryAttempt): Promise<string> {
  const { Address, beginCell } = await loadTonCore();
  const queryId = BigInt(attempt.query_id);
  if (queryId < 0n || queryId > 0xffffffffffffffffn) {
    throw new Error("Подготовленная передача содержит некорректный ID запроса.");
  }

  // TEP-62 transfer: exact buyer snapshot + preparation query_id. This cell is
  // sent to the NFT item contract by the seller's own wallet; the server never
  // signs or broadcasts it.
  const payload = beginCell()
    .storeUint(0x5fcc3d14, 32)
    .storeUint(queryId, 64)
    .storeAddress(Address.parse(attempt.buyer_address))
    .storeAddress(Address.parse(attempt.seller_address))
    .storeBit(0) // no custom payload
    .storeCoins(0) // no forwarded TON amount; avoids turning the transfer into a payment
    .storeBit(0) // empty inline forward payload
    .endCell();

  return payload.toBoc().toString("base64");
}

async function walletReference(boc: string): Promise<string> {
  // TON Connect returns the signed external-message BOC, not a confirmed
  // on-chain transaction hash. Its digest is submitted only as a lookup hint;
  // backend verification uses the persisted item/source/destination/query_id.
  const binary = atob(boc);
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}

function deliveryStatus(attempt: DeliveryAttempt | null, orderStatus: MarketplaceOrder["status"]) {
  if (orderStatus === "completed" || attempt?.status === "подтверждённый") return "Передача подтверждена независимо";
  if (attempt?.status === "manual_review") return "Требуется ручная проверка";
  if (attempt?.status === "failed") return "Передача не подтверждена";
  if (attempt?.candidate_transaction_hash || attempt?.submitted_at) return "Перевод отправлен · проверяем";
  if (orderStatus === "observing_transfer" || attempt?.status === "observing") return "Ожидаем действие продавца в кошельке";
  if (attempt?.status === "prepared" || orderStatus === "awaiting_transfer") return "Ожидаем действие продавца в кошельке";
  return "Передача не подготовлена";
}

function DeliveryPanel({
  order,
  role,
  accessToken,
  onRefreshOrder,
  walletActionsEnabled,
}: {
  order: MarketplaceOrder;
  role: OrderRole;
  accessToken: string;
  onRefreshOrder: () => void;
  walletActionsEnabled: boolean;
}) {
  const connectedWallet = useTonWallet();
  const testWalletBoundary = localTonConnectTestBoundary();
  const wallet = connectedWallet ?? testWalletBoundary?.wallet ?? null;
  const [tonConnectUI] = useTonConnectUI();
  const [delivery, setDelivery] = useState<OrderDeliveryState | null>(null);
  const [loading, setLoading] = useState(true);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [message, setMessage] = useState("");
  const [retryReference, setRetryReference] = useState("");
  const [walletResultUncertain, setWalletResultUncertain] = useState(false);
  const prepareKeyRef = useRef<string | null>(null);
  const actionLockRef = useRef(false);

  const refreshDelivery = useCallback(async () => {
    setLoading(true);
    setError("");
    try {
      const state = await fetchDeliveryState(order.id, accessToken);
      setDelivery(state);
      if (
        state.attempt &&
        state.attempt.status !== "prepared" &&
        (state.attempt.status !== "observing" ||
          state.attempt.candidate_transaction_hash !== null ||
          state.attempt.submitted_at !== null)
      ) {
        setWalletResultUncertain(false);
      }
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Статус передачи недоступен.");
    } finally {
      setLoading(false);
    }
  }, [accessToken, order.id]);

  useEffect(() => {
    void refreshDelivery();
  }, [refreshDelivery]);

  async function prepare() {
    if (actionLockRef.current || role !== "seller") return;
    actionLockRef.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    try {
      const connectedNetwork = wallet ? networkForChain(wallet.account.chain) : null;
      if (!wallet || !connectedNetwork) {
        throw new Error("Сначала подключите совместимый TON-кошелёк в основной или тестовой сети.");
      }
      const records = await fetchMyWallets(accessToken);
      const { Address } = await loadTonCore();
      const connectedAddress = Address.parse(wallet.account.address).toRawString();
      const linked = records.find((record) =>
        record.is_verified &&
        record.network === connectedNetwork &&
        Address.parse(record.address).toRawString() === connectedAddress,
      );
      if (!linked) {
        throw new Error("Этот кошелёк не подтверждён для вашего аккаунта продавца. Сначала подтвердите его в разделе кошельков.");
      }
      prepareKeyRef.current ??= crypto.randomUUID();
      const state = await prepareDelivery(order.id, linked.id, accessToken, prepareKeyRef.current);
      setDelivery(state);
      setMessage("Запрос на передачу сохранён. Проверьте адрес получателя и срок действия перед открытием кошелька.");
      onRefreshOrder();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось подготовить передачу NFT.");
    } finally {
      actionLockRef.current = false;
      setBusy(false);
    }
  }

  async function requestWalletTransfer() {
    if (actionLockRef.current || role !== "seller" || !delivery?.attempt) return;
    if (walletResultUncertain) {
      setError("Результат предыдущего запроса к кошельку неизвестен. Обновите статус и проверьте историю кошелька перед повторной попыткой.");
      return;
    }
    actionLockRef.current = true;
    setBusy(true);
    setError("");
    setMessage("");
    let walletRequestStarted = false;
    try {
      const attempt = delivery.attempt;
      const waitingForSellerTransfer =
        attempt.status === "prepared" ||
        (attempt.status === "observing" && !attempt.candidate_transaction_hash && !attempt.submitted_at);
      if (!waitingForSellerTransfer) {
        throw new Error("Этот запрос на передачу больше не ожидает перевода из кошелька.");
      }
      const connectedNetwork = wallet ? networkForChain(wallet.account.chain) : null;
      if (!wallet || !connectedNetwork) {
        throw new Error("Повторно подключите кошелёк продавца перед запросом передачи.");
      }
      if (connectedNetwork !== attempt.network) {
        throw new Error(`Неверная сеть кошелька. Для этой передачи требуется TON ${attempt.network}.`);
      }
      if (Date.parse(attempt.deadline) <= Date.now()) {
        throw new Error("Срок подготовки передачи (15 минут) истёк. Обновите статус перед дальнейшими действиями.");
      }

      const { Address } = await loadTonCore();
      if (Address.parse(wallet.account.address).toRawString() !== Address.parse(attempt.seller_address).toRawString()) {
        throw new Error("Подключённый кошелёк не совпадает с кошельком продавца, указанным в заказе.");
      }
      const payload = await getTransferPayload(attempt);
      const item = Address.parse(attempt.item_address).toString({
        urlSafe: true,
        bounceable: true,
        testOnly: attempt.network === "testnet",
      });
      walletRequestStarted = true;
      setWalletResultUncertain(true);
      const walletRequest = {
        validUntil: Math.floor(Date.parse(attempt.deadline) / 1000),
        network: attempt.network === "testnet" ? CHAIN.TESTNET : CHAIN.MAINNET,
        messages: [{ address: item, amount: "50000000", payload }],
      };
      const result = testWalletBoundary?.sendTransaction
        ? await testWalletBoundary.sendTransaction(walletRequest)
        : await tonConnectUI.sendTransaction(walletRequest);
      const reference = await walletReference(result.boc);
      setRetryReference(reference);
      setMessage("Кошелёк вернул подписанное сообщение. Отправляем ссылку для проверки — это ещё не подтверждение передачи.");
      try {
        const submitted = await submitDeliveryCandidate(order.id, reference, accessToken);
        setDelivery(submitted);
        setRetryReference("");
        setWalletResultUncertain(false);
        setMessage("Ссылка отправлена. Сервер проверяет перевод в блокчейне. Не отправляйте её повторно.");
        onRefreshOrder();
      } catch (reason) {
        setWalletResultUncertain(true);
        setError(reason instanceof Error ? reason.message : "Не удалось отправить ссылку на транзакцию.");
        setMessage("Кошелёк мог уже отправить перевод в сеть. Повторно отправьте эту же ссылку, не подписывая новый перевод.");
      }
    } catch (reason) {
      const walletError = reason && typeof reason === "object"
        ? reason as { code?: number; message?: string }
        : null;
      const rejected = walletError?.code === 300 || /reject|cancel/i.test(walletError?.message ?? "");
      if (walletRequestStarted && !rejected) setWalletResultUncertain(true);
      if (rejected) {
        setWalletResultUncertain(false);
        setError("Запрос кошелька отклонён или отменён. Передача не подтверждена. Проверьте запрос и попробуйте снова.");
      } else if (walletRequestStarted) {
        const detail = reason instanceof Error ? reason.message : "Кошелёк не вернул подтверждённый результат.";
        setError(`Результат запроса к кошельку неизвестен: ${detail} Обновите статус передачи и проверьте историю кошелька перед повторной попыткой.`);
      } else {
        setError(reason instanceof Error ? reason.message : "Не удалось завершить запрос кошелька.");
      }
    } finally {
      actionLockRef.current = false;
      setBusy(false);
    }
  }

  async function retrySubmission() {
    if (!retryReference || actionLockRef.current) return;
    actionLockRef.current = true;
    setBusy(true);
    setError("");
    try {
      const submitted = await submitDeliveryCandidate(order.id, retryReference, accessToken);
      setDelivery(submitted);
      setRetryReference("");
      setWalletResultUncertain(false);
      setMessage("Ссылка отправлена. Дождитесь независимой проверки в блокчейне.");
      onRefreshOrder();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось отправить сохранённую ссылку.");
    } finally {
      actionLockRef.current = false;
      setBusy(false);
    }
  }

  async function openWallet() {
    setError("");
    try {
      await tonConnectUI.openModal();
    } catch {
      setError("Не удалось открыть подключение кошелька. Проверьте, что мини-приложение запущено на настроенном HTTPS-адресе.");
    }
  }

  const attempt = delivery?.attempt ?? null;
  const canPrepare = walletActionsEnabled && role === "seller" && order.status === "reserved" && !attempt;
  const canRequestTransfer = walletActionsEnabled && role === "seller" &&
    ["awaiting_transfer", "observing_transfer"].includes(order.status) &&
    attempt !== null &&
    (attempt.status === "prepared" ||
      (attempt.status === "observing" && !attempt.candidate_transaction_hash && !attempt.submitted_at));
  const showDetails = Boolean(attempt);

  return (
    <section className="workspace-section delivery-workspace" aria-labelledby="delivery-workspace-title">
      <div className="workspace-section-heading">
        <div><p className="eyebrow">ПЕРЕДАЧА БЕЗ ХРАНЕНИЯ СРЕДСТВ</p><h2 id="delivery-workspace-title">Передача NFT</h2></div>
        <span className={`order-status order-status-${order.status}`}>{deliveryStatus(attempt, order.status)}</span>
      </div>
      <p className="order-guidance">
        The seller signs the TEP-62 transfer in their own wallet. The submitted reference is untrusted;
        only the backend observer can confirm delivery from finalized on-chain evidence.
      </p>
      {loading && <p className="workspace-muted" role="status">Загружаем данные о передаче…</p>}
      {error && <p className="orders-error" role="alert">{error}</p>}
      {message && <p className="workspace-muted" role="status">{message}</p>}
      {showDetails && attempt && (
        <dl className="delivery-snapshot">
          <div><dt>Сеть</dt><dd>TON {attempt.network}</dd></div>
          <div><dt>NFT</dt><dd><code>{attempt.item_address}</code></dd></div>
          <div><dt>Кошелёк продавца</dt><dd><code>{attempt.seller_address}</code></dd></div>
          <div><dt>Кошелёк покупателя</dt><dd><code>{attempt.buyer_address}</code></dd></div>
          <div><dt>ID запроса передачи</dt><dd><code>{attempt.query_id}</code></dd></div>
          <div><dt>Срок подготовки</dt><dd>{new Date(attempt.deadline).toLocaleString()}</dd></div>
          {attempt.transaction_hash && <div><dt>Подтверждённая транзакция</dt><dd><code>{attempt.transaction_hash}</code></dd></div>}
          {attempt.masterchain_seqno !== null && <div><dt>Последовательность Masterchain</dt><dd>{attempt.masterchain_seqno}</dd></div>}
          {attempt.verified_at && <div><dt>Подтверждено</dt><dd>{new Date(attempt.verified_at).toLocaleString()}</dd></div>}
        </dl>
      )}
      {walletActionsEnabled && role === "seller" && !wallet && order.status !== "completed" && (
        <button className="secondary-button" type="button" onClick={() => void openWallet()}>Подключить кошелёк продавца</button>
      )}
      {role === "seller" && !walletActionsEnabled && (
        <p className="workspace-muted" role="status">TON Connect не настроен для этого мини-приложения. Подписание операций отключено.</p>
      )}
      {canPrepare && (
        <button className="primary-button" type="button" disabled={busy || loading} onClick={() => void prepare()}>
          {busy ? "Preparing…" : "Подготовить передачу"}
        </button>
      )}
      {canRequestTransfer && (
        <button className="primary-button" type="button" disabled={busy || loading || walletResultUncertain || Boolean(retryReference)} onClick={() => void requestWalletTransfer()}>
          {busy ? "Ожидаем кошелёк…" : "Проверить и подписать в кошельке"}
        </button>
      )}
      {retryReference && (
        <button className="secondary-button" type="button" disabled={busy} onClick={() => void retrySubmission()}>
          {busy ? "Отправляем…" : "Повторно отправить ту же ссылку"}
        </button>
      )}
      {attempt?.status === "manual_review" && (
        <p className="lifecycle-terminal lifecycle-terminal-expired" role="status">
          Delivery needs reconciliation. Do not send another NFT transfer; completion has not been confirmed.
        </p>
      )}
      {(attempt || role === "buyer") && (
        <button className="secondary-button" type="button" disabled={loading} onClick={() => { void refreshDelivery(); onRefreshOrder(); }}>
          Refresh verification status
        </button>
      )}
      <p className="payment-disclaimer">Оплата и эскроу не используются. Кошелёк может запросить комиссию сети. Маркетплейс не получает NFT и не подписывает перевод.</p>
    </section>
  );
}

export function DeliveryWorkspace({
  order,
  role,
  accessToken,
  onRefreshOrder,
}: {
  order: MarketplaceOrder;
  role: OrderRole;
  accessToken: string;
  onRefreshOrder: () => void;
}) {
  const configuredManifestUrl = import.meta.env.VITE_TONCONNECT_MANIFEST_URL?.trim();
  const testBoundary = localTonConnectTestBoundary();
  const manifestUrl = configuredManifestUrl ||
    (typeof window !== "undefined" ? `${window.location.origin}/tonconnect-manifest.json` : "");
  if (!manifestUrl) {
    return <section className="workspace-section" aria-label="Передача NFT"><p className="eyebrow">ПЕРЕДАЧА БЕЗ ХРАНЕНИЯ СРЕДСТВ</p><h2>Передача NFT</h2><p className="workspace-muted">Статус передачи недоступен в этой среде.</p></section>;
  }

  return (
    <TonConnectUIProvider manifestUrl={manifestUrl}>
      <DeliveryPanel
        order={order}
        role={role}
        accessToken={accessToken}
        onRefreshOrder={onRefreshOrder}
        walletActionsEnabled={Boolean(configuredManifestUrl || testBoundary)}
      />
    </TonConnectUIProvider>
  );
}
