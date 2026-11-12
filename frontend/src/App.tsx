import { useEffect, useRef, useState } from "react";
import {
  fetchListing,
  fetchListings,
  type AssetType,
  type Listing,
  type ListingSort,
} from "./api/listings";
import { createOrder } from "./api/orders";
import { SessionProvider, useRetrySession, useSession } from "./auth/SessionProvider";
import { getTelegramStartParam } from "./auth/telegram";
import { MyListings } from "./listings/MyListings";
import { MyInventory } from "./inventory/MyInventory";
import { Orders } from "./orders/Orders";
import { WalletConnection } from "./wallet/WalletConnection";

const assetTypeLabels: Record<AssetType, string> = {
  ton_nft: "TON NFT",
  telegram_gift: "Telegram gift",
};
const CATALOG_PAGE_SIZE = 24;

function formatPrice(amount: string, currency: string) {
  const numericAmount = Number(amount);
  const formattedAmount = Number.isFinite(numericAmount)
    ? new Intl.NumberFormat("en-US", { maximumFractionDigits: 4 }).format(numericAmount)
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
        <div className="artwork-placeholder" aria-label="Image unavailable"><span>V</span></div>
      )}
    </div>
  );
}

function ListingCard({ listing, onOpen }: { listing: Listing; onOpen: () => void }) {
  const title = listing.title || listing.asset.name || "Untitled asset";
  return (
    <button className="listing-card" type="button" onClick={onOpen}>
      <AssetArtwork imageUrl={listing.asset.image_url} name={title} />
      <span className="listing-card-content">
        <span className="listing-card-type">{assetTypeLabels[listing.asset.asset_type]}</span>
        <span className="listing-card-title">{title}</span>
        <span className="listing-card-price">{formatPrice(listing.price_amount, listing.price_currency)}</span>
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
          setError(reason instanceof Error ? reason.message : "Unable to load this listing.");
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

  if (loading) return <p className="detail-message" role="status">Loading listing...</p>;
  if (error || !listing) {
    return (
      <section className="detail-message" role="alert">
        <p>{error || "This listing is unavailable."}</p>
        <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Try again</button>
      </section>
    );
  }

  const title = listing.title || listing.asset.name || "Untitled asset";
  const seller = listing.seller.first_name || listing.seller.username || "Seller";
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
      setOrderError(reason instanceof Error ? reason.message : "Unable to create this reservation. Please retry.");
    } finally {
      submittingRef.current = false;
      setOrdering(false);
    }
  }

  return (
    <section className="detail-view" aria-labelledby="detail-title">
      <button className="text-button back-button" type="button" onClick={onBack}>
        <span aria-hidden="true">←</span> Back to catalog
      </button>
      <div className="detail-layout">
        <AssetArtwork imageUrl={listing.asset.image_url} name={title} />
        <div className="detail-copy">
          <p className="eyebrow">{assetTypeLabels[listing.asset.asset_type]}</p>
          <h1 id="detail-title">{title}</h1>
          <p className="detail-price">{formatPrice(listing.price_amount, listing.price_currency)}</p>
          <section className="seller-profile" aria-label="Seller profile">
            <div className="seller-profile-avatar" aria-hidden="true">
              {(seller.trim().charAt(0) || "S").toUpperCase()}
            </div>
            <div className="seller-profile-copy">
              <strong>{seller}</strong>
              <span>{listing.seller.username ? `@${listing.seller.username}` : "Telegram seller"}</span>
            </div>
          </section>
          {canOrder ? (
            <div className="order-action">
              <button ref={reserveTriggerRef} className="primary-button" type="button" disabled={ordering || orderCreated} onClick={() => { setOrderError(""); setConfirmationOpen(true); }}>
                {ordering ? "Reserving listing..." : orderCreated ? "Reservation created" : "Place order"}
              </button>
              {orderError && !confirmationOpen && <p role="alert">{orderError}</p>}
              {orderCreated && (
                <div className="reservation-success" role="status">
                  <p>Reservation created for {title}. Payment is not enabled and no funds were collected. No NFT transfer has happened.</p>
                  <button className="primary-button" type="button" onClick={onOrders}>View Orders</button>
                </div>
              )}
            </div>
          ) : session.status === "authenticated" ? (
            <p className="detail-description">You cannot order your own listing.</p>
          ) : (
            <p className="detail-description">Open this Mini App in Telegram to sign in and place an order.</p>
          )}
          {confirmationOpen && (
            <div className="reservation-dialog-backdrop">
              <section ref={dialogRef} className="reservation-dialog" role="dialog" aria-modal="true" aria-labelledby="reservation-dialog-title" aria-describedby="reservation-dialog-description">
                {orderCreated ? (
                  <>
                    <p className="eyebrow">RESERVATION CREATED</p>
                    <h2 id="reservation-dialog-title">Reservation confirmed</h2>
                    <p id="reservation-dialog-description">The order reservation was created for {title}. Payment is not enabled, no funds were collected, and no NFT transfer has happened.</p>
                    <button className="primary-button" type="button" onClick={onOrders}>View Orders</button>
                  </>
                ) : (
                  <>
                    <p className="eyebrow">REVIEW RESERVATION</p>
                    <h2 id="reservation-dialog-title">Reserve this listing?</h2>
                    <dl className="reservation-summary">
                      <div><dt>Listing</dt><dd>{title}</dd></div>
                      <div><dt>Price</dt><dd>{formatPrice(listing.price_amount, listing.price_currency)}</dd></div>
                      <div><dt>Seller</dt><dd>{seller}{listing.seller.username ? ` (@${listing.seller.username})` : ""}</dd></div>
                    </dl>
                    <p id="reservation-dialog-description" className="reservation-disclaimer">This creates a reservation/order only. Payment is not enabled and no funds will be collected. No NFT transfer happens as part of this action.</p>
                    {orderError && <p className="reservation-error" role="alert">{orderError} Your reservation request may have reached the server; retrying uses the same idempotency key.</p>}
                    <div className="reservation-dialog-actions">
                      <button className="text-button" type="button" disabled={ordering} onClick={() => { setConfirmationOpen(false); setOrderError(""); window.setTimeout(() => reserveTriggerRef.current?.focus(), 0); }}>Cancel</button>
                      <button ref={confirmButtonRef} className="primary-button" type="button" disabled={ordering} onClick={() => void handleOrder()}>{ordering ? "Creating reservation…" : "Confirm reservation"}</button>
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
              <dt>Collection</dt>
              <dd>{listing.asset.collection?.name ?? "Uncollected NFT"}</dd>
            </div>
            <div>
              <dt>Item address</dt>
              <dd>
                <code className="mono">{listing.asset.item_address ?? "Not available"}</code>
              </dd>
            </div>
            <div><dt>Asset ID</dt><dd>{listing.asset.external_id}</dd></div>
            <div><dt>Verification</dt><dd>{listing.asset.verification_status}</dd></div>
          </dl>
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
    return <p className="session-banner" role="status">Checking Telegram session...</p>;
  }
  if (session.status === "authenticated") {
    const name = [session.user.first_name, session.user.last_name].filter(Boolean).join(" ");
    const username = session.user.username ? ` · @${session.user.username}` : "";
    return <p className="session-banner session-authenticated" role="status">Signed in as {name || session.user.username}{username}</p>;
  }
  if (session.status === "error") {
    return (
      <div className="session-banner session-error" role="alert">
        <span>{session.message}</span>
        {session.retryable && (
          <button className="text-button" type="button" onClick={retrySession}>
            Retry session
          </button>
        )}
      </div>
    );
  }
  return (
    <p className="session-banner" role="status">
      {session.reason === "missing_init_data"
        ? "Open this mini app in Telegram to sign in. The public catalog is available."
        : "Telegram session could not be verified. Reopen this mini app in Telegram."}
    </p>
  );
}

function MarketplaceApp() {
  const session = useSession();
  const startParam = useRef(getTelegramStartParam()).current;
  const [initialOrderId, setInitialOrderId] = useState<string | null>(null);
  const [section, setSection] = useState<"catalog" | "my-listings" | "my-nft" | "orders">("catalog");
  const [listings, setListings] = useState<Listing[]>([]);
  const [total, setTotal] = useState(0);
  const [search, setSearch] = useState("");
  const [assetType, setAssetType] = useState<AssetType | "all">("all");
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
    fetchListings({ search, assetType, sort, limit: CATALOG_PAGE_SIZE, offset: 0 }, controller.signal)
      .then((page) => {
        if (controller.signal.aborted || version !== requestVersion.current) return;
        setListings(page.items);
        setTotal(page.total);
        setNextOffset(page.offset + page.items.length);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted && version === requestVersion.current) {
          setError(reason instanceof Error ? reason.message : "Unable to load the catalog.");
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
  }, [search, assetType, sort, retry]);

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
        { search, assetType, sort, limit: CATALOG_PAGE_SIZE, offset: nextOffset },
        controller.signal,
      );
      if (controller.signal.aborted || version !== requestVersion.current) return;
      if (page.items.length === 0 && page.offset < page.total) {
        setLoadMoreError("No new listings were returned. Please try again.");
        return;
      }
      setListings((current) => appendUniqueListings(current, page.items));
      setTotal(page.total);
      setNextOffset(page.offset + page.items.length);
    } catch (reason) {
      if (!controller.signal.aborted && version === requestVersion.current) {
        setLoadMoreError(reason instanceof Error ? reason.message : "Unable to load more listings.");
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
          <span className="network-label">TON MARKET</span>
          <WalletConnection accessToken={session.status === "authenticated" ? session.accessToken : null} />
        </div>
      </header>
      <SessionBanner />
      <nav className="app-navigation" aria-label="Marketplace sections">
        <button
          className="navigation-tab"
          type="button"
          aria-pressed={section === "catalog"}
          onClick={() => {
            setListingId(null);
            setSection("catalog");
          }}
        >
          Catalog
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
          My NFT
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
          My Listings
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
          Orders
        </button>
      </nav>

      {section === "orders" ? (
        session.status === "authenticated" ? (
          <Orders accessToken={session.accessToken} userId={session.user.id} initialOrderId={initialOrderId} onCatalog={() => setSection("catalog")} />
        ) : (
          <div className="orders-message" role="status">
            <h2>Sign in to view orders</h2>
            <p>Order history is private and requires a verified Telegram session.</p>
          </div>
        )
      ) : section === "my-listings" ? (
        <MyListings />
      ) : section === "my-nft" ? (
        session.status === "authenticated" ? (
          <MyInventory accessToken={session.accessToken} />
        ) : (
          <div className="inventory-message" role="status">
            <h2>Sign in to view your inventory</h2>
            <p>Your NFT inventory requires a verified Telegram session and a TON wallet confirmed by backend proof.</p>
          </div>
        )
      ) : listingId ? (
        <ListingDetail listingId={listingId} onBack={() => setListingId(null)} onOrders={() => { setListingId(null); setInitialOrderId(null); setSection("orders"); }} />
      ) : (
        <>
          <section className="catalog-intro" id="catalog">
            <p className="eyebrow">DIGITAL COLLECTIBLES · TON</p>
            <h1>Find your next<br /><span>favorite thing.</span></h1>
            <p className="intro-copy">A live catalog of listed digital collectibles.</p>
          </section>
          <section className="catalog" aria-label="Marketplace catalog">
            <div className="catalog-heading">
              <h2>Explore listings</h2>
              {!loading && !error && <span className="result-count">{total} {total === 1 ? "item" : "items"}</span>}
            </div>
            <form className="catalog-controls" onSubmit={(event) => event.preventDefault()}>
              <label className="search-control">
                <span className="sr-only">Search listings</span>
                <span aria-hidden="true">⌕</span>
                <input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search collectibles" />
              </label>
              <label className="select-control">
                <span className="sr-only">Asset type</span>
                <select value={assetType} onChange={(event) => setAssetType(event.target.value as AssetType | "all")}>
                  <option value="all">All assets</option>
                  <option value="ton_nft">TON NFT</option>
                  <option value="telegram_gift">Telegram gift</option>
                </select>
              </label>
              <label className="select-control">
                <span className="sr-only">Sort listings</span>
                <select value={sort} onChange={(event) => setSort(event.target.value as ListingSort)}>
                  <option value="newest">Newest</option>
                  <option value="price_asc">Price: low to high</option>
                  <option value="price_desc">Price: high to low</option>
                </select>
              </label>
            </form>

            {loading ? (
              <div className="listing-grid" aria-label="Listings loading" aria-busy="true">
                {Array.from({ length: 8 }, (_, index) => (
                  <div className="listing-skeleton" key={index} aria-hidden="true"><span /><i /><i /></div>
                ))}
              </div>
            ) : error ? (
              <div className="catalog-message" role="alert">
                <h3>Catalog unavailable</h3><p>{error}</p>
                <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Try again</button>
              </div>
            ) : listings.length === 0 ? (
              <div className="catalog-message" role="status">
                <h3>No listings found</h3><p>Try changing your search or asset type.</p>
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
                    <p className="pagination-count" role="status">Showing {listings.length} of {total}</p>
                    {loadMoreError && <p className="pagination-error" role="alert">{loadMoreError}</p>}
                    <button className="load-more-button" type="button" onClick={loadMore} disabled={loadingMore || !hasMore}>
                      {loadingMore ? "Loading more..." : loadMoreError ? "Retry loading more" : "Load more"}
                    </button>
                  </div>
                )}
              </>
            )}
          </section>
        </>
      )}
      <footer>VILTARA SHOP <span>·</span> Built on TON</footer>
    </main>
  );
}
