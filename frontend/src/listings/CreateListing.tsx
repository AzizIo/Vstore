import { useEffect, useRef, useState } from "react";

import { createListingDraft, fetchMyInventory, type InventoryAsset } from "../api/assets";
import type { Listing, PriceCurrency } from "../api/listings";

const PAGE_SIZE = 24;

function localDateTimeMinimum() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

function assetTitle(asset: InventoryAsset) {
  return asset.name || "TON NFT без названия";
}

function InventoryImage({ asset }: { asset: InventoryAsset }) {
  const [failed, setFailed] = useState(false);
  useEffect(() => setFailed(false), [asset.image_url]);

  return (
    <span className="inventory-image">
      {asset.image_url && !failed ? (
        <img src={asset.image_url} alt="" loading="lazy" onError={() => setFailed(true)} />
      ) : (
        <span aria-hidden="true">V</span>
      )}
    </span>
  );
}

function appendUniqueAssets(current: InventoryAsset[], incoming: InventoryAsset[]) {
  const seen = new Set(current.map((asset) => asset.id));
  const merged = [...current];
  for (const asset of incoming) {
    if (!seen.has(asset.id)) {
      seen.add(asset.id);
      merged.push(asset);
    }
  }
  return merged;
}

export function CreateListing({
  accessToken,
  onCancel,
  onDraftCreated,
}: {
  accessToken: string;
  onCancel: () => void;
  onDraftCreated: (listing: Listing) => void;
}) {
  const [assets, setAssets] = useState<InventoryAsset[]>([]);
  const [walletId, setWalletId] = useState("");
  const [nextOffset, setNextOffset] = useState(0);
  const [hasMore, setHasMore] = useState(false);
  const [selectedAsset, setSelectedAsset] = useState<InventoryAsset | null>(null);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [loadMoreError, setLoadMoreError] = useState("");
  const [retry, setRetry] = useState(0);
  const [priceAmount, setPriceAmount] = useState("");
  const [priceCurrency, setPriceCurrency] = useState<PriceCurrency>("TON");
  const [title, setTitle] = useState("");
  const [description, setDescription] = useState("");
  const [expiresAt, setExpiresAt] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [submitError, setSubmitError] = useState("");
  const [createdListing, setCreatedListing] = useState<Listing | null>(null);
  const loadingMoreRef = useRef(false);
  const nextPageController = useRef<AbortController | null>(null);
  const submitController = useRef<AbortController | null>(null);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    setAssets([]);
    setNextOffset(0);
    setHasMore(false);
    void fetchMyInventory(accessToken, { limit: PAGE_SIZE, offset: 0 }, controller.signal)
      .then((page) => {
        if (controller.signal.aborted) return;
        setAssets(page.items);
        setWalletId(page.wallet_id);
        setNextOffset(page.next_offset);
        setHasMore(page.has_more);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Не удалось загрузить инвентарь подтверждённых NFT.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => {
      controller.abort();
      nextPageController.current?.abort();
      nextPageController.current = null;
      submitController.current?.abort();
      submitController.current = null;
      loadingMoreRef.current = false;
    };
  }, [accessToken, retry]);

  async function loadMore() {
    if (!hasMore || loadingMoreRef.current || !walletId) return;
    const controller = new AbortController();
    nextPageController.current = controller;
    loadingMoreRef.current = true;
    setLoadingMore(true);
    setLoadMoreError("");
    try {
      const page = await fetchMyInventory(
        accessToken,
        { limit: PAGE_SIZE, offset: nextOffset, walletId },
        controller.signal,
      );
      if (controller.signal.aborted) return;
      setAssets((current) => appendUniqueAssets(current, page.items));
      setNextOffset(page.next_offset);
      setHasMore(page.has_more);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setLoadMoreError(reason instanceof Error ? reason.message : "Не удалось загрузить остальные NFT.");
      }
    } finally {
      if (!controller.signal.aborted) {
        loadingMoreRef.current = false;
        nextPageController.current = null;
        setLoadingMore(false);
      }
    }
  }

  async function submitDraft(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selectedAsset || submitting) return;
    setSubmitting(true);
    setSubmitError("");
    const controller = new AbortController();
    submitController.current = controller;
    try {
      const draft = await createListingDraft(accessToken, {
        asset_id: selectedAsset.id,
        price_amount: priceAmount,
        price_currency: priceCurrency,
        ...(title.trim() ? { title: title.trim() } : {}),
        ...(description.trim() ? { description: description.trim() } : {}),
        ...(expiresAt ? { expires_at: new Date(expiresAt).toISOString() } : {}),
      }, controller.signal);
      if (controller.signal.aborted) return;
      setCreatedListing(draft);
      onDraftCreated(draft);
    } catch (reason) {
      if (!controller.signal.aborted) {
        setSubmitError(reason instanceof Error ? reason.message : "Не удалось создать черновик объявления.");
      }
    } finally {
      if (!controller.signal.aborted) {
        submitController.current = null;
        setSubmitting(false);
      }
    }
  }

  if (createdListing) {
    return (
      <section className="create-listing-view" aria-labelledby="create-listing-title">
        <p className="eyebrow">КАБИНЕТ ПРОДАВЦА</p>
        <h1 id="create-listing-title">Черновик создан</h1>
        <div className="creation-success" role="status">
          <span className="listing-status listing-status-draft">Черновик · не опубликован</span>
          <h2>{createdListing.title || createdListing.asset.name || "Объявление TON NFT"}</h2>
          <p>{createdListing.price_amount} {createdListing.price_currency}</p>
          <button className="text-button" type="button" onClick={onCancel}>К моим объявлениям</button>
        </div>
      </section>
    );
  }

  return (
    <section className="create-listing-view" aria-labelledby="create-listing-title">
      <button className="text-button back-button" type="button" onClick={selectedAsset ? () => setSelectedAsset(null) : onCancel}>
        <span aria-hidden="true">←</span> {selectedAsset ? "Назад в инвентарь" : "Назад к объявлениям"}
      </button>
      <p className="eyebrow">КАБИНЕТ ПРОДАВЦА</p>
      <h1 id="create-listing-title">Создать черновик объявления</h1>
      <p className="create-listing-note">Черновики видны только вам и не публикуются на площадке.</p>

      {selectedAsset ? (
        <form className="draft-form" onSubmit={submitDraft}>
          <div className="selected-inventory-asset">
            <InventoryImage asset={selectedAsset} />
            <span>{assetTitle(selectedAsset)}</span>
          </div>
          <label>
            <span>Цена</span>
            <span className="price-field">
              <input
                aria-label="Цена"
                type="number"
                min="0.000000001"
                step="0.000000001"
                required
                value={priceAmount}
                onChange={(event) => setPriceAmount(event.target.value)}
              />
              <select aria-label="Валюта" value={priceCurrency} onChange={(event) => setPriceCurrency(event.target.value as PriceCurrency)}>
                <option value="TON">TON</option>
                <option value="XTR">XTR</option>
              </select>
            </span>
          </label>
          <label>
            <span>Название <small>необязательно</small></span>
            <input maxLength={200} value={title} onChange={(event) => setTitle(event.target.value)} />
          </label>
          <label>
            <span>Описание <small>необязательно</small></span>
            <textarea maxLength={4000} rows={4} value={description} onChange={(event) => setDescription(event.target.value)} />
          </label>
          <label>
            <span>Срок действия <small>необязательно</small></span>
            <input
              aria-label="Срок действия объявления"
              type="datetime-local"
              min={localDateTimeMinimum()}
              value={expiresAt}
              onChange={(event) => setExpiresAt(event.target.value)}
            />
            <small>Оставьте поле пустым, чтобы отключить автоматическое истечение срока.</small>
          </label>
          {submitError && <p className="creation-error" role="alert">{submitError}</p>}
          <button className="load-more-button" type="submit" disabled={submitting}>
            {submitting ? "Создаём черновик…" : "Сохранить черновик"}
          </button>
        </form>
      ) : loading ? (
        <div className="my-listings-message" role="status">Проверяем инвентарь подтверждённых TON NFT…</div>
      ) : /verified TON wallet is required|необходимо подтвердить TON-кошелёк/i.test(error) ? (
        <div className="my-listings-message" role="alert">
          <h2>Сначала подтвердите кошелёк</h2>
          <p>Перед публикацией NFT необходимо подтвердить TON-кошелёк. Одного подключения недостаточно для подтверждения владения.</p>
          <a className="text-button" href="#wallet-connect">Подключить кошелёк</a>
          <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Проверить ещё раз</button>
        </div>
      ) : error ? (
        <div className="my-listings-message" role="alert">
          <h2>Инвентарь недоступен</h2>
          <p>{error}</p>
          <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Повторить</button>
        </div>
      ) : assets.length === 0 && !hasMore ? (
        <div className="my-listings-message" role="status">
          <h2>Подтверждённые TON NFT не найдены</h2>
          <p>В черновик можно добавить только NFT, которыми сейчас владеет подтверждённый кошелёк.</p>
        </div>
      ) : (
        <>
          <div className="inventory-grid">
            {assets.map((asset) => (
              <button
                className="inventory-card"
                type="button"
                key={asset.id}
                onClick={() => setSelectedAsset(asset)}
              >
                <InventoryImage asset={asset} />
                <span className="inventory-card-copy">
                  <span className="listing-type-label">Подтверждённый TON NFT</span>
                  <span className="inventory-card-title">{assetTitle(asset)}</span>
                  <span className="inventory-card-address">{asset.item_address.slice(0, 8)}…{asset.item_address.slice(-5)}</span>
                </span>
              </button>
            ))}
          </div>
          {loadMoreError && <p className="creation-error" role="alert">{loadMoreError}</p>}
          {hasMore && (
            <button className="load-more-button inventory-load-more" type="button" disabled={loadingMore} onClick={loadMore}>
              {loadingMore ? "Загружаем остальные NFT…" : loadMoreError ? "Повторить загрузку" : "Загрузить ещё NFT"}
            </button>
          )}
        </>
      )}
    </section>
  );
}
