import { useEffect, useRef, useState } from "react";
import {
  fetchListing,
  fetchListings,
  type AssetType,
  type Listing,
  type ListingSort,
} from "./api/listings";
import { SessionProvider, useSession } from "./auth/SessionProvider";
import { MyListings } from "./listings/MyListings";
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

function ListingDetail({ listingId, onBack }: { listingId: string; onBack: () => void }) {
  const [listing, setListing] = useState<Listing | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

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
          {listing.description && <p className="detail-description">{listing.description}</p>}
          {listing.asset.description && <p className="detail-description">{listing.asset.description}</p>}
          <dl className="detail-facts">
            <div><dt>Seller</dt><dd>{seller}</dd></div>
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
  if (session.status === "loading") {
    return <p className="session-banner" role="status">Checking Telegram session...</p>;
  }
  if (session.status === "authenticated") {
    const name = [session.user.first_name, session.user.last_name].filter(Boolean).join(" ");
    const username = session.user.username ? ` · @${session.user.username}` : "";
    return <p className="session-banner session-authenticated" role="status">Signed in as {name || session.user.username}{username}</p>;
  }
  if (session.status === "error") {
    return <p className="session-banner session-error" role="alert">{session.message}</p>;
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
  const [section, setSection] = useState<"catalog" | "my-listings">("catalog");
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
        <a className="brand" href="#catalog" onClick={() => setListingId(null)}>
          <span className="brand-mark" aria-hidden="true">V</span>
          <span className="brand-name">VILTARA</span>
        </a>
        <div className="header-actions">
          <span className="network-label">TON MARKET</span>
          <WalletConnection />
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
          aria-pressed={section === "my-listings"}
          onClick={() => {
            setListingId(null);
            setSection("my-listings");
          }}
        >
          My Listings
        </button>
      </nav>

      {section === "my-listings" ? (
        <MyListings />
      ) : listingId ? (
        <ListingDetail listingId={listingId} onBack={() => setListingId(null)} />
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
