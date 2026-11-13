import { useCallback, useEffect, useRef, useState } from "react";
import {
  fetchListing,
  fetchListings,
  type AssetType,
  type Listing,
  type ListingSort,
  type PriceCurrency,
} from "./api/listings";
import { createOrder } from "./api/orders";
import { SessionProvider, useRetrySession, useSession } from "./auth/SessionProvider";
import { getTelegramStartParam } from "./auth/telegram";
import { MyListings } from "./listings/MyListings";
import { MyInventory } from "./inventory/MyInventory";
import { Orders } from "./orders/Orders";
import { SellerReviews } from "./reviews/SellerReviews";
import { WalletConnection } from "./wallet/WalletConnection";
import type { WalletRecord } from "./wallet/api";

const assetTypeLabels: Record<AssetType, string> = {
  ton_nft: "TON NFT",
  telegram_gift: "Подарок Telegram",
};
const CATALOG_PAGE_SIZE = 24;

function formatItemCount(count: number) {
  const category = new Intl.PluralRules("ru-RU").select(count);
  const noun = category === "one" ? "предмет" : category === "few" ? "предмета" : "предметов";
  return `${count} ${noun}`;
}

function formatVerificationStatus(status: string) {
  const labels: Record<string, string> = {
    verified: "Подтверждён",
    stale: "Устарел",
    invalid: "Не подтверждён",
    unsupported: "Не поддерживается",
    provider_unavailable: "Провайдер недоступен",
  };
  return labels[status] ?? "Неизвестно";
}

function formatPrice(amount: string, currency: string) {
  const numericAmount = Number(amount);
  const formattedAmount = Number.isFinite(numericAmount)
    ? new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 4 }).format(numericAmount)
    : amount;
  return `${formattedAmount} ${currency}`;
}

function AssetArtwork({ imageUrl, name }: { imageUrl: string | null; name: string }) {
  const [imageFailed, setImageFailed] = useState(false);
  useEffect(() => setImageFailed(false), [imageUrl]);

  return (
    <div className="artwork">
      {imageUrl && !imageFailed ? (
        <img src={imageUrl} alt={name} loading="lazy" onError={() => setImageFailed(true)} />
      ) : (
        <div className="artwork-placeholder" aria-label="Изображение недоступно"><span>V</span></div>
      )}
    </div>
  );
}

function ListingCard({ listing, onOpen }: { listing: Listing; onOpen: () => void }) {
  const title = listing.title || listing.asset.name || "Без названия";
  const collection = listing.asset.collection?.name;
  const seller = listing.seller.username
    ? `@${listing.seller.username}`
    : listing.seller.first_name || "Продавец";

  return (
    <button className="listing-card" type="button" onClick={onOpen}>
      <AssetArtwork imageUrl={listing.asset.image_url} name={title} />
      <span className="listing-card-content">
        <span className="listing-card-topline">
          <span className="listing-card-type">{assetTypeLabels[listing.asset.asset_type]}</span>
          {listing.asset.verification_status === "verified" && (
            <span className="listing-card-verified">
              <span aria-hidden="true">✓</span> Проверен
            </span>
          )}
        </span>
        {collection && <span className="listing-card-collection">{collection}</span>}
        <span className="listing-card-title">{title}</span>
        <span className="listing-card-footer">
          <span className="listing-card-price">{formatPrice(listing.price_amount, listing.price_currency)}</span>
          <span className="listing-card-seller">{seller}</span>
        </span>
      </span>
    </button>
  );
}

function appendUniqueListings(current: Listing[], nextPage: Listing[]) {
  const seenIds = new Set(current.map((listing) => listing.id));
  const merged = [...current];
  for (const listing of nextPage) {
    if (!seenIds.has(listing.id)) {
      seenIds.add(listing.id);
      merged.push(listing);
    }
  }
  return merged;
}

function ListingDetail({ listingId, onBack, onOrders }: { listingId: string; onBack: () => void; onOrders: () => void }) {
  const session = useSession();
  const [listing, setListing] = useState<Listing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [ordering, setOrdering] = useState(false);
  const [orderError, setOrderError] = useState("");
  const [orderCreated, setOrderCreated] = useState(false);
  const [confirmationOpen, setConfirmationOpen] = useState(false);
  const idempotencyKey = useRef<string | null>(null);
  const submittingRef = useRef(false);
  const reserveTriggerRef = useRef<HTMLButtonElement | null>(null);
  const confirmButtonRef = useRef<HTMLButtonElement | null>(null);
  const dialogRef = useRef<HTMLElement | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetchListing(listingId, controller.signal)
      .then(setListing)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Не удалось загрузить объявление.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [listingId, retry]);

  useEffect(() => {
    if (!confirmationOpen) return;
    confirmButtonRef.current?.focus();
    function handleKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !submittingRef.current && !orderCreated) {
        setConfirmationOpen(false);
        window.setTimeout(() => reserveTriggerRef.current?.focus(), 0);
        return;
      }
      if (event.key === "Tab") {
        const focusable = dialogRef.current?.querySelectorAll<HTMLElement>(
          "button:not(:disabled), a[href], input:not(:disabled), select:not(:disabled), textarea:not(:disabled), [tabindex]:not([tabindex=\"-1\"])",
        );
        if (!focusable?.length) { event.preventDefault(); return; }
        const first = focusable[0];
        const last = focusable[focusable.length - 1];
        if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
        else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
      }
    }
    window.addEventListener("keydown", handleKeyDown);
    return () => window.removeEventListener("keydown", handleKeyDown);
  }, [confirmationOpen, orderCreated]);

  if (loading) return <p className="detail-message" role="status">Загружаем объявление…</p>;
  if (error || !listing) {
    return (
      <section className="detail-message" role="alert">
        <p>{error || "Это объявление недоступно."}</p>
        <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Повторить</button>
      </section>
    );
  }

  const title = listing.title || listing.asset.name || "Без названия";
  const seller = listing.seller.first_name || listing.seller.username || "Продавец";
  const canOrder = session.status === "authenticated" && session.user.id !== listing.seller.id;

  async function handleOrder() {
    if (session.status !== "authenticated" || submittingRef.current || orderCreated) return;
    submittingRef.current = true;
    setOrdering(true);
    setOrderError("");
    try {
      // Keep this key for retries after an uncertain network result: one intent, one key.
      idempotencyKey.current ??= crypto.randomUUID();
      await createOrder(listingId, session.accessToken, idempotencyKey.current);
      setOrderCreated(true);
    } catch (reason) {
      setOrderError(reason instanceof Error ? reason.message : "Не удалось создать резерв. Попробуйте ещё раз.");
    } finally {
      submittingRef.current = false;
      setOrdering(false);
    }
  }

  return (
    <section className="detail-view" aria-labelledby="detail-title">
      <button className="text-button back-button" type="button" onClick={onBack}>
        <span aria-hidden="true">←</span> Назад в каталог
      </button>
      <div className="detail-layout">
        <AssetArtwork imageUrl={listing.asset.image_url} name={title} />
        <div className="detail-copy">
          <p className="eyebrow">{assetTypeLabels[listing.asset.asset_type]}</p>
          <h1 id="detail-title">{title}</h1>
          <p className="detail-price">{formatPrice(listing.price_amount, listing.price_currency)}</p>
          <section className="seller-profile" aria-label="Профиль продавца">
            <div className="seller-profile-avatar" aria-hidden="true">
              {(seller.trim().charAt(0) || "S").toUpperCase()}
            </div>
            <div className="seller-profile-copy">
              <strong>{seller}</strong>
              <span>{listing.seller.username ? `@${listing.seller.username}` : "Продавец в Telegram"}</span>
            </div>
          </section>
          {canOrder ? (
            <div className="order-action">
              <button ref={reserveTriggerRef} className="primary-button" type="button" disabled={ordering || orderCreated} onClick={() => { setOrderError(""); setConfirmationOpen(true); }}>
                {ordering ? "Создаём резерв…" : orderCreated ? "Резерв создан" : "Зарезервировать"}
              </button>
              {orderError && !confirmationOpen && <p role="alert">{orderError}</p>}
              {orderCreated && (
                <div className="reservation-success" role="status">
                  <p>Резерв для «{title}» создан. Оплата не проводилась, NFT пока остаётся у продавца.</p>
                  <button className="primary-button" type="button" onClick={onOrders}>Мои заказы</button>
                </div>
              )}
            </div>
          ) : session.status === "authenticated" ? (
            <p className="detail-description">Нельзя зарезервировать собственное объявление.</p>
          ) : (
            <p className="detail-description">Откройте VILTARA в Telegram, чтобы оформить резерв.</p>
          )}
          {confirmationOpen && (
            <div className="reservation-dialog-backdrop">
              <section ref={dialogRef} className="reservation-dialog" role="dialog" aria-modal="true" aria-labelledby="reservation-dialog-title" aria-describedby="reservation-dialog-description">
                {orderCreated ? (
                  <>
                    <p className="eyebrow">РЕЗЕРВ СОЗДАН</p>
                    <h2 id="reservation-dialog-title">Резерв подтверждён</h2>
                    <p id="reservation-dialog-description">Резерв для «{title}» создан. Оплата не проводилась, NFT пока остаётся у продавца.</p>
                    <button className="primary-button" type="button" onClick={onOrders}>Мои заказы</button>
                  </>
                ) : (
                  <>
                    <p className="eyebrow">ПОДТВЕРЖДЕНИЕ РЕЗЕРВА</p>
                    <h2 id="reservation-dialog-title">Зарезервировать это объявление?</h2>
                    <dl className="reservation-summary">
                      <div><dt>Объявление</dt><dd>{title}</dd></div>
                      <div><dt>Цена</dt><dd>{formatPrice(listing.price_amount, listing.price_currency)}</dd></div>
                      <div><dt>Продавец</dt><dd>{seller}{listing.seller.username ? ` (@${listing.seller.username})` : ""}</dd></div>
                    </dl>
                    <p id="reservation-dialog-description" className="reservation-disclaimer">Это только резерв объявления. Оплата не проводится, средства не списываются, NFT остаётся у продавца.</p>
                    {orderError && <p className="reservation-error" role="alert">{orderError} Запрос мог быть обработан сервером. Повторная попытка не создаст дубликат резерва.</p>}
                    <div className="reservation-dialog-actions">
                      <button className="text-button" type="button" disabled={ordering} onClick={() => { setConfirmationOpen(false); setOrderError(""); window.setTimeout(() => reserveTriggerRef.current?.focus(), 0); }}>Отмена</button>
                      <button ref={confirmButtonRef} className="primary-button" type="button" disabled={ordering} onClick={() => void handleOrder()}>{ordering ? "Создаём резерв…" : "Подтвердить резерв"}</button>
                    </div>
                  </>
                )}
              </section>
            </div>
          )}
          {listing.description && <p className="detail-description">{listing.description}</p>}
          {listing.asset.description && <p className="detail-description">{listing.asset.description}</p>}
          <dl className="detail-facts">
            <div>
              <dt>Коллекция</dt>
              <dd>{listing.asset.collection?.name ?? "Без коллекции"}</dd>
            </div>
            <div>
              <dt>Адрес NFT</dt>
              <dd>
                <code className="mono">{listing.asset.item_address ?? "Недоступно"}</code>
              </dd>
            </div>
            <div><dt>ID актива</dt><dd>{listing.asset.external_id}</dd></div>
            <div><dt>Проверка</dt><dd>{formatVerificationStatus(listing.asset.verification_status)}</dd></div>
          </dl>
          <SellerReviews
            sellerId={listing.seller.id}
            accessToken={session.status === "authenticated" ? session.accessToken : null}
          />
        </div>
      </div>
    </section>
  );
}

export function App() {
  return (
    <SessionProvider>
      <MarketplaceApp />
    </SessionProvider>
  );
}

function SessionBanner() {
  const session = useSession();
  const retrySession = useRetrySession();
  if (session.status === "loading") {
    return <p className="session-banner" role="status">Проверяем сессию Telegram…</p>;
  }
  if (session.status === "authenticated") {
    const name = [session.user.first_name, session.user.last_name].filter(Boolean).join(" ");
    const username = session.user.username ? ` · @${session.user.username}` : "";
    return <p className="session-banner session-authenticated" role="status">Вы вошли как {name || session.user.username}{username}</p>;
  }
  if (session.status === "error") {
    return (
      <div className="session-banner session-error" role="alert">
        <span>{session.message}</span>
        {session.retryable && (
          <button className="text-button" type="button" onClick={retrySession}>
            Повторить проверку
          </button>
        )}
      </div>
    );
  }
  return (
    <p className="session-banner" role="status">
      {session.reason === "missing_init_data"
        ? "Откройте VILTARA в Telegram, чтобы войти. Каталог доступен без авторизации."
        : "Не удалось подтвердить сессию Telegram. Откройте мини-приложение повторно."}
    </p>
  );
}

function MarketplaceApp() {
  const session = useSession();
  const sessionAccessToken = session.status === "authenticated"
    ? session.accessToken
    : null;
  const [selectedWalletState, setSelectedWalletState] = useState<{
    accessToken: string;
    wallet: WalletRecord | null;
  } | null>(null);
  const onSelectedWalletChange = useCallback((wallet: WalletRecord | null) => {
    if (sessionAccessToken) {
      setSelectedWalletState({ accessToken: sessionAccessToken, wallet });
    }
  }, [sessionAccessToken]);
  const selectedWallet = selectedWalletState?.accessToken === sessionAccessToken
    ? selectedWalletState.wallet
    : null;
  const startParam = useRef(getTelegramStartParam()).current;
  const [initialOrderId, setInitialOrderId] = useState<string | null>(null);
  const [section, setSection] = useState<"catalog" | "my-listings" | "my-nft" | "orders">("catalog");
  const [listings, setListings] = useState<Listing[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [assetType, setAssetType] = useState<AssetType | "all">("all");
  const [currency, setCurrency] = useState<PriceCurrency | "all">("all");
  const [minPrice, setMinPrice] = useState("");
  const [maxPrice, setMaxPrice] = useState("");
  const [sort, setSort] = useState<ListingSort>("newest");
  const [listingId, setListingId] = useState<string | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");
  const [nextOffset, setNextOffset] = useState(0);
  const [retry, setRetry] = useState(0);
  const requestVersion = useRef(0);
  const loadingMoreRef = useRef(false);
  const loadMoreController = useRef<AbortController | null>(null);

  useEffect(() => {
    if (!startParam) return;

    if (startParam.type === "listing") {
      setInitialOrderId(null);
      setListingId(startParam.id);
      setSection("catalog");
      return;
    }

    if (session.status === "loading") return;
    setInitialOrderId(startParam.id);
    setListingId(null);
    setSection("orders");
  }, [session.status, startParam]);

  useEffect(() => {
    const version = ++requestVersion.current;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setLoadMoreError("");
    setLoadingMore(false);
    loadingMoreRef.current = false;
    loadMoreController.current?.abort();
    loadMoreController.current = null;
    setListings([]);
    setTotal(0);
    setNextOffset(0);
    fetchListings({ search, assetType, currency, minPrice, maxPrice, sort, limit: CATALOG_PAGE_SIZE, offset: 0 }, controller.signal)
      .then((page) => {
        if (controller.signal.aborted || version !== requestVersion.current) return;
        setListings(page.items);
        setTotal(page.total);
        setNextOffset(page.offset + page.items.length);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted && version === requestVersion.current) {
          setError(reason instanceof Error ? reason.message : "Не удалось загрузить каталог.");
          setListings([]);
          setTotal(0);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && version === requestVersion.current) setLoading(false);
      });
    return () => {
      controller.abort();
      loadMoreController.current?.abort();
      loadMoreController.current = null;
      loadingMoreRef.current = false;
      if (requestVersion.current === version) requestVersion.current += 1;
    };
  }, [search, assetType, currency, minPrice, maxPrice, sort, retry]);

  const hasMore = listings.length < total && nextOffset < total;

  async function loadMore() {
    if (!hasMore || loading || error || loadingMoreRef.current) return;

    const version = requestVersion.current;
    const controller = new AbortController();
    loadingMoreRef.current = true;
    loadMoreController.current = controller;
    setLoadingMore(true);
    setLoadMoreError("");

    try {
      const page = await fetchListings(
        { search, assetType, currency, minPrice, maxPrice, sort, limit: CATALOG_PAGE_SIZE, offset: nextOffset },
        controller.signal,
      );
      if (controller.signal.aborted || version !== requestVersion.current) return;
      if (page.items.length === 0 && page.offset < page.total) {
        setLoadMoreError("Новых объявлений нет. Попробуйте ещё раз.");
        return;
      }
      setListings((current) => appendUniqueListings(current, page.items));
      setTotal(page.total);
      setNextOffset(page.offset + page.items.length);
    } catch (reason) {
      if (!controller.signal.aborted && version === requestVersion.current) {
        setLoadMoreError(reason instanceof Error ? reason.message : "Не удалось загрузить следующие объявления.");
      }
    } finally {
      if (version === requestVersion.current && !controller.signal.aborted) {
        loadingMoreRef.current = false;
        loadMoreController.current = null;
        setLoadingMore(false);
      }
    }
  }

  return (
    <main className="app-shell">
      <header className="topbar">
        <a
          className="brand"
          href="#catalog"
          onClick={() => {
            setListingId(null);
            setSection("catalog");
          }}
        >
          <span className="brand-mark" aria-hidden="true">V</span>
          <span className="brand-name">VILTARA</span>
        </a>
        <div className="header-actions">
          <span className="network-label">МАРКЕТПЛЕЙС TON</span>
          <WalletConnection
            accessToken={sessionAccessToken}
            onSelectedWalletChange={onSelectedWalletChange}
          />
        </div>
      </header>
      <SessionBanner />
      <nav className="app-navigation" aria-label="Разделы маркетплейса">
        <button
          className="navigation-tab"
          type="button"
          aria-pressed={section === "catalog"}
          onClick={() => {
            setListingId(null);
            setSection("catalog");
          }}
        >
          <span className="navigation-icon" aria-hidden="true">▦</span>
          <span className="navigation-label">Каталог</span>
        </button>
        <button
          className="navigation-tab"
          type="button"
          aria-pressed={section === "my-nft"}
          onClick={() => {
            setListingId(null);
            setSection("my-nft");
          }}
        >
          <span className="navigation-icon" aria-hidden="true">◇</span>
          <span className="navigation-label">Мои NFT</span>
        </button>
        <button
          className="navigation-tab"
          type="button"
          aria-pressed={section === "my-listings"}
          onClick={() => {
            setListingId(null);
            setSection("my-listings");
          }}
        >
          <span className="navigation-icon" aria-hidden="true">▤</span>
          <span className="navigation-label">Мои объявления</span>
        </button>
        <button
          className="navigation-tab"
          type="button"
          aria-pressed={section === "orders"}
          onClick={() => {
            setListingId(null);
            setSection("orders");
          }}
        >
          <span className="navigation-icon" aria-hidden="true">↗</span>
          <span className="navigation-label">Заказы</span>
        </button>
      </nav>

      {section === "orders" ? (
        session.status === "authenticated" ? (
          <Orders accessToken={session.accessToken} userId={session.user.id} initialOrderId={initialOrderId} onCatalog={() => setSection("catalog")} />
        ) : (
          <div className="orders-message" role="status">
            <h2>Мои заказы</h2>
            <p>Откройте VILTARA в Telegram, чтобы посмотреть покупки и продажи.</p>
          </div>
        )
      ) : section === "my-listings" ? (
        <MyListings />
      ) : section === "my-nft" ? (
        session.status === "authenticated" ? (
          <MyInventory
            key={selectedWallet ? `${selectedWallet.id}:${selectedWallet.network}` : "no-selected-wallet"}
            accessToken={session.accessToken}
            selectedWallet={selectedWallet}
          />
        ) : (
          <div className="inventory-message" role="status">
            <h2>Мои NFT</h2>
            <p>Чтобы посмотреть NFT, откройте VILTARA в Telegram и подключите кошелёк с подтверждённым владением.</p>
          </div>
        )
      ) : listingId ? (
        <ListingDetail listingId={listingId} onBack={() => setListingId(null)} onOrders={() => { setListingId(null); setInitialOrderId(null); setSection("orders"); }} />
      ) : (
        <>
          <section className="catalog-intro" id="catalog">
            <p className="eyebrow">ЦИФРОВЫЕ КОЛЛЕКЦИОННЫЕ ПРЕДМЕТЫ · TON</p>
            <h1>Найдите свой<br /><span>следующий цифровой актив.</span></h1>
            <p className="intro-copy">Каталог цифровых предметов, выставленных владельцами на продажу.</p>
          </section>
          <section className="catalog" aria-label="Каталог маркетплейса">
            <div className="catalog-heading">
              <h2>Объявления</h2>
              {!loading && !error && <span className="result-count">{formatItemCount(total)}</span>}
            </div>
            <form className="catalog-controls" onSubmit={(event) => event.preventDefault()}>
              <label className="search-control">
                <span className="sr-only">Поиск объявлений</span>
                <span aria-hidden="true">⌕</span>
                <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Поиск коллекционных предметов" />
              </label>
              <label className="select-control">
                <span className="sr-only">Тип актива</span>
                <select value={assetType} onChange={(event) => setAssetType(event.target.value as AssetType | "all")}>
                  <option value="all">Все активы</option>
                  <option value="ton_nft">TON NFT</option>
                  <option value="telegram_gift">Подарок Telegram</option>
                </select>
              </label>
              <label className="select-control">
                <span className="sr-only">Валюта</span>
                <select
                  aria-label="Валюта"
                  value={currency}
                  onChange={(event) => {
                    const value = event.target.value as PriceCurrency | "all";
                    setCurrency(value);
                    if (value === "all") {
                      setSort("newest");
                      setMinPrice("");
                      setMaxPrice("");
                    }
                  }}
                >
                  <option value="all">Все валюты</option>
                  <option value="TON">TON</option>
                  <option value="XTR">Звёзды (XTR)</option>
                </select>
              </label>
              <label className="price-control">
                <span className="sr-only">Минимальная цена</span>
                <input aria-label="Минимальная цена" type="number" min="0.000000001" step="0.000000001" placeholder="Мин. цена" disabled={currency === "all"} value={minPrice} onChange={(event) => setMinPrice(event.target.value)} />
              </label>
              <label className="price-control">
                <span className="sr-only">Максимальная цена</span>
                <input aria-label="Максимальная цена" type="number" min="0.000000001" step="0.000000001" placeholder="Макс. цена" disabled={currency === "all"} value={maxPrice} onChange={(event) => setMaxPrice(event.target.value)} />
              </label>
              <label className="select-control">
                <span className="sr-only">Сортировка объявлений</span>
                <select
                  value={sort}
                  onChange={(event) => setSort(event.target.value as ListingSort)}
                >
                  <option value="newest">Сначала новые</option>
                  <option value="price_asc" disabled={currency === "all"}>Сначала дешевле</option>
                  <option value="price_desc" disabled={currency === "all"}>Сначала дороже</option>
                </select>
              </label>
              {(search || assetType !== "all" || currency !== "all" || minPrice || maxPrice || sort !== "newest") && (
                <button
                  className="clear-filters-button"
                  type="button"
                  onClick={() => {
                    setSearch("");
                    setAssetType("all");
                    setCurrency("all");
                    setMinPrice("");
                    setMaxPrice("");
                    setSort("newest");
                  }}
                >
                  Сбросить фильтры
                </button>
              )}
            </form>
            {(minPrice || maxPrice) && currency === "all" && (
              <p className="filter-hint" role="status">Выберите TON или Звёзды, чтобы задать диапазон цены.</p>
            )}
            {currency === "all" && sort !== "newest" && (
              <p className="filter-hint" role="status">Выберите валюту, чтобы корректно сравнить цены.</p>
            )}

            {loading ? (
              <div className="listing-grid" aria-label="Загружаем объявления…" aria-busy="true">
                {Array.from({ length: 8 }, (_, index) => (
                  <div className="listing-skeleton" key={index} aria-hidden="true"><span /><i /><i /></div>
                ))}
              </div>
            ) : error ? (
              <div className="catalog-message" role="alert">
                <h3>Каталог недоступен</h3><p>{error}</p>
                <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Повторить</button>
              </div>
            ) : listings.length === 0 ? (
              <div className="catalog-message" role="status">
                <h3>Объявления не найдены</h3><p>Измените поисковый запрос или тип актива.</p>
              </div>
            ) : (
              <>
                <div className="listing-grid">
                  {listings.map((listing) => (
                    <ListingCard key={listing.id} listing={listing} onOpen={() => setListingId(listing.id)} />
                  ))}
                </div>
                {(hasMore || loadingMore || loadMoreError) && (
                  <div className="catalog-pagination">
                    <p className="pagination-count" role="status">Показано {listings.length} из {total}</p>
                    {loadMoreError && <p className="pagination-error" role="alert">{loadMoreError}</p>}
                    <button className="load-more-button" type="button" onClick={loadMore} disabled={loadingMore || !hasMore}>
                      {loadingMore ? "Загружаем ещё…" : loadMoreError ? "Повторить загрузку" : "Загрузить ещё"}
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        </>
      )}
      <footer>VILTARA SHOP <span>·</span> Работает на TON</footer>
    </main>
  );
}
