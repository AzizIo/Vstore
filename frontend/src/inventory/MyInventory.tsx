import { useEffect, useRef, useState } from "react";

import {
  fetchMyInventory,
  syncMyInventory,
  type InventoryAsset,
  type InventorySyncResponse,
} from "../api/assets";

const PAGE_SIZE = 24;

function safeImageUrl(value: string | null) {
  if (!value) return null;
  try {
    const url = new URL(value);
    if (url.protocol !== "https:" || !url.hostname || url.username || url.password) return null;
    return url.toString();
  } catch {
    return null;
  }
}

function mergeUniqueAssets(current: InventoryAsset[], incoming: InventoryAsset[]) {
  const known = new Set(current.map((asset) => asset.id));
  const merged = [...current];
  for (const asset of incoming) {
    if (!known.has(asset.id)) {
      known.add(asset.id);
      merged.push(asset);
    }
  }
  return merged;
}

function InventoryArtwork({ asset }: { asset: InventoryAsset }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [asset.image_url]);
  const imageUrl = safeImageUrl(asset.image_url);

  return (
    <div className="inventory-artwork">
      {imageUrl && !failed ? (
        <img
          src={imageUrl}
          alt=""
          loading="lazy"
          referrerPolicy="no-referrer"
          onError={() => setFailed(true)}
        />
      ) : (
        <span aria-hidden="true">V</span>
      )}
    </div>
  );
}

export function MyInventory({ accessToken }: { accessToken: string }) {
  const [initialLoadRetry, setInitialLoadRetry] = useState(0);
  const [assets, setAssets] = useState<InventoryAsset[]>([]);
  const [walletId, setWalletId] = useState<string | null>(null);
  const [nextOffset, setNextOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [syncResult, setSyncResult] = useState<InventorySyncResponse | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");
  const loadMoreRef = useRef<AbortController | null>(null);
  const activeControllerRef = useRef<AbortController | null>(null);
  const requestVersion = useRef(0);
  const loadingMoreFlag = useRef(false);

  useEffect(() => {
    const version = ++requestVersion.current;
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setLoadMoreError("");
    setAssets([]);
    setWalletId(null);
    setNextOffset(0);
    setHasMore(false);
    setSyncResult(null);
    setLoadingMore(false);
    loadingMoreFlag.current = false;
    loadMoreRef.current?.abort();
    loadMoreRef.current = null;

    fetchMyInventory(
      accessToken,
      { limit: PAGE_SIZE, offset: 0 },
      controller.signal,
    )
      .then((page) => {
        if (controller.signal.aborted || version !== requestVersion.current) return;
        setAssets(page.items);
        setWalletId(page.wallet_id);
        setNextOffset(page.next_offset);
        setHasMore(page.has_more);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted && version === requestVersion.current) {
          setError(reason instanceof Error ? reason.message : "Unable to load your NFT inventory.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted && version === requestVersion.current) {
          setLoading(false);
        }
      });

    return () => {
      controller.abort();
      activeControllerRef.current?.abort();
      loadMoreRef.current?.abort();
      loadMoreRef.current = null;
      loadingMoreFlag.current = false;
    };
  }, [accessToken, initialLoadRetry]);

  async function runSync() {
    if (loading || loadingMoreFlag.current) return;
    const version = ++requestVersion.current;
    const controller = new AbortController();
    activeControllerRef.current?.abort();
    activeControllerRef.current = controller;
    loadMoreRef.current?.abort();
    loadMoreRef.current = null;
    loadingMoreFlag.current = false;
    setLoading(true);
    setLoadingMore(false);
    setError("");
    setLoadMoreError("");
    setAssets([]);
    setSyncResult(null);
    setNextOffset(0);
    setHasMore(false);

    try {
      const sync = await syncMyInventory(accessToken, walletId ?? undefined, controller.signal);
      if (controller.signal.aborted || version !== requestVersion.current) return;
      setSyncResult(sync);
      const page = await fetchMyInventory(
        accessToken,
        { limit: PAGE_SIZE, offset: 0, walletId: sync.wallet_id },
        controller.signal,
      );
      if (controller.signal.aborted || version !== requestVersion.current) return;
      setAssets(page.items);
      setWalletId(page.wallet_id);
      setNextOffset(page.next_offset);
      setHasMore(page.has_more);
    } catch (reason) {
      if (!controller.signal.aborted && version === requestVersion.current) {
        setError(reason instanceof Error ? reason.message : "Unable to sync your NFT inventory.");
      }
    } finally {
      if (!controller.signal.aborted && version === requestVersion.current) {
        activeControllerRef.current = null;
        setLoading(false);
      }
    }
  }

  async function loadMore() {
    if (!hasMore || loading || loadingMoreFlag.current || !walletId) return;
    const version = requestVersion.current;
    const controller = new AbortController();
    loadMoreRef.current = controller;
    loadingMoreFlag.current = true;
    setLoadingMore(true);
    setLoadMoreError("");
    try {
      const page = await fetchMyInventory(
        accessToken,
        { limit: PAGE_SIZE, offset: nextOffset, walletId },
        controller.signal,
      );
      if (controller.signal.aborted || version !== requestVersion.current) return;
      const merged = mergeUniqueAssets(assets, page.items);
      if (merged.length === assets.length && page.has_more && page.next_offset <= nextOffset) {
        throw new Error("The inventory page did not advance. Please refresh and try again.");
      }
      setAssets(merged);
      setNextOffset(page.next_offset);
      setHasMore(page.has_more);
    } catch (reason) {
      if (!controller.signal.aborted && version === requestVersion.current) {
        setLoadMoreError(reason instanceof Error ? reason.message : "Unable to load more NFTs.");
      }
    } finally {
      if (!controller.signal.aborted && version === requestVersion.current) {
        loadingMoreFlag.current = false;
        loadMoreRef.current = null;
        setLoadingMore(false);
      }
    }
  }

  return (
    <section className="inventory-view" aria-labelledby="inventory-title">
      <div className="inventory-heading">
        <div>
          <p className="eyebrow">COLLECTOR SPACE</p>
          <h1 id="inventory-title">My NFT inventory</h1>
          <p className="inventory-intro">
            NFTs are shown only after the backend rechecks current on-chain ownership.
          </p>
        </div>
        <button
          className="text-button"
          type="button"
          onClick={() => void runSync()}
          disabled={loading || loadingMore}
        >
          {loading ? "Loading..." : "Sync inventory"}
        </button>
      </div>

      {syncResult && !loading && !error && (
        <p className="inventory-sync-summary" role="status">
          Last synced {new Date(syncResult.synced_at).toLocaleString()} · {syncResult.verified_count} verified
          {syncResult.stale_count > 0 ? ` · ${syncResult.stale_count} marked stale` : ""}
          {syncResult.invalid_count > 0 ? ` · ${syncResult.invalid_count} could not be verified` : ""}
          {syncResult.unsupported_count > 0 ? ` · ${syncResult.unsupported_count} unsupported` : ""}
        </p>
      )}

      {loading ? (
        <div className="inventory-message" role="status" aria-busy="true">
          Syncing your verified wallets and checking NFT ownership...
        </div>
      ) : error ? (
        <div className="inventory-message" role="alert">
          <h2>Inventory unavailable</h2>
          <p>{error}</p>
          {/verified TON wallet/i.test(error) ? (
            <p>Connect and verify a TON wallet first. Connecting a wallet alone does not verify ownership.</p>
          ) : null}
          <button className="text-button" type="button" onClick={() => setInitialLoadRetry((value) => value + 1)}>
            Try again
          </button>
        </div>
      ) : assets.length === 0 ? (
        <div className="inventory-message" role="status">
          <h2>No verified NFTs found</h2>
          <p>This wallet returned no assets that could be confirmed as currently owned by you.</p>
        </div>
      ) : (
        <>
          <div className="inventory-grid" aria-label="My verified NFTs">
            {assets.map((asset) => (
              <article className="inventory-card" key={asset.id}>
                <InventoryArtwork asset={asset} />
                <div className="inventory-card-copy">
                  <div className="inventory-card-heading">
                    <p className="inventory-card-type">TON NFT · verified</p>
                    <span className="inventory-verified">Verified</span>
                  </div>
                  <h2>{asset.name || "Untitled TON NFT"}</h2>
                  {asset.collection_address && (
                    <p className="inventory-collection">
                      <span>Collection</span>
                      <code>{asset.collection_address}</code>
                    </p>
                  )}
                  <p className="inventory-address">
                    <span>Item address</span>
                    <code>{asset.item_address}</code>
                  </p>
                  <p className="inventory-card-note">Current owner checked on-chain. Eligible for draft listing.</p>
                </div>
              </article>
            ))}
          </div>

          {(hasMore || loadingMore || loadMoreError) && (
            <div className="inventory-pagination">
              {loadMoreError && <p role="alert">{loadMoreError}</p>}
              <button
                className="load-more-button"
                type="button"
                onClick={() => void loadMore()}
                disabled={loadingMore || !hasMore}
              >
                {loadingMore ? "Loading more..." : loadMoreError ? "Retry loading more" : "Load more NFTs"}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
