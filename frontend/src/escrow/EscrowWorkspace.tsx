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
  type EscrowAction,
  type EscrowDeal,
  type EscrowListingIntent,
  type EscrowWithdrawal,
  type PreparedEscrowTransaction,
} from "../api/escrow";
import type { InventoryAsset } from "../api/assets";
import type { WalletRecord } from "../wallet/api";
import {
  createTonConnectEscrowAdapter,
  walletBocReference,
  type EscrowWalletAdapter,
} from "./TonConnectEscrowAdapter";
import { fetchEscrowTestnetInventory, type EscrowOwnedNft } from "./inventory";
import {
  ESCROW_DEAL_STATE_META,
  ESCROW_DISPUTE_LABELS,
  ESCROW_LISTING_STATE_META,
  ESCROW_WITHDRAWAL_LABELS,
  formatEscrowDate,
  nanoToTon,
  tonToNano,
} from "./escrowState";

type WorkspaceRole = "buyer" | "seller";

interface Props {
  accessToken: string;
  currentUserId: string;
  api?: EscrowApiClient;
  manifestUrl?: string;
  allowTestnetSigning?: boolean;
  onManageListings?: () => void;
}

interface PendingWalletAction {
  transaction: PreparedEscrowTransaction;
  expectedWalletAddress: string;
}

interface WalletInventory {
  wallets: WalletRecord[];
  nfts: EscrowOwnedNft[];
}

function safeImageUrl(value: string | null): string | null {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function titleForNft(nft: InventoryAsset | EscrowListingIntent["nft"] | EscrowDeal["nft"]): string {
  return ("name" in nft ? nft.name : nft.title) ?? "TON NFT";
}

function addressesMatch(left: string, right: string): boolean {
  try {
    return Address.parse(left).toRawString() === Address.parse(right).toRawString();
  } catch {
    return false;
  }
}

function shortAddress(value: string | null | undefined): string {
  if (!value) return "Адрес ещё не подтверждён Backend observer";
  if (value.length <= 25) return value;
  return `${value.slice(0, 11)}…${value.slice(-8)}`;
}

function actionLabel(action: EscrowAction): string {
  switch (action) {
    case "create_deal_escrow": return "Создать DealEscrow";
    case "deposit_nft": return "Внести NFT в escrow";
    case "fund_deal": return "Внести TON";
    case "accept_deal": return "Принять условия и передать NFT";
    case "open_dispute": return "Открыть спор";
    case "return_nft_to_escrow": return "Вернуть NFT в escrow";
    case "withdraw_unsold_nft": return "Вернуть непроданный NFT";
  }
}

function allowed(action: EscrowAction, available: EscrowAction[]): boolean {
  return available.includes(action);
}

export function ListingIntentStateBadge({ state }: { state: EscrowListingIntent["state"] }) {
  const meta = ESCROW_LISTING_STATE_META[state];
  return <span className={`escrow-state-badge escrow-state-${meta.tone}`} data-state={state}>{meta.label}</span>;
}

export function DealStateBadge({ state }: { state: EscrowDeal["state"] }) {
  const meta = ESCROW_DEAL_STATE_META[state];
  return <span className={`escrow-state-badge escrow-state-${meta.tone}`} data-state={state}>{meta.label}</span>;
}

function NftArtwork({ src, title }: { src: string | null; title: string }) {
  const [failed, setFailed] = useState(false);
  const image = safeImageUrl(src);
  useEffect(() => setFailed(false), [image]);
  return (
    <div className="escrow-nft-artwork">
      {image && !failed
        ? <img src={image} alt="" loading="lazy" referrerPolicy="no-referrer" onError={() => setFailed(true)} />
        : <span role="img" aria-label={`Изображение ${title} недоступно`}>V</span>}
    </div>
  );
}

function ListingIntentCard({
  listing,
  selected,
  onSelect,
}: {
  listing: EscrowListingIntent;
  selected: boolean;
  onSelect: () => void;
}) {
  const title = titleForNft(listing.nft);
  const available = listing.available_actions.includes("create_deal_intent");
  return (
    <button
      type="button"
      className={`escrow-listing-card${selected ? " is-selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`Выбрать предложение ${title}, ${ESCROW_LISTING_STATE_META[listing.state].label}`}
      disabled={!available}
    >
      <NftArtwork src={listing.nft.image_url} title={title} />
      <span className="escrow-listing-copy">
        <span className="escrow-listing-title">{title}</span>
        <ListingIntentStateBadge state={listing.state} />
        <strong>{nanoToTon(listing.price_nano)} TON</strong>
        <span className="escrow-muted">{shortAddress(listing.nft.item_address)}</span>
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
  role: WorkspaceRole;
  selected: boolean;
  onSelect: () => void;
}) {
  return (
    <button
      type="button"
      className={`escrow-deal-card${selected ? " is-selected" : ""}`}
      onClick={onSelect}
      aria-pressed={selected}
      aria-label={`Открыть сделку ${titleForNft(deal.nft)}, ${ESCROW_DEAL_STATE_META[deal.state].label}`}
    >
      <span className="escrow-deal-card-topline">
        <span>{role === "buyer" ? "ПОКУПКА" : "ПРОДАЖА"}</span>
        <DealStateBadge state={deal.state} />
      </span>
      <strong>{titleForNft(deal.nft)}</strong>
      <span>{nanoToTon(deal.price_nano)} TON</span>
      <span className="escrow-muted">Deal · {deal.id.slice(0, 8)}</span>
    </button>
  );
}

function StateGuidance({ state }: { state: EscrowDeal["state"] }) {
  return <p className="escrow-state-guidance">{ESCROW_DEAL_STATE_META[state].guidance}</p>;
}

function WithdrawalList({ withdrawals }: { withdrawals: EscrowWithdrawal[] }) {
  if (!withdrawals.length) return <p className="escrow-empty-inline">Истории возврата NFT пока нет.</p>;
  return (
    <div className="escrow-withdrawal-list">
      {withdrawals.map((withdrawal) => (
        <article className="escrow-withdrawal-row" key={withdrawal.id}>
          <div>
            <strong>Возврат непроданного NFT</strong>
            <span>{ESCROW_WITHDRAWAL_LABELS[withdrawal.status]} · {formatEscrowDate(withdrawal.updated_at)}</span>
            {withdrawal.transaction_hash && <code>{withdrawal.transaction_hash}</code>}
          </div>
          <code>{shortAddress(withdrawal.destination_address)}</code>
        </article>
      ))}
    </div>
  );
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
          <p className="eyebrow">ПРОВЕРЬТЕ КАЖДОЕ СООБЩЕНИЕ</p>
          <h2 id="escrow-transaction-title">{actionLabel(transaction.action)}</h2>
        </div>
        <button type="button" className="escrow-icon-button" onClick={onClose} aria-label="Закрыть">×</button>
      </div>
      <p className="escrow-transaction-summary">{transaction.display_purpose}</p>
      <dl className="escrow-facts">
        <div><dt>Сеть</dt><dd>TON testnet</dd></div>
        <div><dt>DealEscrow</dt><dd><code>{transaction.escrow_address ?? "Адрес будет рассчитан Backend по StateInit"}</code></dd></div>
        <div><dt>NFT item address</dt><dd><code>{transaction.nft_item_address}</code></dd></div>
        {transaction.price_nano !== null && <div><dt>Цена сделки</dt><dd>{nanoToTon(transaction.price_nano)} TON</dd></div>}
        <div><dt>Комиссия платформы</dt><dd>0 TON · 0 bps · PoC</dd></div>
        <div><dt>Execution reserve</dt><dd>{transaction.execution_reserve_nano === null ? "Не указан" : `${nanoToTon(transaction.execution_reserve_nano)} TON (${transaction.execution_reserve_nano} nanotons)`}</dd></div>
        <div><dt>Подписывающий кошелёк</dt><dd><code>{pending.expectedWalletAddress}</code></dd></div>
        <div><dt>Срок действия</dt><dd>{formatEscrowDate(transaction.valid_until)}</dd></div>
      </dl>
      <section className="escrow-message-review" aria-label="Исходящие TON-сообщения">
        <h3>Все сообщения TON Connect</h3>
        {transaction.messages.map((message, index) => (
          <article className="escrow-message-review-row" key={`${transaction.action_id}-${index}`}>
            <strong>Сообщение {index + 1}</strong>
            <dl className="escrow-compact-facts">
              <div><dt>Получатель</dt><dd><code>{message.address}</code></dd></div>
              <div><dt>Сумма</dt><dd>{nanoToTon(message.amount_nano)} TON · {message.amount_nano} nanotons</dd></div>
              <div><dt>Payload</dt><dd>{message.payload_boc ? "Подготовлен Backend (BOC)" : "Нет"}</dd></div>
              <div><dt>State init</dt><dd>{message.state_init_boc ? "Подготовлен Backend (BOC)" : "Нет"}</dd></div>
            </dl>
          </article>
        ))}
      </section>
      <p className="escrow-warning" role="note">
        Blockchain-транзакции могут быть необратимыми. Сверьте testnet, все адреса и суммы. VILTARA не попросит seed phrase или private key.
      </p>
      {!signingEnabled && (
        <p className="escrow-integration-lock" role="status">
          Подписание отключено до утверждения ABI, Backend API и live testnet acceptance. Можно только проверить подготовленные параметры.
        </p>
      )}
      {uncertain && (
        <p className="escrow-warning" role="alert">
          Результат предыдущего запроса неизвестен. Не подписывайте повторно: сначала требуется сверка Backend observer.
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

function WorkspaceBody({
  accessToken,
  currentUserId,
  api,
  allowTestnetSigning,
  onManageListings,
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
  const [role, setRole] = useState<WorkspaceRole>("buyer");
  const [listings, setListings] = useState<EscrowListingIntent[]>([]);
  const [sellerListings, setSellerListings] = useState<EscrowListingIntent[]>([]);
  const [buyerDeals, setBuyerDeals] = useState<EscrowDeal[]>([]);
  const [sellerDeals, setSellerDeals] = useState<EscrowDeal[]>([]);
  const [withdrawals, setWithdrawals] = useState<EscrowWithdrawal[]>([]);
  const [inventory, setInventory] = useState<WalletInventory>({ wallets: [], nfts: [] });
  const [selectedListingId, setSelectedListingId] = useState("");
  const [selectedDealId, setSelectedDealId] = useState("");
  const [selectedNftId, setSelectedNftId] = useState("");
  const [selectedBuyerWalletId, setSelectedBuyerWalletId] = useState("");
  const [sellerPriceTon, setSellerPriceTon] = useState("");
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
    () => listings.filter((listing) =>
      listing.seller_id !== currentUserId &&
      listing.available_actions.includes("create_deal_intent"),
    ),
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
  const ownedSellerDeals = useMemo(
    () => sellerDeals.filter((deal) => deal.seller_id === currentUserId),
    [sellerDeals, currentUserId],
  );
  const selectedNft = sellerInventory.find((entry) => entry.asset.id === selectedNftId) ?? null;
  const selectedBuyerWallet = inventory.wallets.find((wallet) => wallet.id === selectedBuyerWalletId) ?? null;
  const selectedListing = marketplaceListings.find((listing) => listing.id === selectedListingId) ?? null;
  const selectedDeal = (role === "buyer" ? ownedBuyerDeals : ownedSellerDeals)
    .find((deal) => deal.id === selectedDealId) ?? null;

  const signingEnabled = Boolean(
    allowTestnetSigning === true &&
    import.meta.env.VITE_ESCROW_TESTNET_SIGNING_ENABLED === "true" &&
    walletAdapter?.signingEnabled,
  );

  function verifiedWalletForAddress(address: string): WalletRecord | null {
    return inventory.wallets.find((wallet) =>
      wallet.is_verified &&
      wallet.network === "testnet" &&
      addressesMatch(wallet.address, address),
    ) ?? null;
  }

  async function runGuarded<T>(
    operation: () => Promise<T>,
    successMessage: string,
  ): Promise<T | null> {
    if (actionLock.current || busy || walletResultUncertain) return null;
    if (!api) {
      setActionError("Escrow API не согласован и не подключён.");
      return null;
    }
    actionLock.current = true;
    setBusy(true);
    setActionError("");
    setActionMessage("");
    try {
      const result = await operation();
      setActionMessage(successMessage);
      return result;
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Операция TON Escrow не выполнена.");
      return null;
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  async function createListingIntent() {
    if (!api || !selectedNft) {
      setActionError("Выберите NFT из подтверждённого testnet-инвентаря.");
      return;
    }
    const priceNano = tonToNano(sellerPriceTon);
    if (!priceNano) {
      setActionError("Укажите положительную цену в TON не более чем с 9 знаками после запятой.");
      return;
    }
    const result = await runGuarded(
      () => api.createListingIntent({
        asset_id: selectedNft.asset.id,
        seller_wallet_id: selectedNft.wallet.id,
        price_nano: priceNano,
      }),
      "Listing intent создан. Это ещё не означает, что NFT находится в escrow или доступен для оплаты.",
    );
    if (result) {
      setSellerPriceTon("");
      setRetry((value) => value + 1);
    }
  }

  async function createBuyerDealIntent() {
    if (!api || !selectedListing || !selectedBuyerWallet) return;
    const result = await runGuarded(
      () => api.createBuyerDealIntent({
        listing_id: selectedListing.id,
        buyer_wallet_id: selectedBuyerWallet.id,
      }),
      "Deal intent создан и привязан к вашему подтверждённому testnet-кошельку. Оплату можно вносить только после подтверждённого NFT-депозита.",
    );
    if (result) {
      setSelectedDealId(result.id);
      setRole("buyer");
      setRetry((value) => value + 1);
    }
  }

  async function prepareWalletAction(
    action: EscrowAction,
    deal: EscrowDeal,
    prepare: () => Promise<PreparedEscrowTransaction>,
    expectedWallet: WalletRecord | null,
  ) {
    if (!api || !allowed(action, deal.available_actions)) {
      setActionError("Backend не разрешил это действие для текущего состояния сделки.");
      return;
    }
    if (!expectedWallet || !expectedWallet.is_verified || expectedWallet.network !== "testnet") {
      setActionError("Для операции нужен сохранённый и подтверждённый Backend testnet-кошелёк участника.");
      return;
    }
    const transaction = await runGuarded(
      prepare,
      "Backend подготовил транзакцию. Проверьте все сообщения и параметры перед подписью.",
    );
    if (transaction) {
      if (transaction.action !== action || transaction.network !== "testnet") {
        setActionError("Backend вернул неподходящее действие или сеть. Подписание заблокировано.");
        return;
      }
      setPending({ transaction, expectedWalletAddress: expectedWallet.address });
    }
  }

  async function signPreparedTransaction() {
    if (!pending || actionLock.current || busy || walletResultUncertain) return;
    if (!api || !walletAdapter || !signingEnabled) {
      setActionError("Подписание отключено до утверждения testnet ABI и Backend API.");
      return;
    }
    if (!walletAdapter.connectedWallet || walletAdapter.connectedWallet.chain !== CHAIN.TESTNET) {
      setActionError("Подключите кошелёк в TON testnet.");
      return;
    }

    actionLock.current = true;
    setBusy(true);
    setActionError("");
    let walletRequestStarted = false;
    try {
      const result = await walletAdapter.sendPreparedTransaction(
        pending.transaction,
        pending.expectedWalletAddress,
        () => { walletRequestStarted = true; },
      );
      const reference = await walletBocReference(result.boc);
      try {
        await api.submitWalletReference({
          action_id: pending.transaction.action_id,
          action: pending.transaction.action,
          reference,
        });
        setPending(null);
        setActionMessage("BOC digest передан Backend observer как lookup hint. Это не tx hash и не подтверждение состояния сделки.");
        setRetry((value) => value + 1);
      } catch (reason) {
        setRetryReference(reference);
        setWalletResultUncertain(true);
        setActionError(reason instanceof Error ? reason.message : "Не удалось передать ссылку на проверку.");
        setActionMessage("Транзакция могла попасть в сеть. Не подписывайте повторно: можно повторно отправить только тот же BOC digest.");
      }
    } catch (reason) {
      const walletError = reason && typeof reason === "object"
        ? reason as { code?: number; message?: string }
        : null;
      const rejected = walletError?.code === 300 || /reject|cancel/i.test(walletError?.message ?? "");
      if (walletRequestStarted && !rejected) setWalletResultUncertain(true);
      setActionError(rejected
        ? "Запрос кошелька отклонён. Backend не получил подтверждение операции."
        : "Результат запроса кошелька неизвестен. Проверьте состояние сделки в Backend.");
      if (walletRequestStarted && !rejected) {
        setActionMessage("Не отправляйте повторную транзакцию, пока Backend observer не сверит первое действие.");
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
        action_id: pending.transaction.action_id,
        action: pending.transaction.action,
        reference: retryReference,
      });
      setRetryReference("");
      setPending(null);
      setWalletResultUncertain(false);
      setActionMessage("Тот же BOC digest передан observer повторно. Дождитесь подтверждения контрактного состояния.");
      setRetry((value) => value + 1);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Не удалось повторно отправить тот же BOC digest.");
    } finally {
      actionLock.current = false;
      setBusy(false);
    }
  }

  function sellerWalletForDeal(deal: EscrowDeal): WalletRecord | null {
    return verifiedWalletForAddress(deal.seller_wallet_address);
  }

  function buyerWalletForDeal(deal: EscrowDeal): WalletRecord | null {
    return verifiedWalletForAddress(deal.buyer_wallet_address);
  }

  const selectedDealBuyerWallet = selectedDeal ? buyerWalletForDeal(selectedDeal) : null;

  return (
    <section className="escrow-workspace" aria-labelledby="escrow-workspace-title">
      <header className="escrow-workspace-heading">
        <div>
          <p className="eyebrow">VILTARA · TON TESTNET</p>
          <h1 id="escrow-workspace-title">TON Escrow</h1>
          <p>Listing intent, отдельная сделка, NFT-депозит и TON фиксируются раздельно. Истина о состоянии берётся из контрактного observer.</p>
        </div>
        <button className="escrow-refresh-button" type="button" onClick={refresh} disabled={loading || inventoryLoading}>
          Обновить
        </button>
      </header>

      <div className="escrow-testnet-notice" role="note">
        <strong>Только TON testnet · fee_bps = 0.</strong>
        Это изолированный интерфейс PoC. Buyer сначала создаёт deal intent, продавец вносит NFT, и только после observer confirmation покупатель может внести TON. Не подключено к production orders, Stars или mainnet.
      </div>

      <div className="escrow-role-tabs" role="tablist" aria-label="Роль в escrow">
        <button type="button" role="tab" aria-selected={role === "buyer"} className={role === "buyer" ? "is-active" : ""} onClick={() => { setRole("buyer"); setSelectedDealId(ownedBuyerDeals[0]?.id ?? ""); }}>
          Покупатель
        </button>
        <button type="button" role="tab" aria-selected={role === "seller"} className={role === "seller" ? "is-active" : ""} onClick={() => { setRole("seller"); setSelectedDealId(ownedSellerDeals[0]?.id ?? ""); }}>
          Продавец
        </button>
      </div>

      {apiError && <div className="escrow-message escrow-message-error" role="alert"><strong>Escrow API недоступен</strong><p>{apiError}</p><button type="button" onClick={refresh}>Повторить</button></div>}
      {inventoryError && <div className="escrow-message escrow-message-error" role="alert"><strong>Инвентарь недоступен</strong><p>{inventoryError}</p></div>}
      {actionError && <p className="escrow-inline-error" role="alert">{actionError}</p>}
      {actionMessage && <p className="escrow-inline-message" role="status">{actionMessage}</p>}

      {role === "seller" ? (
        <div className="escrow-panel">
          <section className="escrow-section" aria-labelledby="escrow-seller-intent-title">
            <div className="escrow-section-heading">
              <div><p className="eyebrow">ПРЕДЛОЖЕНИЕ ПРОДАВЦА</p><h2 id="escrow-seller-intent-title">Создать listing intent</h2></div>
              <span>{sellerInventory.length} NFT</span>
            </div>
            <p className="escrow-muted">Создание listing intent не депонирует NFT и не создаёт сделку. Если обычное объявление создано как черновик, опубликуйте его в разделе «Мои объявления»: покупателям доступны только активные объявления. После привязки buyer wallet Backend подготовит отдельный DealEscrow для конкретной пары участников.</p>
            {onManageListings && <button className="escrow-button escrow-button-secondary" type="button" onClick={onManageListings}>Открыть мои объявления</button>}
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
                      <span><strong>{title}</strong><small>{shortAddress(entry.asset.item_address)}</small><small>Backend verified · {shortAddress(entry.wallet.address)}</small></span>
                    </button>
                  );
                })}
              </div>
            ) : (
              <div className="escrow-empty-state"><h3>Нет подходящих NFT</h3><p>Подтвердите testnet-кошелёк и убедитесь, что NFT доступен для listing intent.</p></div>
            )}
            {selectedNft && (
              <div className="escrow-deposit-preview">
                <h3>Параметры предложения</h3>
                <label className="escrow-wallet-select" htmlFor="escrow-seller-price">
                  <span>Цена предложения · TON testnet</span>
                  <input
                    id="escrow-seller-price"
                    aria-label="Цена предложения · TON testnet"
                    name="price_ton"
                    type="text"
                    inputMode="decimal"
                    autoComplete="off"
                    placeholder="Например, 2.5"
                    value={sellerPriceTon}
                    onChange={(event) => setSellerPriceTon(event.target.value)}
                    aria-describedby="escrow-seller-price-help"
                  />
                  <small id="escrow-seller-price-help">До 9 знаков после запятой. Цена сериализуется в nanotons без float-округления; Backend дополнительно проверяет диапазон.</small>
                </label>
                <dl className="escrow-facts">
                  <div><dt>Сеть</dt><dd>TON testnet</dd></div>
                  <div><dt>NFT item</dt><dd><code>{selectedNft.asset.item_address}</code></dd></div>
                  <div><dt>Кошелёк продавца</dt><dd><code>{selectedNft.wallet.address}</code></dd></div>
                  <div><dt>Комиссия платформы</dt><dd>0 bps · PoC</dd></div>
                </dl>
                <button className="escrow-button escrow-button-primary" type="button" disabled={!api || busy || loading || !tonToNano(sellerPriceTon)} onClick={() => void createListingIntent()}>
                  {busy ? "Создаём предложение…" : "Создать listing intent"}
                </button>
              </div>
            )}
          </section>

          <section className="escrow-section" aria-labelledby="escrow-seller-listings-title">
            <div className="escrow-section-heading"><div><p className="eyebrow">МОИ ПРЕДЛОЖЕНИЯ</p><h2 id="escrow-seller-listings-title">Listing intents</h2></div></div>
            {loading ? <p className="escrow-empty-inline" role="status">Загружаем предложения…</p> : ownedSellerListings.length ? (
              <div className="escrow-list">
                {ownedSellerListings.map((listing) => (
                  <article key={listing.id} className="escrow-row-card">
                    <div className="escrow-row-main">
                      <NftArtwork src={listing.nft.image_url} title={titleForNft(listing.nft)} />
                      <div><strong>{titleForNft(listing.nft)}</strong><ListingIntentStateBadge state={listing.state} /><p className="escrow-state-guidance">{ESCROW_LISTING_STATE_META[listing.state].guidance}</p></div>
                    </div>
                    <dl className="escrow-compact-facts">
                      <div><dt>Цена</dt><dd>{nanoToTon(listing.price_nano)} TON</dd></div>
                      <div><dt>Listing key</dt><dd><code>{listing.listing_key ?? "Назначается Backend"}</code></dd></div>
                      <div><dt>NFT item</dt><dd><code>{shortAddress(listing.nft.item_address)}</code></dd></div>
                    </dl>
                  </article>
                ))}
              </div>
            ) : <p className="escrow-empty-inline">Listing intents пока нет.</p>}
          </section>

          <section className="escrow-section" aria-labelledby="escrow-seller-deals-title">
            <div className="escrow-section-heading"><div><p className="eyebrow">ВХОДЯЩИЕ СДЕЛКИ</p><h2 id="escrow-seller-deals-title">Депозит NFT и возврат</h2></div></div>
            {loading ? <p className="escrow-empty-inline" role="status">Загружаем сделки…</p> : ownedSellerDeals.length ? (
              <div className="escrow-list">
                {ownedSellerDeals.map((deal) => {
                  const signer = sellerWalletForDeal(deal);
                  return (
                    <article className="escrow-row-card" key={deal.id}>
                      <div className="escrow-row-main"><NftArtwork src={deal.nft.image_url} title={titleForNft(deal.nft)} /><div><strong>{titleForNft(deal.nft)}</strong><DealStateBadge state={deal.state} /><StateGuidance state={deal.state} /></div></div>
                      <dl className="escrow-compact-facts">
                        <div><dt>Цена</dt><dd>{nanoToTon(deal.price_nano)} TON</dd></div>
                        <div><dt>DealEscrow</dt><dd><code>{deal.escrow_address ?? "Ещё не создан"}</code></dd></div>
                        <div><dt>NFT item</dt><dd><code>{shortAddress(deal.nft.item_address)}</code></dd></div>
                      </dl>
                      {deal.state === "seller_payout_pending" && (
                        <p className="escrow-inline-message" role="status">Контракт инициировал seller payout. Ручного claim нет; ждём подтверждение финальности observer.</p>
                      )}
                      {deal.state === "buyer_refund_pending" && (
                        <p className="escrow-warning" role="status">Контракт инициировал buyer refund. Ожидается финальное подтверждение observer.</p>
                      )}
                      {deal.state === "manual_review" && (
                        <p className="escrow-warning" role="status">Сделка требует reconciliation. Не отправляйте повторные транзакции до обновления состояния Backend.</p>
                      )}
                      {deal.dispute && (
                        <div className="escrow-dispute-card" role="status">
                          <strong>Спор · {ESCROW_DISPUTE_LABELS[deal.dispute.status]}</strong>
                          <p>{deal.dispute.summary || deal.dispute.reason_code}</p>
                          <span>Открыт: {formatEscrowDate(deal.dispute.opened_at)}</span>
                          {deal.dispute.resolution_note && <p>Решение: {deal.dispute.resolution_note}</p>}
                        </div>
                      )}
                      <div className="escrow-buyer-actions">
                        {allowed("create_deal_escrow", deal.available_actions) && (
                          <button className="escrow-button escrow-button-primary" type="button" disabled={!api || busy || !signer} onClick={() => signer && void prepareWalletAction("create_deal_escrow", deal, () => api!.prepareDealEscrow({ deal_id: deal.id, wallet_id: signer.id }), signer)}>
                            Создать DealEscrow
                          </button>
                        )}
                        {allowed("deposit_nft", deal.available_actions) && (
                          <button className="escrow-button escrow-button-primary" type="button" disabled={!api || busy || !signer} onClick={() => signer && void prepareWalletAction("deposit_nft", deal, () => api!.prepareNftDeposit({ deal_id: deal.id, wallet_id: signer.id }), signer)}>
                            Внести NFT в DealEscrow
                          </button>
                        )}
                        {allowed("withdraw_unsold_nft", deal.available_actions) && (
                          <button className="escrow-button escrow-button-secondary" type="button" disabled={!api || busy || !signer} onClick={() => signer && void prepareWalletAction("withdraw_unsold_nft", deal, () => api!.prepareUnsoldNftWithdrawal({ deal_id: deal.id, wallet_id: signer.id }), signer)}>
                            Вернуть непроданный NFT
                          </button>
                        )}
                      </div>
                    </article>
                  );
                })}
              </div>
            ) : <p className="escrow-empty-inline">Входящих сделок пока нет. Когда покупатель создаст deal intent, он появится здесь.</p>}
            <h3 className="escrow-subheading">История возврата непроданных NFT</h3>
            <WithdrawalList withdrawals={withdrawals} />
          </section>
        </div>
      ) : (
        <div className="escrow-panel">
          <section className="escrow-section" aria-labelledby="escrow-buyer-market-title">
            <div className="escrow-section-heading"><div><p className="eyebrow">КАТАЛОГ LISTING INTENTS</p><h2 id="escrow-buyer-market-title">Предложения продавцов</h2></div><span>{marketplaceListings.length} предложений</span></div>
            <label className="escrow-wallet-select">
              <span>Подтверждённый кошелёк покупателя · TON testnet</span>
              <select value={selectedBuyerWalletId} onChange={(event) => setSelectedBuyerWalletId(event.target.value)} disabled={!inventory.wallets.length}>
                {inventory.wallets.map((wallet) => <option value={wallet.id} key={wallet.id}>{shortAddress(wallet.address)}{wallet.is_primary ? " · основной" : ""}</option>)}
              </select>
            </label>
            {loading ? <p className="escrow-empty-inline" role="status">Загружаем предложения…</p> : marketplaceListings.length ? (
              <div className="escrow-market-grid">
                {marketplaceListings.map((listing) => <ListingIntentCard key={listing.id} listing={listing} selected={selectedListingId === listing.id} onSelect={() => setSelectedListingId(listing.id)} />)}
              </div>
            ) : <div className="escrow-empty-state"><h3>Предложений пока нет</h3><p>Listing intent станет доступен после серверной публикации продавцом.</p></div>}
            {selectedListing && (
              <article className="escrow-selected-listing">
                <div className="escrow-row-main"><NftArtwork src={selectedListing.nft.image_url} title={titleForNft(selectedListing.nft)} /><div><p className="eyebrow">ПРЕДЛОЖЕНИЕ ПРОДАВЦА</p><h3>{titleForNft(selectedListing.nft)}</h3><ListingIntentStateBadge state={selectedListing.state} /></div></div>
                <dl className="escrow-facts">
                  <div><dt>Сеть</dt><dd>TON testnet</dd></div>
                  <div><dt>NFT item</dt><dd><code>{selectedListing.nft.item_address}</code></dd></div>
                  <div><dt>Цена</dt><dd>{nanoToTon(selectedListing.price_nano)} TON</dd></div>
                  <div><dt>Комиссия</dt><dd>0 TON · 0 bps · PoC</dd></div>
                  <div><dt>Продавец</dt><dd><code>{shortAddress(selectedListing.seller_wallet_address)}</code></dd></div>
                </dl>
                <p className="escrow-warning">Создание deal intent привяжет ваш verified testnet wallet к сделке. Это ещё не оплата. Сначала продавец подпишет создание DealEscrow и внесёт точный NFT; только после observer-confirmed состояния awaiting_buyer_funds появится подготовка TON funding.</p>
                <button className="escrow-button escrow-button-primary" type="button" disabled={!api || busy || !selectedBuyerWallet || selectedListing.seller_id === currentUserId || !selectedListing.available_actions.includes("create_deal_intent")} onClick={() => void createBuyerDealIntent()}>
                  Создать сделку
                </button>
              </article>
            )}
          </section>

          <section className="escrow-section" aria-labelledby="escrow-buyer-deals-title">
            <div className="escrow-section-heading"><div><p className="eyebrow">МОИ СДЕЛКИ</p><h2 id="escrow-buyer-deals-title">Депозит, TON funding и dispute</h2></div></div>
            {loading ? <p className="escrow-empty-inline" role="status">Загружаем сделки…</p> : ownedBuyerDeals.length ? (
              <div className="escrow-deals-grid">
                {ownedBuyerDeals.map((deal) => <DealCard key={deal.id} deal={deal} role="buyer" selected={selectedDealId === deal.id} onSelect={() => setSelectedDealId(deal.id)} />)}
              </div>
            ) : <p className="escrow-empty-inline">Deal intents пока нет.</p>}
            {selectedDeal && (
              <article className="escrow-selected-deal">
                <div className="escrow-section-heading"><div><p className="eyebrow">DEAL {selectedDeal.id.slice(0, 8)}</p><h3>{titleForNft(selectedDeal.nft)}</h3></div><DealStateBadge state={selectedDeal.state} /></div>
                <StateGuidance state={selectedDeal.state} />
                <dl className="escrow-facts">
                  <div><dt>DealEscrow</dt><dd><code>{selectedDeal.escrow_address ?? "Создаётся; дождитесь observer"}</code></dd></div>
                  <div><dt>NFT item</dt><dd><code>{selectedDeal.nft.item_address}</code></dd></div>
                  <div><dt>Цена</dt><dd>{nanoToTon(selectedDeal.price_nano)} TON</dd></div>
                  <div><dt>Комиссия</dt><dd>0 bps · PoC</dd></div>
                  <div><dt>Окно проверки</dt><dd>{formatEscrowDate(selectedDeal.buyer_review_deadline)}</dd></div>
                  <div><dt>Окончание dispute window</dt><dd>{formatEscrowDate(selectedDeal.dispute_deadline)}</dd></div>
                </dl>
                {selectedDeal.dispute && (
                  <div className="escrow-dispute-card" role="status">
                    <strong>Спор · {ESCROW_DISPUTE_LABELS[selectedDeal.dispute.status]}</strong>
                    <p>{selectedDeal.dispute.summary || selectedDeal.dispute.reason_code}</p>
                    <span>Открыт: {formatEscrowDate(selectedDeal.dispute.opened_at)}</span>
                    {selectedDeal.dispute.resolution_note && <p>Решение: {selectedDeal.dispute.resolution_note}</p>}
                  </div>
                )}
                {selectedDeal.state === "seller_payout_pending" && <p className="escrow-inline-message" role="status">Контракт инициировал seller payout. Ручного claim нет; ждём подтверждение финальности от observer.</p>}
                {selectedDeal.state === "buyer_refund_pending" && <p className="escrow-warning" role="status">Контракт инициировал refund. Он не считается завершённым, пока observer не подтвердит финальность.</p>}
                {selectedDeal.state === "manual_review" && <p className="escrow-warning" role="status">Операции приостановлены. Не отправляйте повторные платежи или переводы NFT до завершения reconciliation.</p>}
                {allowed("fund_deal", selectedDeal.available_actions) && (
                  <button className="escrow-button escrow-button-primary" type="button" disabled={!api || busy || !selectedDealBuyerWallet} onClick={() => selectedDealBuyerWallet && void prepareWalletAction("fund_deal", selectedDeal, () => api!.prepareBuyerFunding({ deal_id: selectedDeal.id, wallet_id: selectedDealBuyerWallet.id }), selectedDealBuyerWallet)}>
                    Внести TON
                  </button>
                )}
                {allowed("accept_deal", selectedDeal.available_actions) && (
                  <button className="escrow-button escrow-button-primary" type="button" disabled={!api || busy || !selectedDealBuyerWallet} onClick={() => selectedDealBuyerWallet && void prepareWalletAction("accept_deal", selectedDeal, () => api!.prepareBuyerAcceptance({ deal_id: selectedDeal.id, wallet_id: selectedDealBuyerWallet.id }), selectedDealBuyerWallet)}>
                    Принять условия и передать NFT
                  </button>
                )}
                {allowed("open_dispute", selectedDeal.available_actions) && (
                  <div className="escrow-buyer-actions">
                    <label className="escrow-dispute-reason"><span>Причина спора</span><textarea rows={3} value={disputeReason} onChange={(event) => setDisputeReason(event.target.value)} placeholder="Опишите проблему с депозитом, оплатой или передачей NFT." /></label>
                    <button className="escrow-button escrow-button-danger" type="button" disabled={!api || busy || !selectedDealBuyerWallet || disputeReason.trim().length < 8} onClick={() => selectedDealBuyerWallet && void prepareWalletAction("open_dispute", selectedDeal, () => api!.prepareDispute({ deal_id: selectedDeal.id, reason: disputeReason.trim() }), selectedDealBuyerWallet)}>
                      Открыть спор
                    </button>
                  </div>
                )}
                {allowed("return_nft_to_escrow", selectedDeal.available_actions) && (
                  <div className="escrow-return-nft">
                    <p className="escrow-warning">Для buyer-favourable post-delivery resolution нужно вернуть именно этот NFT в escrow. Refund невозможен, пока NFT остаётся у покупателя.</p>
                    <button className="escrow-button escrow-button-primary" type="button" disabled={!api || busy || !selectedDealBuyerWallet} onClick={() => selectedDealBuyerWallet && void prepareWalletAction("return_nft_to_escrow", selectedDeal, () => api!.prepareBuyerNftReturn({ deal_id: selectedDeal.id, wallet_id: selectedDealBuyerWallet.id }), selectedDealBuyerWallet)}>
                      Вернуть NFT в escrow
                    </button>
                  </div>
                )}
              </article>
            )}
          </section>
        </div>
      )}

      {!walletConnected && manifestConfigured && (
        <button className="escrow-button escrow-button-secondary escrow-connect-button" type="button" onClick={() => { void onConnectWallet?.(); }}>
          Подключить testnet-кошелёк
        </button>
      )}
      {walletConnected && walletAdapter?.connectedWallet?.chain !== CHAIN.TESTNET && (
        <p className="escrow-inline-error" role="alert">Подключён не TON testnet. Все escrow-действия заблокированы.</p>
      )}
      {walletConnected && walletAdapter?.connectedWallet?.chain === CHAIN.TESTNET && (
        <p className="escrow-inline-message" role="status">Кошелёк подключён. Владение NFT и право подписи проверяются отдельно по Backend-записи verified wallet.</p>
      )}
      {!signingEnabled && <p className="escrow-integration-lock" role="status">Wallet signing выключен по умолчанию. Никакое действие не будет отправлено в сеть без отдельного testnet-only включения после ABI/API review.</p>}

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
          Повторно отправить тот же BOC digest observer
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

  return (
    <WorkspaceBody
      {...props}
      walletAdapter={walletAdapter}
      walletConnected={Boolean(wallet)}
      onConnectWallet={() => tonConnectUI.openModal()}
      manifestConfigured
    />
  );
}

/** Standalone until the shared API/ABI is frozen and the host integration is approved. */
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
