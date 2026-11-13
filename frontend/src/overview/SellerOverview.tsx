import { useEffect, useState } from "react";

import { fetchSellerOverview, type SellerActivityItem, type SellerOverview } from "../api/overview";

interface Props {
  accessToken: string;
  onOpenOrders: (orderId?: string) => void;
  onOpenListing: (listingId: string) => void;
  onManageListings: () => void;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Дата недоступна"
    : new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    draft: "Черновик",
    pending_review: "На модерации",
    active: "Активно",
    reserved: "Зарезервировано",
    sold: "Продано",
    cancelled: "Отменено",
    expired: "Истекло",
    suspended: "Приостановлено",
    awaiting_transfer: "Ожидает передачи",
    observing_transfer: "Проверяем передачу",
    completed: "Завершено",
  };
  return labels[status] ?? status.replaceAll("_", " ");
}

function formatSnapshots(values: Record<string, string>) {
  const entries = Object.entries(values).sort(([left], [right]) => left.localeCompare(right));
  return entries.length
    ? entries.map(([currency, amount]) => `${amount} ${currency}`).join(" · ")
    : "—";
}

function ActivityRow({
  item,
  onOpenOrders,
  onOpenListing,
}: {
  item: SellerActivityItem;
  onOpenOrders: (orderId?: string) => void;
  onOpenListing: (listingId: string) => void;
}) {
  const isOrder = item.kind === "order";
  return (
    <button
      className="seller-activity-row"
      type="button"
      onClick={() => isOrder ? onOpenOrders(item.id) : onOpenListing(item.listing_id)}
    >
      <span className="seller-activity-kind">{isOrder ? (item.role === "buyer" ? "ПОКУПКА" : "ПРОДАЖА") : "ОБЪЯВЛЕНИЕ"}</span>
      <span className="seller-activity-main">
        <strong>{item.title}</strong>
        <span>{isOrder ? "Заказ" : "Объявление"} · {statusLabel(item.status)} · {formatDate(item.created_at)}</span>
      </span>
      <span className="seller-activity-price">{item.price_amount} {item.price_currency}</span>
      <span className="seller-activity-arrow" aria-hidden="true">↗</span>
    </button>
  );
}

export function SellerOverview({ accessToken, onOpenOrders, onOpenListing, onManageListings }: Props) {
  const [overview, setOverview] = useState<SellerOverview | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetchSellerOverview(accessToken, controller.signal)
      .then((result) => {
        if (!controller.signal.aborted) setOverview(result);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Не удалось загрузить обзор магазина.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [accessToken, retry]);

  if (loading) {
    return <section className="seller-overview-message" role="status" aria-busy="true">Загружаем обзор магазина…</section>;
  }
  if (error || !overview) {
    return (
      <section className="seller-overview-message" role="alert">
        <h2>Обзор недоступен</h2>
        <p>{error || "Не удалось загрузить обзор магазина."}</p>
        <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Повторить</button>
      </section>
    );
  }

  const listingCards = [
    { label: "Активные объявления", value: overview.listings.active },
    { label: "На модерации", value: overview.listings.pending_review },
    { label: "Зарезервированные", value: overview.listings.reserved },
    { label: "Черновики", value: overview.listings.draft },
    { label: "Всего объявлений", value: overview.listings.total },
  ];
  const orderCards = [
    { label: "Полученные заказы", value: overview.orders_as_seller.total },
    { label: "Оформленные заказы", value: overview.orders_as_buyer.total },
    { label: "Заказы в процессе", value: overview.orders_as_seller.awaiting_transfer + overview.orders_as_seller.reserved + overview.orders_as_seller.observing_transfer },
    { label: "Завершённые передачи", value: overview.orders_as_seller.completed },
  ];

  return (
    <section className="seller-overview" aria-labelledby="seller-overview-title">
      <div className="seller-overview-heading">
        <div>
          <p className="eyebrow">ВАШ МАРКЕТПЛЕЙС</p>
          <h1 id="seller-overview-title">Обзор магазина</h1>
          <p>Статистика объявлений, заказов и последних действий.</p>
        </div>
        <button className="refresh-button" type="button" onClick={() => setRetry((value) => value + 1)}>Обновить</button>
      </div>

      <section className="seller-overview-section" aria-labelledby="seller-listings-heading">
        <div className="seller-overview-section-heading">
          <h2 id="seller-listings-heading">Объявления</h2>
          <button className="text-button" type="button" onClick={onManageListings}>Управлять объявлениями ↗</button>
        </div>
        <div className="seller-overview-grid">
          {listingCards.map((card) => (
            <article className="seller-overview-card" key={card.label}>
              <span>{card.label}</span>
              <strong>{card.value}</strong>
            </article>
          ))}
        </div>
      </section>

      <section className="seller-overview-section" aria-labelledby="seller-orders-heading">
        <div className="seller-overview-section-heading">
          <h2 id="seller-orders-heading">Заказы</h2>
          <button className="text-button" type="button" onClick={() => onOpenOrders()}>Открыть заказы ↗</button>
        </div>
        <div className="seller-overview-grid">
          {orderCards.map((card) => (
            <article className="seller-overview-card" key={card.label}>
              <span>{card.label}</span>
              <strong>{card.value}</strong>
            </article>
          ))}
        </div>
        <div className="seller-overview-values">
          <article>
            <span>Сумма резервов по валютам</span>
            <strong>{formatSnapshots(overview.reserved_order_snapshot_values)}</strong>
          </article>
          <article>
            <span>Сумма завершённых заказов</span>
            <strong>{formatSnapshots(overview.completed_order_snapshot_values)}</strong>
          </article>
        </div>
        <p className="seller-overview-disclaimer">
          Это снимки цен объявлений и заказов. Резервирование не является оплатой: VILTARA не списывает и не хранит средства.
        </p>
      </section>

      <section className="seller-overview-section" aria-labelledby="seller-activity-heading">
        <div className="seller-overview-section-heading">
          <h2 id="seller-activity-heading">Последняя активность</h2>
          <span>{overview.recent_activity.length} записей</span>
        </div>
        {overview.recent_activity.length ? (
          <div className="seller-activity-list">
            {overview.recent_activity.map((item) => (
              <ActivityRow key={`${item.kind}-${item.id}`} item={item} onOpenOrders={onOpenOrders} onOpenListing={onOpenListing} />
            ))}
          </div>
        ) : (
          <div className="seller-overview-empty">
            <h3>Пока нет активности</h3>
            <p>Создайте объявление или зарезервируйте предмет — здесь появится история действий.</p>
          </div>
        )}
      </section>
    </section>
  );
}
