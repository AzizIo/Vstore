import { useEffect, useMemo, useRef, useState } from "react";

import {
  cancelOrder,
  fetchOrder,
  fetchOrders,
  type MarketplaceOrder,
  type OrderRole,
  type OrderStatus,
} from "../api/orders";
import { ReviewForm } from "../reviews/ReviewForm";

import { DeliveryWorkspace } from "./DeliveryWorkspace";

type StatusFilter = "all" | "active" | "completed" | "closed";
type SortMode = "newest" | "oldest" | "price";

const statusOrder: OrderStatus[] = [
  "reserved",
  "awaiting_transfer",
  "observing_transfer",
  "completed",
];

function getOrderTitle(order: MarketplaceOrder) {
  return order.title || order.asset_name || "Без названия";
}

function formatOrderPrice(amount: string, currency: string) {
  const value = Number(amount);
  const formatted = Number.isFinite(value)
    ? new Intl.NumberFormat("ru-RU", { maximumFractionDigits: 2 }).format(value)
    : amount;
  return `${formatted} ${currency}`;
}

function getDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Дата недоступна"
    : new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function formatOrderCount(count: number) {
  const category = new Intl.PluralRules("ru-RU").select(count);
  const noun = category === "one" ? "заказ" : category === "few" ? "заказа" : "заказов";
  return `${count} ${noun}`;
}

function getTimestamp(value: string) {
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function statusLabel(status: OrderStatus) {
  switch (status) {
    case "reserved": return "Ожидает передачи";
    case "awaiting_transfer": return "Ожидает перевода";
    case "observing_transfer": return "Проверяем перевод";
    case "completed": return "Завершён";
    case "cancelled": return "Отменено";
    case "expired": return "Срок истёк";
  }
}

function statusGuidance(status: OrderStatus) {
  switch (status) {
    case "reserved":
      return "Объявление зарезервировано. Продавец ещё не начал передачу NFT.";
    case "awaiting_transfer":
      return "Продавец готовит прямую передачу NFT покупателю. Оплата не предусмотрена.";
    case "observing_transfer":
      return "Проверяем перевод по данным блокчейна. Заказ не считается завершённым до окончания проверки.";
    case "completed":
      return "Сервер подтвердил передачу нужного NFT покупателю. Заказ завершён.";
    case "cancelled":
      return "Резерв отменён. Приложение не проводило оплату или возврат средств.";
    case "expired":
      return "Срок резерва истёк до завершения заказа. Оплата и автоматический возврат средств не предусмотрены.";
  }
}

function formatRemaining(expiresAt: string, now: number) {
  const expiry = new Date(expiresAt).getTime();
  if (!Number.isFinite(expiry)) return "Срок действия неизвестен";
  const remaining = expiry - now;
  if (remaining <= 0) return "Срок резерва истёк";
  const seconds = Math.floor(remaining / 1000);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (days > 0) return `${days} дн. ${hours} ч. осталось`;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")} осталось`;
}

function useClock() {
  const [now, setNow] = useState(() => Date.now());
  useEffect(() => {
    const timer = window.setInterval(() => setNow(Date.now()), 1000);
    return () => window.clearInterval(timer);
  }, []);
  return now;
}

function OrderCard({
  order,
  role,
  highlighted,
  onOpen,
}: {
  order: MarketplaceOrder;
  role: OrderRole;
  highlighted: boolean;
  onOpen: () => void;
}) {
  const title = getOrderTitle(order);
  return (
    <button
      className={`workspace-order-card${highlighted ? " workspace-order-card-linked" : ""}`}
      type="button"
      onClick={onOpen}
      aria-label={`Открыть заказ ${title}, ${statusLabel(order.status)}`}
    >
      <span className="workspace-card-topline">
        <span className="workspace-asset-type">{order.asset_type === "ton_nft" ? "TON NFT" : "ПОДАРОК TELEGRAM"}</span>
        <span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span>
      </span>
      <span className="workspace-card-title">{title}</span>
      <span className="workspace-card-price">{formatOrderPrice(order.price_amount, order.price_currency)}</span>
      <span className="workspace-card-meta">
        <span>{role === "buyer" ? "Покупка" : "Продажа"} · {getDate(order.created_at)}</span>
        <span className="workspace-card-arrow" aria-hidden="true">↗</span>
      </span>
    </button>
  );
}

function OrderDetails({
  order,
  role,
  busy,
  accessToken,
  onClose,
  onCancel,
  onRefreshOrder,
}: {
  order: MarketplaceOrder;
  role: OrderRole;
  busy: boolean;
  accessToken: string;
  onClose: () => void;
  onCancel: (orderId: string) => void;
  onRefreshOrder: () => void;
}) {
  const now = useClock();
  const [copied, setCopied] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [copyError, setCopyError] = useState("");
  const isTerminal = order.status === "cancelled" || order.status === "expired";
  const activeIndex = statusOrder.indexOf(order.status);

  async function copyOrderId() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Буфер обмена недоступен");
      await navigator.clipboard.writeText(order.id);
      setCopied(true);
      setCopyError("");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopyError("Копирование недоступно. Выделите и скопируйте ID вручную.");
    }
  }

  return (
    <section className="order-detail-panel" aria-labelledby="order-detail-title">
      <div className="order-detail-toolbar">
        <button className="text-button" type="button" onClick={onClose}>← Назад к заказам</button>
        <span className="workspace-asset-type">ДАННЫЕ ЗАКАЗА</span>
      </div>
      <div className="order-detail-hero">
        <div className="order-detail-symbol" aria-hidden="true">{order.asset_type === "ton_nft" ? "◇" : "✳"}</div>
        <div className="order-detail-heading">
          <p className="eyebrow">{order.asset_type === "ton_nft" ? "TON NFT" : "ПОДАРОК TELEGRAM"}</p>
          <h1 id="order-detail-title">{getOrderTitle(order)}</h1>
          <p className="order-detail-price">{formatOrderPrice(order.price_amount, order.price_currency)}</p>
        </div>
        <span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span>
      </div>

      <div className="order-detail-grid">
        <div className="order-detail-main">
          <section className="workspace-section" aria-labelledby="lifecycle-heading">
            <div className="workspace-section-heading">
              <div><p className="eyebrow">ЭТАПЫ ЗАКАЗА</p><h2 id="lifecycle-heading">Статус заказа</h2></div>
              <span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span>
            </div>
            {isTerminal ? (
              <div className={`lifecycle-terminal lifecycle-terminal-${order.status}`}>
                <span aria-hidden="true">{order.status === "cancelled" ? "×" : "!"}</span>
                <div><strong>{statusLabel(order.status)}</strong><p>{statusGuidance(order.status)}</p></div>
              </div>
            ) : (
              <ol className="lifecycle-steps">
                {statusOrder.map((status, index) => {
                  const done = index < activeIndex || status === order.status;
                  const current = status === order.status;
                  return (
                    <li key={status} className={`lifecycle-step${done ? " is-done" : ""}${current ? " is-current" : ""}`}>
                      <span className="lifecycle-step-marker" aria-hidden="true">{index < activeIndex ? "✓" : index + 1}</span>
                      <span className="lifecycle-step-copy"><strong>{statusLabel(status)}</strong>{current && <small>Текущий этап</small>}</span>
                    </li>
                  );
                })}
              </ol>
            )}
            <p className="order-guidance">{statusGuidance(order.status)}</p>
            <p className="payment-disclaimer">Оплата в VILTARA SHOP пока не подключена. Приложение не предоставляет эскроу, хранение средств, автоматический возврат или обработку платежей.</p>
          </section>

          <section className="workspace-section" aria-labelledby="timeline-heading">
            <div className="workspace-section-heading"><div><p className="eyebrow">ИСТОРИЯ ИЗМЕНЕНИЙ</p><h2 id="timeline-heading">История событий</h2></div><span className="workspace-count">{order.events.length} событий</span></div>
            {order.events.length ? (
              <ol className="event-timeline">
                {[...order.events].sort((a, b) => getTimestamp(a.created_at) - getTimestamp(b.created_at)).map((event, index) => (
                  <li key={`${event.to_status}-${event.created_at}-${index}`}>
                    <span className="event-timeline-dot" aria-hidden="true" />
                    <div className="event-timeline-copy"><strong>{statusLabel(event.to_status)}</strong><span>{event.actor_type === "system" ? "Система" : event.actor_type === "buyer" ? "Покупатель" : "Продавец"} обновление</span></div>
                    <time dateTime={event.created_at}>{getDate(event.created_at)}</time>
                  </li>
                ))}
              </ol>
            ) : <p className="workspace-muted">Пока нет событий по этому заказу.</p>}
          </section>
          {role === "buyer" && order.status === "completed" && (
            <ReviewForm
              orderId={order.id}
              accessToken={accessToken}
              onSubmitted={onRefreshOrder}
            />
          )}
          <DeliveryWorkspace
            order={order}
            role={role}
            accessToken={accessToken}
            onRefreshOrder={onRefreshOrder}
          />
        </div>

        <aside className="order-detail-aside">
          {order.status === "reserved" && (
            <section className="expiry-card" aria-live="polite">
              <p className="eyebrow">СРОК РЕЗЕРВА</p>
              <strong className="expiry-countdown">{formatRemaining(order.expires_at, now)}</strong>
              <p>Истекает {getDate(order.expires_at)}</p>
            </section>
          )}
          <section className="workspace-section order-facts">
            <p className="eyebrow">ИНФОРМАЦИЯ О ЗАКАЗЕ</p>
            <dl>
              <div><dt>Ваша роль</dt><dd>{role === "buyer" ? "Покупатель · Покупка" : "Продавец · Продажа"}</dd></div>
              <div><dt>ID заказа</dt><dd className="order-id-value"><code>{order.id}</code><button className="copy-id-button" type="button" onClick={() => void copyOrderId()} aria-label="Скопировать ID заказа">{copied ? "Скопировано" : "Копировать ID"}</button></dd></div>
              {copied && <div className="mini-toast mini-toast-success" role="status">ID заказа скопирован</div>}
              {copyError && <p className="copy-id-error" role="status">{copyError}</p>}
              <div><dt>ID объявления</dt><dd><code>{order.listing_id}</code></dd></div>
              <div><dt>Тип актива</dt><dd>{order.asset_type === "ton_nft" ? "TON NFT" : "Подарок Telegram"}</dd></div>
              <div><dt>Создан</dt><dd>{getDate(order.created_at)}</dd></div>
              <div><dt>Последнее обновление</dt><dd>{getDate(order.updated_at)}</dd></div>
              <div><dt>Резерв истекает</dt><dd>{getDate(order.expires_at)}</dd></div>
            </dl>
          </section>
          {role === "buyer" && order.status === "reserved" && (
            <section className="cancel-order-card">
              {!confirmCancel ? (
                <><strong>Хотите отменить?</strong><p>Вы можете отменить заказ, пока он находится в резерве.</p><button className="danger-button" type="button" onClick={() => setConfirmCancel(true)}>Отменить заказ</button></>
              ) : (
                <div className="cancel-confirmation" role="group" aria-label="Подтвердите отмену заказа">
                  <strong>Отменить этот резерв?</strong>
                  <p>Это действие нельзя отменить. Оплата и возврат средств не проводятся.</p>
                  <div><button className="danger-button" type="button" disabled={busy} onClick={() => onCancel(order.id)}>{busy ? "Отменяем…" : "Подтвердить отмену"}</button><button className="secondary-button" type="button" disabled={busy} onClick={() => setConfirmCancel(false)}>Оставить заказ</button></div>
                </div>
              )}
            </section>
          )}
        </aside>
      </div>
    </section>
  );
}

export function Orders({
  accessToken,
  userId,
  initialOrderId = null,
  onCatalog,
}: {
  accessToken: string;
  userId?: string;
  initialOrderId?: string | null;
  onCatalog?: () => void;
}) {
  const [role, setRole] = useState<OrderRole>("buyer");
  const [orders, setOrders] = useState<MarketplaceOrder[]>([]);
  const [selectedOrder, setSelectedOrder] = useState<MarketplaceOrder | null>(null);
  const [detailLoading, setDetailLoading] = useState(false);
  const [detailError, setDetailError] = useState("");
  const [linkedOrder, setLinkedOrder] = useState<MarketplaceOrder | null>(null);
  const [linkedOrderError, setLinkedOrderError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyOrderId, setBusyOrderId] = useState("");
  const [retry, setRetry] = useState(0);
  const [search, setSearch] = useState("");
  const [filter, setFilter] = useState<StatusFilter>("all");
  const [sort, setSort] = useState<SortMode>("newest");
  const [refreshing, setRefreshing] = useState(false);
  const detailRequestRef = useRef(0);

  useEffect(() => {
    if (!initialOrderId || !userId) {
      setLinkedOrder(null);
      setLinkedOrderError("");
      return;
    }
    const requestId = ++detailRequestRef.current;
    const controller = new AbortController();
    setLinkedOrder(null);
    setLinkedOrderError("");
    fetchOrder(initialOrderId, accessToken, controller.signal)
      .then((order) => {
        if (controller.signal.aborted || requestId !== detailRequestRef.current) return;
        if (order.buyer_id !== userId && order.seller_id !== userId) {
          throw new Error("Этот заказ недоступен для вашего аккаунта.");
        }
        setLinkedOrder(order);
        setRole(order.buyer_id === userId ? "buyer" : "seller");
        setSelectedOrder(order);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted && requestId === detailRequestRef.current) {
          setLinkedOrderError(reason instanceof Error ? reason.message : "Не удалось открыть заказ.");
        }
      });
    return () => {
      controller.abort();
      if (requestId === detailRequestRef.current) detailRequestRef.current += 1;
    };
  }, [accessToken, initialOrderId, userId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetchOrders(role, accessToken, controller.signal)
      .then(setOrders)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Не удалось загрузить заказы.");
          setOrders([]);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) {
          setLoading(false);
          setRefreshing(false);
        }
      });
    return () => controller.abort();
  }, [accessToken, retry, role]);

  async function openOrder(order: MarketplaceOrder) {
    const requestId = ++detailRequestRef.current;
    setSelectedOrder(order);
    setDetailLoading(true);
    setDetailError("");
    try {
      const fullOrder = await fetchOrder(order.id, accessToken);
      if (requestId !== detailRequestRef.current) return;
      if (userId && fullOrder.buyer_id !== userId && fullOrder.seller_id !== userId) {
        throw new Error("Этот заказ недоступен для вашего аккаунта.");
      }
      setSelectedOrder(fullOrder);
      setOrders((current) => current.map((item) => item.id === fullOrder.id ? fullOrder : item));
      setLinkedOrder((current) => current?.id === fullOrder.id ? fullOrder : current);
    } catch (reason) {
      if (requestId === detailRequestRef.current) {
        setDetailError(reason instanceof Error ? reason.message : "Не удалось загрузить данные заказа.");
      }
    } finally {
      if (requestId === detailRequestRef.current) setDetailLoading(false);
    }
  }

  async function handleCancel(orderId: string) {
    setBusyOrderId(orderId);
    setActionError("");
    try {
      const updated = await cancelOrder(orderId, accessToken);
      setOrders((current) => current.map((order) => order.id === updated.id ? updated : order));
      setLinkedOrder((current) => current?.id === updated.id ? updated : current);
      setSelectedOrder((current) => current?.id === updated.id ? updated : current);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Не удалось отменить заказ.");
    } finally {
      setBusyOrderId("");
    }
  }

  const counts = useMemo(() => ({
    all: orders.length,
    active: orders.filter((order) => ["reserved", "awaiting_transfer", "observing_transfer"].includes(order.status)).length,
    completed: orders.filter((order) => order.status === "completed").length,
    closed: orders.filter((order) => order.status === "cancelled" || order.status === "expired").length,
  }), [orders]);

  const visibleOrders = useMemo(() => {
    const source = linkedOrder ? [linkedOrder, ...orders.filter((order) => order.id !== linkedOrder.id)] : orders;
    const query = search.trim().toLowerCase();
    return source.filter((order) => {
      const matchesQuery = !query || getOrderTitle(order).toLowerCase().includes(query) || order.id.toLowerCase().includes(query);
      const matchesStatus = filter === "all"
        || (filter === "active" && ["reserved", "awaiting_transfer", "observing_transfer"].includes(order.status))
        || (filter === "completed" && order.status === "completed")
        || (filter === "closed" && (order.status === "cancelled" || order.status === "expired"));
      return matchesQuery && matchesStatus;
    }).sort((a, b) => {
      if (sort === "price") return Number(b.price_amount) - Number(a.price_amount);
      const difference = getTimestamp(b.created_at) - getTimestamp(a.created_at);
      return sort === "newest" ? difference : -difference;
    });
  }, [orders, linkedOrder, search, filter, sort]);

  if (selectedOrder) {
    return (
      <div className="orders-view order-detail-view">
        {detailLoading && <p className="workspace-inline-loading" role="status">Обновляем данные заказа…</p>}
        {detailError && <div className="orders-error" role="alert"><span>{detailError}</span><button className="text-button" type="button" onClick={() => void openOrder(selectedOrder)}>Повторить</button></div>}
        <OrderDetails order={selectedOrder} role={userId ? (selectedOrder.buyer_id === userId ? "buyer" : "seller") : role} busy={busyOrderId === selectedOrder.id} accessToken={accessToken} onClose={() => { detailRequestRef.current += 1; setDetailLoading(false); setSelectedOrder(null); }} onCancel={(id) => void handleCancel(id)} onRefreshOrder={() => void openOrder(selectedOrder)} />
      </div>
    );
  }

  return (
    <section className="orders-view" aria-labelledby="orders-title">
      <div className="workspace-page-heading">
        <div><p className="eyebrow">ВАША АКТИВНОСТЬ</p><h1 id="orders-title">Заказы</h1><p className="workspace-subtitle">Все ваши резервы, передачи NFT и завершённые заказы — в одном месте.</p></div>
        <button className="secondary-button refresh-button" type="button" disabled={loading} onClick={() => { setRefreshing(true); setRetry((value) => value + 1); }}><span aria-hidden="true">↻</span> {refreshing ? "Обновляем…" : "Обновить"}</button>
      </div>

      <div className="workspace-role-tabs" role="tablist" aria-label="Тип заказа">
        <button role="tab" id="purchases-tab" aria-selected={role === "buyer"} type="button" onClick={() => { setRole("buyer"); setFilter("all"); }}><span>Покупки</span><span className="workspace-tab-count">{role === "buyer" ? counts.all : "—"}</span></button>
        <button role="tab" id="sales-tab" aria-selected={role === "seller"} type="button" onClick={() => { setRole("seller"); setFilter("all"); }}><span>Продажи</span><span className="workspace-tab-count">{role === "seller" ? counts.all : "—"}</span></button>
      </div>

      {actionError && <p className="orders-error" role="alert">{actionError}</p>}
      {linkedOrderError && <p className="orders-error" role="alert">{linkedOrderError}</p>}

      <div className="workspace-toolbar">
        <label className="workspace-search"><span aria-hidden="true">⌕</span><span className="sr-only">Поиск по названию актива или ID заказа</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Поиск по названию или ID заказа" /></label>
        <label className="workspace-sort"><span className="sr-only">Сортировка заказов</span><select value={sort} onChange={(event) => setSort(event.target.value as SortMode)}><option value="newest">Сначала новые</option><option value="oldest">Сначала старые</option><option value="price">Сначала дорогие</option></select></label>
      </div>

      <div className="workspace-filter-row" role="group" aria-label="Фильтр заказов по статусу">
        {([{ value: "all", label: "Все", count: counts.all }, { value: "active", label: "Активные", count: counts.active }, { value: "completed", label: "Завершён", count: counts.completed }, { value: "closed", label: "Отменённые / истёкшие", count: counts.closed }] as const).map((item) => (
          <button key={item.value} type="button" className={filter === item.value ? "workspace-filter is-active" : "workspace-filter"} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>{item.label}<span>{item.count}</span></button>
        ))}
      </div>

      {loading ? (
        <div className="workspace-order-grid" aria-label="Загружаем заказы" role="status"><span className="sr-only">Загружаем заказы…</span>{[1, 2, 3, 4].map((item) => <div className="workspace-skeleton" key={item}><span /><span /><span /><span /></div>)}</div>
      ) : error ? (
        <div className="orders-message workspace-empty" role="alert"><span className="workspace-empty-icon" aria-hidden="true">!</span><h2>Заказы недоступны</h2><p>{error}</p><button className="primary-button" type="button" onClick={() => setRetry((value) => value + 1)}>Повторить</button></div>
      ) : visibleOrders.length === 0 ? (
        <div className="orders-message workspace-empty" role="status"><span className="workspace-empty-icon" aria-hidden="true">◇</span><h2>{search || filter !== "all" ? "Заказы не найдены" : `Пока нет ${role === "buyer" ? "покупок" : "продаж"}`}</h2><p>{search || filter !== "all" ? "Измените поисковый запрос или фильтр статуса." : "Здесь появятся ваши заказы после резервирования объявления или продажи актива."}</p>{search || filter !== "all" ? <button className="secondary-button" type="button" onClick={() => { setSearch(""); setFilter("all"); }}>Сбросить фильтры</button> : onCatalog ? <button className="primary-button" type="button" onClick={onCatalog}>Перейти в каталог</button> : null}</div>
      ) : (
        <>
          <div className="workspace-results-heading"><span>{formatOrderCount(visibleOrders.length)}</span><span>Данные вашего аккаунта</span></div>
          <div className="workspace-order-grid">{visibleOrders.map((order) => <OrderCard key={order.id} order={order} role={role} highlighted={order.id === linkedOrder?.id} onOpen={() => void openOrder(order)} />)}</div>
        </>
      )}
    </section>
  );
}
