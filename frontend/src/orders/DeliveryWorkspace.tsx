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
    throw new Error("The prepared transfer contains an invalid query ID.");
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
  if (orderStatus === "completed" || attempt?.status === "verified") return "Transfer independently verified";
  if (attempt?.status === "manual_review") return "Manual review required";
  if (attempt?.status === "failed") return "Transfer not verified";
  if (attempt?.candidate_transaction_hash || attempt?.submitted_at) return "Transfer submitted · verifying";
  if (orderStatus === "observing_transfer" || attempt?.status === "observing") return "Watching chain · awaiting seller wallet action";
  if (attempt?.status === "prepared" || orderStatus === "awaiting_transfer") return "Awaiting seller wallet action";
  return "Delivery not prepared";
}

function DeliveryPanel({
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
      setError(reason instanceof Error ? reason.message : "Delivery status is unavailable.");
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
        throw new Error("Connect a supported TON wallet on mainnet or testnet first.");
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
        throw new Error("This connected wallet is not verified for your seller account. Verify it in Wallets first.");
      }
      prepareKeyRef.current ??= crypto.randomUUID();
      const state = await prepareDelivery(order.id, linked.id, accessToken, prepareKeyRef.current);
      setDelivery(state);
      setMessage("Delivery intent saved. Review the recipient and deadline before opening your wallet.");
      onRefreshOrder();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not prepare the NFT transfer.");
    } finally {
      actionLockRef.current = false;
      setBusy(false);
    }
  }

  async function requestWalletTransfer() {
    if (actionLockRef.current || role !== "seller" || !delivery?.attempt) return;
    if (walletResultUncertain) {
      setError("The previous wallet result is uncertain. Refresh status and check wallet activity before retrying.");
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
        throw new Error("This delivery intent is no longer waiting for a wallet transfer.");
      }
      const connectedNetwork = wallet ? networkForChain(wallet.account.chain) : null;
      if (!wallet || !connectedNetwork) {
        throw new Error("Reconnect the seller wallet before requesting a transfer.");
      }
      if (connectedNetwork !== attempt.network) {
        throw new Error(`Wrong wallet network. This delivery requires TON ${attempt.network}.`);
      }
      if (Date.parse(attempt.deadline) <= Date.now()) {
        throw new Error("The 15-minute delivery preparation window has expired. Refresh status before taking action.");
      }

      const { Address } = await loadTonCore();
      if (Address.parse(wallet.account.address).toRawString() !== Address.parse(attempt.seller_address).toRawString()) {
        throw new Error("The connected wallet does not match the snapshotted seller source.");
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
      setMessage("Wallet returned a signed message. Sending its reference for lookup; this is not proof of delivery.");
      try {
        const submitted = await submitDeliveryCandidate(order.id, reference, accessToken);
        setDelivery(submitted);
        setRetryReference("");
        setWalletResultUncertain(false);
        setMessage("Reference submitted. The backend observer is checking the exact on-chain transfer; do not send it again.");
        onRefreshOrder();
      } catch (reason) {
        setWalletResultUncertain(true);
        setError(reason instanceof Error ? reason.message : "Reference submission failed.");
        setMessage("The wallet may already have broadcast the transfer. Retry submitting this same reference; do not sign another transfer.");
      }
    } catch (reason) {
      const walletError = reason && typeof reason === "object"
        ? reason as { code?: number; message?: string }
        : null;
      const rejected = walletError?.code === 300 || /reject|cancel/i.test(walletError?.message ?? "");
      if (walletRequestStarted && !rejected) setWalletResultUncertain(true);
      if (rejected) {
        setWalletResultUncertain(false);
        setError("The wallet request was rejected or cancelled. No delivery success was recorded; you can review the request and try again.");
      } else if (walletRequestStarted) {
        const detail = reason instanceof Error ? reason.message : "Wallet request did not return a confirmed result.";
        setError(`Wallet result is uncertain: ${detail} Refresh delivery status and check wallet activity before retrying.`);
      } else {
        setError(reason instanceof Error ? reason.message : "Wallet request did not complete.");
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
      setMessage("Reference submitted. Wait for independent on-chain verification.");
      onRefreshOrder();
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Could not submit the existing reference.");
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
      setError("Wallet connection could not be opened. Check that the Mini App is running on its configured HTTPS origin.");
    }
  }

  const attempt = delivery?.attempt ?? null;
  const canPrepare = role === "seller" && order.status === "reserved" && !attempt;
  const canRequestTransfer = role === "seller" &&
    ["awaiting_transfer", "observing_transfer"].includes(order.status) &&
    attempt !== null &&
    (attempt.status === "prepared" ||
      (attempt.status === "observing" && !attempt.candidate_transaction_hash && !attempt.submitted_at));
  const showDetails = Boolean(attempt);

  return (
    <section className="workspace-section delivery-workspace" aria-labelledby="delivery-workspace-title">
      <div className="workspace-section-heading">
        <div><p className="eyebrow">NON-CUSTODIAL DELIVERY</p><h2 id="delivery-workspace-title">NFT transfer</h2></div>
        <span className={`order-status order-status-${order.status}`}>{deliveryStatus(attempt, order.status)}</span>
      </div>
      <p className="order-guidance">
        The seller signs the TEP-62 transfer in their own wallet. The submitted reference is untrusted;
        only the backend observer can confirm delivery from finalized on-chain evidence.
      </p>
      {loading && <p className="workspace-muted" role="status">Loading delivery details…</p>}
      {error && <p className="orders-error" role="alert">{error}</p>}
      {message && <p className="workspace-muted" role="status">{message}</p>}
      {showDetails && attempt && (
        <dl className="delivery-snapshot">
          <div><dt>Network</dt><dd>TON {attempt.network}</dd></div>
          <div><dt>NFT item</dt><dd><code>{attempt.item_address}</code></dd></div>
          <div><dt>Seller source</dt><dd><code>{attempt.seller_address}</code></dd></div>
          <div><dt>Buyer destination</dt><dd><code>{attempt.buyer_address}</code></dd></div>
          <div><dt>Transfer query ID</dt><dd><code>{attempt.query_id}</code></dd></div>
          <div><dt>Preparation deadline</dt><dd>{new Date(attempt.deadline).toLocaleString()}</dd></div>
          {attempt.transaction_hash && <div><dt>Verified transaction</dt><dd><code>{attempt.transaction_hash}</code></dd></div>}
          {attempt.masterchain_seqno !== null && <div><dt>Masterchain sequence</dt><dd>{attempt.masterchain_seqno}</dd></div>}
          {attempt.verified_at && <div><dt>Verified at</dt><dd>{new Date(attempt.verified_at).toLocaleString()}</dd></div>}
        </dl>
      )}
      {role === "seller" && !wallet && order.status !== "completed" && (
        <button className="secondary-button" type="button" onClick={() => void openWallet()}>Connect seller wallet</button>
      )}
      {canPrepare && (
        <button className="primary-button" type="button" disabled={busy || loading} onClick={() => void prepare()}>
          {busy ? "Preparing…" : "Prepare transfer"}
        </button>
      )}
      {canRequestTransfer && (
        <button className="primary-button" type="button" disabled={busy || loading || walletResultUncertain || Boolean(retryReference)} onClick={() => void requestWalletTransfer()}>
          {busy ? "Waiting for wallet…" : "Review and sign in wallet"}
        </button>
      )}
      {retryReference && (
        <button className="secondary-button" type="button" disabled={busy} onClick={() => void retrySubmission()}>
          {busy ? "Submitting…" : "Retry submitting same reference"}
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
      <p className="payment-disclaimer">No payment or escrow is involved. Your wallet may ask for network fees; the marketplace never receives or signs the NFT transfer.</p>
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
    (testBoundary && typeof window !== "undefined"
      ? `${window.location.origin}/tonconnect-manifest.json`
      : "");
  if (!manifestUrl) {
    return <section className="workspace-section" aria-label="NFT transfer"><p className="eyebrow">NON-CUSTODIAL DELIVERY</p><h2>NFT transfer</h2><p className="workspace-muted">TON Connect is not configured for this Mini App. No wallet transfer can be initiated here.</p></section>;
  }

  return (
    <TonConnectUIProvider manifestUrl={manifestUrl}>
      <DeliveryPanel order={order} role={role} accessToken={accessToken} onRefreshOrder={onRefreshOrder} />
    </TonConnectUIProvider>
  );
}
