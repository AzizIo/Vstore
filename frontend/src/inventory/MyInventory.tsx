import { useEffect, useRef, useState } from "react";

import {
  fetchMyInventory,
  syncMyInventory,
  type InventoryAsset,
  type InventorySyncResponse,
} from "../api/assets";
import type { WalletRecord } from "../wallet/api";

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

export function MyInventory({
  accessToken,
  selectedWallet,
}: {
  accessToken: string;
  selectedWallet: WalletRecord | null;
}) {
  const [initialLoadRetry, setInitialLoadRetry] = useState(0);
  const [assets, setAssets] = useState<InventoryAsset[]>([]);
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

  const selectedWalletId = selectedWallet?.id ?? null;
  const selectedWalletNetwork = selectedWallet?.network ?? null;
  const selectedWalletAddress = selectedWallet?.address ?? null;

  useEffect(() => {
    const version = ++requestVersion.current;
    const controller = new AbortController();

    activeControllerRef.current?.abort();
    activeControllerRef.current = null;
    loadMoreRef.current?.abort();
    loadMoreRef.current = null;
    loadingMoreFlag.current = false;
    setLoadingMore(false);
    setError("");
    setLoadMoreError("");
    setAssets([]);
    setNextOffset(0);
    setHasMore(false);
    setSyncResult(null);

    if (!selectedWalletId) {
      setLoading(false);
      return () => controller.abort();
    }

    setLoading(true);
    fetchMyInventory(
      accessToken,
      { limit: PAGE_SIZE, offset: 0, walletId: selectedWalletId },
      controller.signal,
    )
      .then((page) => {
        if (controller.signal.aborted || version !== requestVersion.current) return;
        setAssets(page.items);
        setNextOffset(page.next_offset);
        setHasMore(page.has_more);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted && version === requestVersion.current) {
          setError(reason instanceof Error ? reason.message : "Не удалось загрузить инвентарь NFT.");
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
      activeControllerRef.current = null;
      loadMoreRef.current?.abort();
      loadMoreRef.current = null;
      loadingMoreFlag.current = false;
    };
  }, [
    accessToken,
    initialLoadRetry,
    selectedWalletId,
    selectedWalletNetwork,
    selectedWalletAddress,
  ]);

  async function runSync() {
    if (loading || loadingMoreFlag.current || !selectedWalletId) return;
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
      const sync = await syncMyInventory(accessToken, selectedWalletId, controller.signal);
      if (controller.signal.aborted || version !== requestVersion.current) return;
      if (sync.wallet_id !== selectedWalletId) {
        throw new Error("Синхронизация вернула данные другого кошелька.");
      }
      setSyncResult(sync);
      const page = await fetchMyInventory(
        accessToken,
        { limit: PAGE_SIZE, offset: 0, walletId: selectedWalletId },
        controller.signal,
      );
      if (controller.signal.aborted || version !== requestVersion.current) return;
      setAssets(page.items);
      setNextOffset(page.next_offset);
      setHasMore(page.has_more);
    } catch (reason) {
      if (!controller.signal.aborted && version === requestVersion.current) {
        setError(reason instanceof Error ? reason.message : "Не удалось синхронизировать инвентарь NFT.");
      }
    } finally {
      if (!controller.signal.aborted && version === requestVersion.current) {
        activeControllerRef.current = null;
        setLoading(false);
      }
    }
  }

  async function loadMore() {
    if (!hasMore || loading || loadingMoreFlag.current || !selectedWalletId) return;
    const version = requestVersion.current;
    const controller = new AbortController();
    loadMoreRef.current = controller;
    loadingMoreFlag.current = true;
    setLoadingMore(true);
    setLoadMoreError("");
    try {
      const page = await fetchMyInventory(
        accessToken,
        { limit: PAGE_SIZE, offset: nextOffset, walletId: selectedWalletId },
        controller.signal,
      );
      if (controller.signal.aborted || version !== requestVersion.current) return;
      const merged = mergeUniqueAssets(assets, page.items);
      if (merged.length === assets.length && page.has_more && page.next_offset <= nextOffset) {
        throw new Error("Не удалось перейти к следующей странице. Обновите страницу и попробуйте снова.");
      }
      setAssets(merged);
      setNextOffset(page.next_offset);
      setHasMore(page.has_more);
    } catch (reason) {
      if (!controller.signal.aborted && version === requestVersion.current) {
        setLoadMoreError(reason instanceof Error ? reason.message : "Не удалось загрузить остальные NFT.");
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
          <p className="eyebrow">КОЛЛЕКЦИОНЕР</p>
          <h1 id="inventory-title">Мои NFT</h1>
          <p className="inventory-intro">
            {selectedWallet ? (
              <>
                Showing verified NFTs for {selectedWallet.address.slice(0, 8)}…
                {selectedWallet.address.slice(-5)} · {selectedWallet.network}
              </>
            ) : (
              "Подключите и подтвердите TON-кошелёк, чтобы посмотреть его NFT. Другой основной кошелёк автоматически выбран не будет."
            )}
          </p>
        </div>
        <button
          className="text-button"
          type="button"
          onClick={() => void runSync()}
          disabled={loading || loadingMore || !selectedWalletId}
        >
          {loading ? "Загрузка…" : "Синхронизировать инвентарь"}
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
          Checking the selected verified wallet and its NFT ownership...
        </div>
      ) : !selectedWallet ? (
        <div className="inventory-message" role="status">
          <h2>Подключить и подтвердить кошелёк</h2>
          <p>Подключите нужный кошелёк и подтвердите владение через TON Proof. Другой основной кошелёк автоматически выбран не будет.</p>
        </div>
      ) : error ? (
        <div className="inventory-message" role="alert">
          <h2>Инвентарь недоступен</h2>
          <p>{error}</p>
          {/verified TON wallet/i.test(error) ? (
            <p>Сначала подключите и подтвердите TON-кошелёк. Одного подключения недостаточно для подтверждения владения.</p>
          ) : null}
          <button className="text-button" type="button" onClick={() => setInitialLoadRetry((value) => value + 1)}>
            Try again
          </button>
        </div>
      ) : assets.length === 0 ? (
        <div className="inventory-message" role="status">
          {hasMore ? (
            <>
              <h2>На этой странице нет подтверждённых NFT</h2>
              <p>
                None of the items on this page could be confirmed as currently owned by you.
                More inventory pages are available and may contain verified NFTs.
              </p>
              {loadMoreError && <p role="alert">{loadMoreError}</p>}
              <button
                className="load-more-button"
                type="button"
                onClick={() => void loadMore()}
                disabled={loading || loadingMore || !hasMore}
              >
                {loadingMore ? "Загружаем ещё…" : loadMoreError ? "Повторить загрузку" : "Загрузить ещё NFT"}
              </button>
            </>
          ) : (
            <>
              <h2>Подтверждённые NFT не найдены</h2>
              <p>В этом кошельке не найдено активов, владение которыми удалось подтвердить.</p>
            </>
          )}
        </div>
      ) : (
        <>
          <div className="inventory-grid" aria-label="Мои подтверждённые NFT">
            {assets.map((asset) => (
              <article className="inventory-card" key={asset.id}>
                <InventoryArtwork asset={asset} />
                <div className="inventory-card-copy">
                  <div className="inventory-card-heading">
                    <p className="inventory-card-type">TON NFT · подтверждён</p>
                    <span className="inventory-verified">Подтверждён</span>
                  </div>
                  <h2>{asset.name || "TON NFT без названия"}</h2>
                  {asset.collection_address && (
                    <p className="inventory-collection">
                      <span>Коллекция</span>
                      <code>{asset.collection_address}</code>
                    </p>
                  )}
                  <p className="inventory-address">
                    <span>Адрес NFT</span>
                    <code>{asset.item_address}</code>
                  </p>
                  <p className="inventory-card-note">Владелец проверен в блокчейне. NFT можно добавить в черновик объявления.</p>
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
                disabled={loading || loadingMore || !hasMore}
              >
                {loadingMore ? "Загружаем ещё…" : loadMoreError ? "Повторить загрузку" : "Загрузить ещё NFT"}
              </button>
            </div>
          )}
        </>
      )}
    </section>
  );
}
