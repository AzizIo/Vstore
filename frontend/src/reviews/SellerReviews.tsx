import { useCallback, useEffect, useState } from "react";

import { fetchSellerReviews, type ReviewItem, type SellerReviewPage } from "./api";
import "./reviews.css";

const PAGE_SIZE = 10;

export function SellerReviews({ sellerId, accessToken: _accessToken }: { sellerId: string; accessToken: string | null }) {
  const [page, setPage] = useState<SellerReviewPage | null>(null);
  const [items, setItems] = useState<ReviewItem[]>([]);
  const [loading, setLoading] = useState(true);
  const [loadingMore, setLoadingMore] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  const load = useCallback((signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    fetchSellerReviews(sellerId, PAGE_SIZE, 0, signal)
      .then((result) => { setPage(result); setItems(result.items); })
      .catch((reason: unknown) => {
        if (!signal?.aborted) setError(reason instanceof Error ? reason.message : "Не удалось загрузить отзывы.");
      })
      .finally(() => { if (!signal?.aborted) setLoading(false); });
  }, [sellerId]);

  useEffect(() => {
    const controller = new AbortController();
    load(controller.signal);
    return () => controller.abort();
  }, [load, retry]);

  async function loadMore() {
    if (!page || loadingMore || !page.has_more) return;
    setLoadingMore(true);
    setError("");
    try {
      const next = await fetchSellerReviews(sellerId, PAGE_SIZE, items.length);
      setItems((current) => [...current, ...next.items]);
      setPage(next);
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Не удалось загрузить остальные отзывы.");
    } finally {
      setLoadingMore(false);
    }
  }

  return (
    <section className="seller-reviews" aria-labelledby="seller-reviews-title">
      <div className="reviews-heading">
        <div><p className="eyebrow">ПОДТВЕРЖДЁННЫЕ ПЕРЕДАЧИ NFT</p><h2 id="seller-reviews-title">Отзывы о продавце</h2></div>
        {page && <p className="reviews-summary"><strong>{page.average_rating.toFixed(1)}</strong> / 5 <span>· {page.review_count} verified {page.review_count === 1 ? "отзыв" : "отзывов"}</span></p>}
      </div>
      {loading ? <p role="status" className="reviews-state">Загружаем отзывы…</p> : error && items.length === 0 ? (
        <div className="reviews-state" role="alert"><p>{error}</p><button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Повторить</button></div>
      ) : items.length === 0 ? <p className="reviews-state">Пока нет подтверждённых отзывов.</p> : (
        <ul className="review-list">
          {items.map((item) => <li className="review-item" key={item.id}>
            <div className="review-item-heading"><span aria-label={`${item.rating} из 5 звёзд`}>{"★".repeat(item.rating)}{"☆".repeat(5 - item.rating)}</span><time dateTime={item.created_at}>{new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium" }).format(new Date(item.created_at))}</time></div>
            {item.comment && <p>{item.comment}</p>}
            <small>Заказ с подтверждённой передачей</small>
          </li>)}
        </ul>
      )}
      {error && items.length > 0 && <p role="alert" className="reviews-inline-error">{error}</p>}
      {page?.has_more && <button className="secondary-button reviews-load-more" type="button" disabled={loadingMore} onClick={() => void loadMore()}>{loadingMore ? "Загружаем…" : "Загрузить ещё отзывы"}</button>}
    </section>
  );
}
