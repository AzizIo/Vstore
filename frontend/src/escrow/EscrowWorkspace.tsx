import "./escrow.css";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import {
  CHAIN,
  TonConnectUIProvider,
  useTonConnectUI,
  useTonWallet,
} from "@tonconnect/ui-react";
import { Address } from "@ton/core";

import {
  type EscrowApiClient,
  type EscrowDeal,
  type EscrowListing,
  type EscrowState,
  type EscrowWithdrawal,
  type PreparedEscrowTransaction,
} from "../api/escrow";
import type { InventoryAsset } from "../api/assets";
import type { WalletRecord } from "../wallet/api";
import {
  createTonConnectEscrowAdapter,
  walletBocReference,
  type EscrowWalletAdapter,
  type EscrowTonConnectRequest,
} from "./TonConnectEscrowAdapter";
import { fetchEscrowTestnetInventory, type EscrowOwnedNft } from "./inventory";
import {
  ESCROW_DISPUTE_LABELS,
  ESCROW_STATE_META,
  ESCROW_WITHDRAWAL_LABELS,
  formatEscrowDate,
  formatTonAmount,
  isPositiveTonAmount,
} from "./escrowState";

type EscrowWorkspaceRole = "buyer" | "seller";

interface Props {
  accessToken: string;
  currentUserId: string;
  api?: EscrowApiClient;
  manifestUrl?: string;
  /**
   * Additional explicit opt-in. Wallet signing still remains disabled unless
   * VITE_ESCROW_TESTNET_SIGNING_ENABLED=true is separately configured.
   */
  allowTestnetSigning?: boolean;
}

interface PendingWalletAction {
  transaction: PreparedEscrowTransaction;
  expectedWalletAddress: string;
}

interface WalletInventory {
  wallets: WalletRecord[];
  nfts: EscrowOwnedNft[];
}

function imageUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function titleForNft(nft: InventoryAsset | EscrowListing["nft"] | EscrowDeal["nft"]) {
  return ("name" in nft ? nft.name : nft.title) ?? "TON NFT";
}

function addressesMatch(left: string, right: string): boolean {
  try {
    return Address.parse(left).toRawString() === Address.parse(right).toRawString();
  } catch {
    return false;
  }
}

function formatAddress(value: string | null | undefined): string {
  if (!value) return "Backend ещё не вернул адрес";
  if (value.length <= 24) return value;
  return `${value.slice(0, 10)}…${value.slice(-8)}`;
}

export function EscrowStateBadge({ state }: { state: EscrowState }) {
  const meta = ESCROW_STATE_META[state];
  return (
    <span className={`escrow-state-badge escrow-state-${meta.tone}`} data-state={state}>
      {meta.label}
    </span>
  );
}

function NftArtwork({ src, title }: { src: string | null; title: string }) {
  const [failed, setFailed] = useState(false);
  const safeSrc = imageUrl(src);
  useEffect(() => setFailed(false), [safeSrc]);

  return (
    <div className="escrow-nft-artwork">
      {safeSrc && !failed
        ? <img src={safeSrc} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
        : <span aria-label={`Изображение ${title} недоступно`} role="img">V</span>}
    </div>
  );
}

function StateGuidance({ state }: { state: EscrowState }) {
  return <p className="escrow-state-guidance">{ESCROW_STATE_META[state].guidance}</p>;
}

function TransactionReview({
  pending,
  signingEnabled,
  busy,
  uncertain,
  onSign,
  onClose,
}: {
  pending: PendingWalletAction;
  signingEnabled: boolean;
  busy: boolean;
  uncertain: boolean;
  onSign: () => void;
  onClose: () => void;
}) {
  const transaction = pending.transaction;
  return (
    <section className="escrow-transaction-review" role="dialog" aria-modal="true" aria-labelledby="escrow-transaction-title">
      <div className="escrow-transaction-heading">
        <div>
          <p className="eyebrow">ПРОВЕРЬТЕ ПЕРЕД ПОДПИСАНИЕМ</p>
          <h2 id="escrow-transaction-title">Параметры TON-транзакции</h2>
        </div>
        <button type="button" className="escrow-icon-button" onClick={onClose} aria-label="Закрыть">×</button>
      </div>
      <p className="escrow-transaction-summary">{transaction.display_summary}</p>
      <dl className="escrow-facts">
        <div><dt>Сеть</dt><dd>TON testnet</dd></div>
        <div><dt>Адрес escrow</dt><dd><code>{transaction.contract_address}</code></dd></div>
        <div><dt>NFT item</dt><dd><code>{transaction.nft_item_address ?? "Не относится к этой операции"}</code></dd></div>
        <div><dt>Сумма TON</dt><dd>{formatTonAmount(transaction.amount_ton)} TON</dd></div>
        <div><dt>Комиссия платформы</dt><dd>{formatTonAmount(transaction.fee_ton)} TON</dd></div>
        <div><dt>Сетевой резерв</dt><dd>{formatTonAmount(transaction.network_fee_ton)} TON</dd></div>
        <div><dt>Подписывающий кошелёк</dt><dd><code>{pending.expectedWalletAddress}</code></dd></div>
        <div><dt>Срок запроса</dt><dd>{formatEscrowDate(transaction.valid_until)}</dd></div>
      </dl>
      <p className="escrow-warning" role="note">
        Blockchain-транзакции могут быть необратимыми. Проверьте сеть, адрес escrow, NFT item, сумму и комиссию. VILTARA никогда не попросит seed phrase или private key.
      </p>
      {!signingEnabled && (
        <p className="escrow-integration-lock" role="status">
          Подписание отключено: ABI, Backend API и testnet-приёмка ещё не утверждены. Сейчас можно только проверить параметры, полученные от Backend.
        </p>
      )}
      {uncertain && (
        <p className="escrow-warning" role="alert">
          Предыдущий запрос кошелька мог быть отправлен. Не создавайте новую транзакцию. Сначала обновите состояние сделки.
        </p>
      )}
      <div className="escrow-actions-row">
        <button className="escrow-button escrow-button-secondary" type="button" onClick={onClose} disabled={busy}>Назад</button>
        <button className="escrow-button escrow-button-primary" type="button" onClick={onSign} disabled={!signingEnabled || busy || uncertain}>
          {busy ? "Ожидаем кошелёк…" : "Подписать в TON Connect"}
        </button>
      </div>
    </section>
  );
}

function ListingCard({
  listing,
  selected,
  onSelect,
}: {
  listing: EscrowListing;
  selected: boolean;
  onSelect: () => void;
}) {
  const title = titleForNft(listing.nft);
  return (
    <button
      type="button"
      className={`escrow-listing-card${selected ? " is-selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`Выбрать escrow-лот ${title}`}
    >
      <NftArtwork src={listing.nft.image_url} title={title} />
      <span className="escrow-listing-copy">
        <span className="escrow-listing-title">{title}</span>
        <EscrowStateBadge state={listing.state} />
        <strong>{formatTonAmount(listing.price_ton)} TON</strong>
        <span className="escrow-muted">{formatAddress(listing.nft.item_address)}</span>
      </span>
    </button>
  );
}

function DealCard({
  deal,
  role,
  selected,
  onSelect,
}: {
  deal: EscrowDeal;
  role: EscrowWorkspaceRole;
  selected: boolean;
  onSelect: () => void;
}) {
  const title = titleForNft(deal.nft);
  return (
    <button
      type="button"
      className={`escrow-deal-card${selected ? " is-selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`Открыть сделку ${title}, ${ESCROW_STATE_META[deal.state].label}`}
    >
      <span className="escrow-deal-card-topline">
        <span>{role === "buyer" ? "ПОКУПКА" : "ПРОДАЖА"}</span>
        <EscrowStateBadge state={deal.state} />
      </span>
      <strong>{title}</strong>
      <span>{formatTonAmount(deal.price_ton)} TON</span>
      <span className="escrow-muted">Сделка · {deal.id.slice(0, 8)}</span>
    </button>
  );
}

function WithdrawalList({ withdrawals }: { withdrawals: EscrowWithdrawal[] }) {
  if (!withdrawals.length) {
    return <p className="escrow-empty-inline">Записей о выводе пока нет.</p>;
  }
  return (
    <div className="escrow-withdrawal-list">
      {withdrawals.map((withdrawal) => (
        <article className="escrow-withdrawal-row" key={withdrawal.id}>
          <div>
            <strong>{withdrawal.kind === "seller_proceeds" ? "Выплата продавцу" : "Вывод непроданного NFT"}</strong>
            <span>{ESCROW_WITHDRAWAL_LABELS[withdrawal.status]} · {formatEscrowDate(withdrawal.updated_at)}</span>
            {withdrawal.transaction_hash && <code>{withdrawal.transaction_hash}</code>}
          </div>
          {withdrawal.amount_ton && <strong>{formatTonAmount(withdrawal.amount_ton)} TON</strong>}
        </article>
      ))}
    </div>
  );
}

function WorkspaceBody({
  accessToken,
  currentUserId,
  api,
  allowTestnetSigning,
  walletAdapter,
  walletConnected,
  onConnectWallet,
  manifestConfigured,
}: Props & {
  walletAdapter: EscrowWalletAdapter | null;
  walletConnected: boolean;
  onConnectWallet: (() => Promise<void>) | null;
  manifestConfigured: boolean;
}) {
  const [role, setRole] = useState<EscrowWorkspaceRole>("buyer");
  const [listings, setListings] = useState<EscrowListing[]>([]);
  const [sellerListings, setSellerListings] = useState<EscrowListing[]>([]);
  const [buyerDeals, setBuyerDeals] = useState<EscrowDeal[]>([]);
  const [sellerDeals, setSellerDeals] = useState<EscrowDeal[]>([]);
  const [withdrawals, setWithdrawals] = useState<EscrowWithdrawal[]>([]);
  const [inventory, setInventory] = useState<WalletInventory>({ wallets: [], nfts: [] });
  const [selectedListingId, setSelectedListingId] = useState("");
  const [selectedDealId, setSelectedDealId] = useState("");
  const [selectedNftId, setSelectedNftId] = useState("");
  const [selectedBuyerWalletId, setSelectedBuyerWalletId] = useState("");
  const [disputeReason, setDisputeReason] = useState("");
  const [loading, setLoading] = useState(true);
  const [inventoryLoading, setInventoryLoading] = useState(true);
  const [apiError, setApiError] = useState("");
  const [inventoryError, setInventoryError] = useState("");
  const [retry, setRetry] = useState(0);
  const [busy, setBusy] = useState(false);
  const [actionError, setActionError] = useState("");
  const [actionMessage, setActionMessage] = useState("");
  const [pending, setPending] = useState<PendingWalletAction | null>(null);
  const [walletResultUncertain, setWalletResultUncertain] = useState(false);
  const [retryReference, setRetryReference] = useState("");
  const actionLock = useRef(false);

  const refresh = useCallback(() => setRetry((value) => value + 1), []);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setApiError("");
    if (!api) {
      setListings([]);
      setSellerListings([]);
      setBuyerDeals([]);
      setSellerDeals([]);
      setWithdrawals([]);
      setApiError("Escrow Backend API пока не подключён. Существующие Order и Delivery API не используются для имитации escrow.");
      setLoading(false);
    } else {
      void Promise.all([
        api.listMarketplaceListings(controller.signal),
        api.listSellerListings(controller.signal),
        api.listBuyerDeals(controller.signal),
        api.listSellerDeals(controller.signal),
        api.listSellerWithdrawals(controller.signal),
      ])
        .then(([marketplacePage, sellerPage, buyerPage, sellerDealPage, withdrawalPage]) => {
          if (controller.signal.aborted) return;
          setListings(marketplacePage.items);
          setSellerListings(sellerPage.items);
          setBuyerDeals(buyerPage.items);
          setSellerDeals(sellerDealPage.items);
          setWithdrawals(withdrawalPage.items);
          setSelectedListingId((current) => current || marketplacePage.items[0]?.id || "");
          setSelectedDealId((current) => current || buyerPage.items[0]?.id || "");
        })
        .catch((reason: unknown) => {
          if (!controller.signal.aborted) {
            setApiError(reason instanceof Error ? reason.message : "Не удалось загрузить данные TON Escrow.");
          }
        })
        .finally(() => {
          if (!controller.signal.aborted) setLoading(false);
        });
    }

    setInventoryLoading(true);
    setInventoryError("");
    void fetchEscrowTestnetInventory(accessToken, controller.signal)
      .then((result) => {
        if (controller.signal.aborted) return;
        setInventory(result);
        setSelectedNftId((current) => current || result.nfts[0]?.asset.id || "");
        setSelectedBuyerWalletId((current) => current || result.wallets.find((wallet) => wallet.is_primary)?.id || result.wallets[0]?.id || "");
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setInventoryError(reason instanceof Error ? reason.message : "Не удалось загрузить подтверждённый testnet-инвентарь.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setInventoryLoading(false);
      });

    return () => controller.abort();
  }, [accessToken, api, retry]);

  const sellerInventory = useMemo(
    () => inventory.nfts.filter((entry) => entry.asset.eligible_for_listing),
    [inventory.nfts],
  );
  const marketplaceListings = useMemo(
    () => listings.filter((listing) => listing.state === "listed" && listing.seller_id !== currentUserId),
    [listings, currentUserId],
  );
  const ownedSellerListings = useMemo(
    () => sellerListings.filter((listing) => listing.seller_id === currentUserId),
    [sellerListings, currentUserId],
  );
  const ownedBuyerDeals = useMemo(
    () => buyerDeals.filter((deal) => deal.buyer_id === currentUserId),
    [buyerDeals, currentUserId],
  );
  const selectedNft = sellerInventory.find((entry) => entry.asset.id === selectedNftId) ?? null;
  const selectedBuyerWallet = inventory.wallets.find((wallet) => wallet.id === selectedBuyerWalletId) ?? null;
  const selectedListing = marketplaceListings.find((listing) => listing.id === selectedListingId) ?? null;
  const ownedSellerDeals = useMemo(
    () => sellerDeals.filter((deal) => deal.seller_id === currentUserId),
    [sellerDeals, currentUserId],
  );
  const selectedDeal = (role === "buyer" ? ownedBuyerDeals : ownedSellerDeals)
    .find((deal) => deal.id === selectedDealId) ?? null;

  const signingEnabled = Boolean(
    allowTestnetSigning === true &&
    import.meta.env.VITE_ESCROW_TESTNET_SIGNING_ENABLED === "true" &&
    walletAdapter?.signingEnabled,
  );

  function expectedWalletForAddress(address: string): WalletRecord | null {
    return inventory.wallets.find((wallet) =>
      wallet.is_verified &&
      wallet.network === "testnet" &&
      addressesMatch(wallet.address, address),
    ) ?? null;
  }

  async function prepareAction(
    prepare: () => Promise<PreparedEscrowTransaction>,
    expectedWallet: WalletRecord | null,
  ) {
    if (actionLock.current || busy) return;
    if (!api) {
      setActionError("Escrow API не согласован и не подключён.");
      return;
    }
    if (!expectedWallet || !expectedWallet.is_verified || expectedWallet.network !== "testnet") {
      setActionError("Для операции нужен сохранённый и подтверждённый Backend testnet-кошелёк.");
      return;
    }
    actionLock.current = true;
    setBusy(true);
    setActionError("");
    setActionMessage("");
    setWalletResultUncertain(false);
    setRetryReference("");
    try {
      const transaction = await prepare();
      if (transaction.network !== "testnet") {
        throw new Error("Backend вернул неподдерживаемую сеть. Подписание заблокировано.");
      }
      setPending({
        transaction,
        expectedWalletAddress: expectedWallet.address,
      });
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Не удалось подготовить escrow-транзакцию.");
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  async function signPreparedTransaction() {
    if (!pending || actionLock.current || busy || walletResultUncertain) return;
    if (!api || !walletAdapter || !signingEnabled) {
      setActionError("Подписание отключено до утверждения testnet ABI и Backend API.");
      return;
    }
    if (
      !walletAdapter.connectedWallet ||
      walletAdapter.connectedWallet.chain !== CHAIN.TESTNET
    ) {
      setActionError("Подключите кошелёк в TON testnet.");
      return;
    }

    actionLock.current = true;
    setBusy(true);
    setActionError("");
    let walletRequestStarted = false;
    try {
      walletRequestStarted = true;
      const result = await walletAdapter.sendPreparedTransaction(
        pending.transaction,
        pending.expectedWalletAddress,
      );
      const reference = await walletBocReference(result.boc);
      try {
        await api.submitWalletReference({
          target_id: pending.transaction.id,
          action: pending.transaction.action,
          reference,
        });
        setPending(null);
        setActionMessage("Кошелёк вернул подписанное сообщение. Backend observer должен отдельно подтвердить on-chain состояние; это ещё не успех сделки.");
        setRetry((value) => value + 1);
      } catch (reason) {
        setRetryReference(reference);
        setWalletResultUncertain(true);
        setActionError(reason instanceof Error ? reason.message : "Не удалось передать ссылку на проверку.");
        setActionMessage("Транзакция могла попасть в сеть. Не подписывайте новую: можно повторно отправить только эту же ссылку.");
      }
    } catch (reason) {
      const walletError = reason && typeof reason === "object"
        ? reason as { code?: number; message?: string }
        : null;
      const rejected = walletError?.code === 300 || /reject|cancel/i.test(walletError?.message ?? "");
      if (walletRequestStarted && !rejected) setWalletResultUncertain(true);
      setActionError(rejected
        ? "Запрос кошелька отклонён. Backend не получил подтверждение операции."
        : reason instanceof Error ? reason.message : "Результат запроса кошелька неизвестен.");
      if (walletRequestStarted && !rejected) {
        setActionMessage("Не отправляйте повторную транзакцию, пока не обновите статус escrow через Backend.");
      }
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  async function retryReferenceSubmission() {
    if (!api || !pending || !retryReference || actionLock.current || busy) return;
    actionLock.current = true;
    setBusy(true);
    setActionError("");
    try {
      await api.submitWalletReference({
        target_id: pending.transaction.id,
        action: pending.transaction.action,
        reference: retryReference,
      });
      setRetryReference("");
      setPending(null);
      setWalletResultUncertain(false);
      setActionMessage("Ссылка передана observer. Дождитесь подтверждения состояния от Backend.");
      setRetry((value) => value + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Не удалось повторно отправить ту же ссылку.");
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  function sellerWalletForListing(listing: EscrowListing): WalletRecord | null {
    return expectedWalletForAddress(listing.seller_wallet_address);
  }

  function sellerWalletForDeal(deal: EscrowDeal): WalletRecord | null {
    return expectedWalletForAddress(deal.seller_wallet_address);
  }

  return (
    <section className="escrow-workspace" aria-labelledby="escrow-workspace-title">
      <header className="escrow-workspace-heading">
        <div>
          <p className="eyebrow">VILTARA · TON TESTNET</p>
          <h1 id="escrow-workspace-title">TON Escrow</h1>
          <p>Лот, оплата и передача NFT отслеживаются по данным контракта и Backend observer.</p>
        </div>
        <button className="escrow-refresh-button" type="button" onClick={refresh} disabled={loading || inventoryLoading}>
          Обновить
        </button>
      </header>

      <div className="escrow-testnet-notice" role="note">
        <strong>Только TON testnet.</strong> Это изолированный интерфейс подготовки. Он не подключён к production-заказам, Stars или mainnet. Успех не показывается до подтверждения Backend observer.
      </div>

      <div className="escrow-role-tabs" role="tablist" aria-label="Роль в escrow">
        <button type="button" role="tab" aria-selected={role === "buyer"} className={role === "buyer" ? "is-active" : ""} onClick={() => { setRole("buyer"); setSelectedDealId(ownedBuyerDeals[0]?.id ?? ""); }}>
          Покупатель
        </button>
        <button type="button" role="tab" aria-selected={role === "seller"} className={role === "seller" ? "is-active" : ""} onClick={() => { setRole("seller"); setSelectedDealId(sellerDeals.find((deal) => deal.seller_id === currentUserId)?.id ?? ""); }}>
          Продавец
        </button>
      </div>

      {apiError && <div className="escrow-message escrow-message-error" role="alert"><strong>Escrow API недоступен</strong><p>{apiError}</p><button type="button" onClick={refresh}>Повторить</button></div>}
      {inventoryError && <div className="escrow-message escrow-message-error" role="alert"><strong>Инвентарь недоступен</strong><p>{inventoryError}</p></div>}
      {actionError && <p className="escrow-inline-error" role="alert">{actionError}</p>}
      {actionMessage && <p className="escrow-inline-message" role="status">{actionMessage}</p>}

      {role === "seller" ? (
        <div className="escrow-panel">
          <section className="escrow-section" aria-labelledby="escrow-seller-deposit-title">
            <div className="escrow-section-heading">
              <div><p className="eyebrow">ПЕРЕДАЧА В ESCROW</p><h2 id="escrow-seller-deposit-title">Внести NFT</h2></div>
              <span>{sellerInventory.length} доступно</span>
            </div>
            <p className="escrow-muted">Выбираются только NFT из подтверждённых testnet-кошельков, полученных от Backend. Подключение кошелька само по себе не подтверждает владение.</p>
            {inventoryLoading ? (
              <p className="escrow-empty-inline" role="status" aria-busy="true">Проверяем testnet-инвентарь…</p>
            ) : sellerInventory.length ? (
              <div className="escrow-nft-picker">
                {sellerInventory.map((entry) => {
                  const title = titleForNft(entry.asset);
                  const selected = entry.asset.id === selectedNftId;
                  return (
                    <button key={entry.asset.id} type="button" className={`escrow-nft-choice${selected ? " is-selected" : ""}`} aria-pressed={selected} onClick={() => setSelectedNftId(entry.asset.id)}>
                      <NftArtwork src={entry.asset.image_url} title={title} />
                      <span><strong>{title}</strong><small>{formatAddress(entry.asset.item_address)}</small><small>Подтверждённый кошелёк · {formatAddress(entry.wallet.address)}</small></span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="escrow-empty-state"><h3>Нет подходящих NFT</h3><p>Подтвердите testnet-кошелёк и убедитесь, что NFT доступен для депозита.</p></div>
            )}
            {selectedNft && (
              <div className="escrow-deposit-preview">
                <h3>Условия депозита</h3>
                <dl className="escrow-facts">
                  <div><dt>Сеть</dt><dd>TON testnet</dd></div>
                  <div><dt>NFT item address</dt><dd><code>{selectedNft.asset.item_address}</code></dd></div>
                  <div><dt>Кошелёк продавца</dt><dd><code>{selectedNft.wallet.address}</code></dd></div>
                  <div><dt>Адрес escrow</dt><dd>Будет показан из подготовленной Backend-транзакции</dd></div>
                  <div><dt>Комиссия</dt><dd>Будет показана из подготовленной Backend-транзакции</dd></div>
                </dl>
                <button
                  className="escrow-button escrow-button-primary"
                  type="button"
                  disabled={!api || busy || loading || !selectedNft}
                  onClick={() => void prepareAction(
                    () => api!.prepareNftDeposit({ asset_id: selectedNft.asset.id, seller_wallet_id: selectedNft.wallet.id }),
                    selectedNft.wallet,
                  )}
                >
                  {busy ? "Подготавливаем…" : "Проверить условия депозита"}
                </button>
              </div>
            )}
          </section>

          <section className="escrow-section" aria-labelledby="escrow-seller-listings-title">
            <div className="escrow-section-heading"><div><p className="eyebrow">МОИ ЛОТЫ</p><h2 id="escrow-seller-listings-title">Активные и завершённые</h2></div></div>
            {loading ? <p className="escrow-empty-inline" role="status">Загружаем лоты…</p> : ownedSellerListings.length ? (
              <div className="escrow-list">
                {ownedSellerListings.map((listing) => (
                  <article key={listing.id} className="escrow-row-card">
                    <div className="escrow-row-main">
                      <NftArtwork src={listing.nft.image_url} title={titleForNft(listing.nft)} />
                      <div><strong>{titleForNft(listing.nft)}</strong><EscrowStateBadge state={listing.state} /><StateGuidance state={listing.state} /></div>
                    </div>
                    <dl className="escrow-compact-facts">
                      <div><dt>Цена</dt><dd>{formatTonAmount(listing.price_ton)} TON</dd></div>
                      <div><dt>Escrow</dt><dd><code>{formatAddress(listing.contract_address)}</code></dd></div>
                      <div><dt>NFT item</dt><dd><code>{formatAddress(listing.nft.item_address)}</code></dd></div>
                    </dl>
                    {listing.state === "listed" && (
                      <button
                        className="escrow-button escrow-button-secondary"
                        type="button"
                        disabled={!api || busy}
                        onClick={() => void prepareAction(
                          () => api!.prepareUnsoldNftWithdrawal({
                            listing_id: listing.id,
                            seller_wallet_id: sellerWalletForListing(listing)?.id ?? "",
                          }),
                          sellerWalletForListing(listing),
                        )}
                      >
                        Вывести непроданный NFT
                      </button>
                    )}
                  </article>
                ))}
              </div>
            ) : <p className="escrow-empty-inline">Escrow-лотов пока нет.</p>}
          </section>

          <section className="escrow-section" aria-labelledby="escrow-seller-deals-title">
            <div className="escrow-section-heading"><div><p className="eyebrow">РАСЧЁТЫ</p><h2 id="escrow-seller-deals-title">Выплаты по сделкам</h2></div></div>
            {buyerDeals.filter((deal) => deal.seller_id === currentUserId).length ? (
              <div className="escrow-list">
                {buyerDeals.filter((deal) => deal.seller_id === currentUserId).map((deal) => {
                  const claimable = isPositiveTonAmount(deal.seller_claimable_ton);
                  const signer = sellerWalletForDeal(deal);
                  return (
                    <article className="escrow-row-card" key={deal.id}>
                      <div className="escrow-row-main"><NftArtwork src={deal.nft.image_url} title={titleForNft(deal.nft)} /><div><strong>{titleForNft(deal.nft)}</strong><EscrowStateBadge state={deal.state} /><StateGuidance state={deal.state} /></div></div>
                      <div className="escrow-payout-line"><span>Доступно по данным Backend</span><strong>{formatTonAmount(deal.seller_claimable_ton)} TON</strong></div>
                      {claimable && (
                        <button
                          className="escrow-button escrow-button-primary"
                          type="button"
                          disabled={!api || busy || !signer}
                          onClick={() => signer && void prepareAction(
                            () => api!.prepareSellerProceedsWithdrawal({ deal_id: deal.id, seller_wallet_id: signer.id }),
                            signer,
                          )}
                        >
                          Получить выплату / Claim
                        </button>
                      )}
                    </article>
                  );
                })}
              </div>
            ) : <p className="escrow-empty-inline">Завершённых продаж с доступной выплатой пока нет.</p>}
            <h3 className="escrow-subheading">История вывода</h3>
            <WithdrawalList withdrawals={withdrawals} />
          </section>
        </div>
      ) : (
        <div className="escrow-panel">
          <section className="escrow-section" aria-labelledby="escrow-buyer-market-title">
            <div className="escrow-section-heading"><div><p className="eyebrow">КАТАЛОГ ESCROW</p><h2 id="escrow-buyer-market-title">Лоты, доступные за TON</h2></div><span>{marketplaceListings.length} лотов</span></div>
            <label className="escrow-wallet-select">
              <span>Подтверждённый кошелёк покупателя · TON testnet</span>
              <select value={selectedBuyerWalletId} onChange={(event) => setSelectedBuyerWalletId(event.target.value)} disabled={!inventory.wallets.length}>
                {inventory.wallets.map((wallet) => <option value={wallet.id} key={wallet.id}>{formatAddress(wallet.address)}{wallet.is_primary ? " · основной" : ""}</option>)}
              </select>
            </label>
            {loading ? <p className="escrow-empty-inline" role="status">Загружаем escrow-лоты…</p> : marketplaceListings.length ? (
              <div className="escrow-market-grid">
                {marketplaceListings.map((listing) => <ListingCard key={listing.id} listing={listing} selected={selectedListingId === listing.id} onSelect={() => setSelectedListingId(listing.id)} />)}
              </div>
            ) : <div className="escrow-empty-state"><h3>Доступных лотов пока нет</h3><p>Лот появится после подтверждённого депозита NFT продавцом.</p></div>}
            {selectedListing && (
              <article className="escrow-selected-listing">
                <div className="escrow-row-main"><NftArtwork src={selectedListing.nft.image_url} title={titleForNft(selectedListing.nft)} /><div><p className="eyebrow">ПАРАМЕТРЫ СДЕЛКИ</p><h3>{titleForNft(selectedListing.nft)}</h3><EscrowStateBadge state={selectedListing.state} /></div></div>
                <dl className="escrow-facts">
                  <div><dt>Сеть</dt><dd>TON testnet</dd></div>
                  <div><dt>Адрес escrow</dt><dd><code>{selectedListing.contract_address ?? "Не опубликован Backend"}</code></dd></div>
                  <div><dt>NFT item address</dt><dd><code>{selectedListing.nft.item_address}</code></dd></div>
                  <div><dt>Цена</dt><dd>{formatTonAmount(selectedListing.price_ton)} TON</dd></div>
                  <div><dt>Комиссия платформы</dt><dd>{formatTonAmount(selectedListing.platform_fee_ton)} TON</dd></div>
                  <div><dt>Продавец</dt><dd><code>{formatAddress(selectedListing.seller_wallet_address)}</code></dd></div>
                </dl>
                <p className="escrow-warning">Покупка и передача NFT выполняются on-chain. Проверьте сеть, NFT item, адрес контракта и полную сумму до подписи. Необратимые операции нельзя отменить одной кнопкой в приложении.</p>
                <button
                  className="escrow-button escrow-button-primary"
                  type="button"
                  disabled={!api || busy || !selectedBuyerWallet || selectedListing.seller_id === currentUserId}
                  onClick={() => selectedBuyerWallet && void prepareAction(
                    () => api!.preparePurchase({ listing_id: selectedListing.id, buyer_wallet_id: selectedBuyerWallet.id }),
                    selectedBuyerWallet,
                  )}
                >
                  Купить за TON
                </button>
              </article>
            )}
          </section>

          <section className="escrow-section" aria-labelledby="escrow-buyer-deals-title">
            <div className="escrow-section-heading"><div><p className="eyebrow">МОИ СДЕЛКИ</p><h2 id="escrow-buyer-deals-title">Оплата, доставка и споры</h2></div></div>
            {loading ? <p className="escrow-empty-inline" role="status">Загружаем сделки…</p> : ownedBuyerDeals.length ? (
              <div className="escrow-deals-grid">
                {ownedBuyerDeals.map((deal) => <DealCard key={deal.id} deal={deal} role="buyer" selected={selectedDealId === deal.id} onSelect={() => setSelectedDealId(deal.id)} />)}
              </div>
            ) : <p className="escrow-empty-inline">Покупок через escrow пока нет.</p>}
            {selectedDeal && selectedDeal.buyer_id === currentUserId && (
              <article className="escrow-selected-deal">
                <div className="escrow-section-heading"><div><p className="eyebrow">СДЕЛКА {selectedDeal.id.slice(0, 8)}</p><h3>{titleForNft(selectedDeal.nft)}</h3></div><EscrowStateBadge state={selectedDeal.state} /></div>
                <StateGuidance state={selectedDeal.state} />
                <dl className="escrow-facts">
                  <div><dt>Адрес escrow</dt><dd><code>{selectedDeal.contract_address}</code></dd></div>
                  <div><dt>NFT item</dt><dd><code>{selectedDeal.nft.item_address}</code></dd></div>
                  <div><dt>Цена</dt><dd>{formatTonAmount(selectedDeal.price_ton)} TON</dd></div>
                  <div><dt>Комиссия</dt><dd>{formatTonAmount(selectedDeal.platform_fee_ton)} TON</dd></div>
                  <div><dt>Окно подтверждения</dt><dd>{formatEscrowDate(selectedDeal.buyer_confirmation_deadline)}</dd></div>
                  <div><dt>Окончание окна спора</dt><dd>{formatEscrowDate(selectedDeal.dispute_deadline)}</dd></div>
                </dl>
                {selectedDeal.dispute && (
                  <div className="escrow-dispute-card" role="status">
                    <strong>Спор · {ESCROW_DISPUTE_LABELS[selectedDeal.dispute.status]}</strong>
                    <p>{selectedDeal.dispute.summary || selectedDeal.dispute.reason_code}</p>
                    <span>Открыт: {formatEscrowDate(selectedDeal.dispute.opened_at)}</span>
                    {selectedDeal.dispute.resolution_note && <p>Решение: {selectedDeal.dispute.resolution_note}</p>}
                  </div>
                )}
                {selectedDeal.state === "buyer_confirmation_window" && (
                  <div className="escrow-buyer-actions">
                    <button
                      className="escrow-button escrow-button-primary"
                      type="button"
                      disabled={!api || busy || !selectedBuyerWallet}
                      onClick={() => selectedBuyerWallet && void prepareAction(
                        () => api!.prepareBuyerConfirmation({ deal_id: selectedDeal.id }),
                        expectedWalletForAddress(selectedDeal.buyer_wallet_address),
                      )}
                    >Подтвердить получение</button>
                    <label className="escrow-dispute-reason"><span>Причина спора</span><textarea rows={3} value={disputeReason} onChange={(event) => setDisputeReason(event.target.value)} placeholder="Опишите проблему с оплатой или передачей NFT." /></label>
                    <button
                      className="escrow-button escrow-button-danger"
                      type="button"
                      disabled={!api || busy || disputeReason.trim().length < 8}
                      onClick={() => void prepareAction(
                        () => api!.prepareDispute({ deal_id: selectedDeal.id, reason: disputeReason.trim() }),
                        expectedWalletForAddress(selectedDeal.buyer_wallet_address),
                      )}
                    >Открыть спор</button>
                  </div>
                )}
                {selectedDeal.state === "refund_pending_nft_return" && (
                  <div className="escrow-return-nft">
                    <p className="escrow-warning">Для buyer-favourable refund после доставки NFT необходимо сначала вернуть предмет в escrow. Нельзя запросить возврат денег, пока NFT остаётся у покупателя.</p>
                    <button
                      className="escrow-button escrow-button-primary"
                      type="button"
                      disabled={!api || busy || !expectedWalletForAddress(selectedDeal.buyer_wallet_address)}
                      onClick={() => void prepareAction(
                        () => api!.prepareBuyerNftReturn({
                          deal_id: selectedDeal.id,
                          buyer_wallet_id: expectedWalletForAddress(selectedDeal.buyer_wallet_address)!.id,
                        }),
                        expectedWalletForAddress(selectedDeal.buyer_wallet_address),
                      )}
                    >Вернуть NFT в escrow</button>
                  </div>
                )}
                {selectedDeal.state === "refundable_failure" && (
                  <p className="escrow-warning">Обнаружена ошибка, допускающая возврат. Следите за состоянием возврата; не отправляйте повторную оплату.</p>
                )}
              </article>
            )}
          </section>
        </div>
      )}

      {!walletConnected && manifestConfigured && (
        <button className="escrow-button escrow-button-secondary escrow-connect-button" type="button" onClick={() => onConnectWallet?.()}>
          Подключить testnet-кошелёк
        </button>
      )}
      {walletConnected && walletAdapter?.connectedWallet?.chain !== CHAIN.TESTNET && (
        <p className="escrow-inline-error" role="alert">Подключён не TON testnet. Все escrow-действия заблокированы.</p>
      )}
      {walletConnected && walletAdapter?.connectedWallet?.chain === CHAIN.TESTNET && (
        <p className="escrow-inline-message" role="status">Кошелёк подключён. Владение NFT и право подписи проверяются отдельно по Backend-записи подтверждённого кошелька.</p>
      )}
      {!signingEnabled && <p className="escrow-integration-lock" role="status">Wallet signing выключен по умолчанию. Никакая операция не будет отправлена в сеть из этого интерфейса без отдельного testnet-only включения после согласования ABI/API.</p>}

      {pending && (
        <TransactionReview
          pending={pending}
          signingEnabled={signingEnabled}
          busy={busy}
          uncertain={walletResultUncertain}
          onSign={() => void signPreparedTransaction()}
          onClose={() => {
            if (!busy && !walletResultUncertain) setPending(null);
          }}
        />
      )}
      {retryReference && pending && (
        <button className="escrow-button escrow-button-secondary" type="button" disabled={busy} onClick={() => void retryReferenceSubmission()}>
          Отправить ту же ссылку observer повторно
        </button>
      )}
    </section>
  );
}

function ConnectedEscrowWorkspace(props: Props) {
  const wallet = useTonWallet();
  const [tonConnectUI] = useTonConnectUI();
  const walletAdapter = useMemo(() => createTonConnectEscrowAdapter({
    connectedWallet: wallet ? {
      address: wallet.account.address,
      chain: wallet.account.chain,
    } : null,
    enabled: props.allowTestnetSigning === true
      && import.meta.env.VITE_ESCROW_TESTNET_SIGNING_ENABLED === "true",
    sendTransaction: (request) => tonConnectUI.sendTransaction(
      request as Parameters<typeof tonConnectUI.sendTransaction>[0],
    ),
  }), [wallet, tonConnectUI, props.allowTestnetSigning]);

  const walletConnected = Boolean(wallet);
  return (
    <WorkspaceBody
      {...props}
      walletAdapter={walletAdapter}
      walletConnected={walletConnected}
      onConnectWallet={() => tonConnectUI.openModal()}
      manifestConfigured
    />
  );
}

/**
 * This workspace is intentionally standalone: App.tsx navigation is not changed
 * until the escrow API, ABI, ADR and product/policy gates are approved.
 */
export function EscrowWorkspace(props: Props) {
  const manifestUrl = props.manifestUrl ?? import.meta.env.VITE_TONCONNECT_MANIFEST_URL?.trim();
  if (!manifestUrl) {
    return (
      <WorkspaceBody
        {...props}
        walletAdapter={null}
        walletConnected={false}
        onConnectWallet={null}
        manifestConfigured={false}
      />
    );
  }
  return (
    <TonConnectUIProvider manifestUrl={manifestUrl}>
      <ConnectedEscrowWorkspace {...props} />
    </TonConnectUIProvider>
  );
}
