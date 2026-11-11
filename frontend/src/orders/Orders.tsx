import { useEffect, useMemo, useState } from "react";

import {
  cancelOrder,
  fetchOrder,
  fetchOrders,
  type MarketplaceOrder,
  type OrderRole,
  type OrderStatus,
} from "../api/orders";

type StatusFilter = "all" | "active" | "completed" | "closed";
type SortMode = "newest" | "oldest" | "price";

const statusOrder: OrderStatus[] = [
  "reserved",
  "awaiting_transfer",
  "observing_transfer",
  "completed",
];

function getOrderTitle(order: MarketplaceOrder) {
  return order.title || order.asset_name || "Untitled asset";
}

function getDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function getTimestamp(value: string) {
  const time = new Date(value).getTime();
  return Number.isFinite(time) ? time : 0;
}

function statusLabel(status: OrderStatus) {
  switch (status) {
    case "reserved": return "Reservation pending";
    case "awaiting_transfer": return "Awaiting transfer";
    case "observing_transfer": return "Verifying transfer";
    case "completed": return "Completed";
    case "cancelled": return "Cancelled";
    case "expired": return "Expired";
  }
}

function statusGuidance(status: OrderStatus) {
  switch (status) {
    case "reserved":
      return "The listing is reserved. The seller has not started the NFT transfer.";
    case "awaiting_transfer":
      return "The seller is preparing a direct NFT transfer to the buyer. Payments are not enabled.";
    case "observing_transfer":
      return "The transfer is being checked against on-chain evidence. It is not considered delivered until verification completes.";
    case "completed":
      return "The server confirmed the exact NFT transfer to the buyer. This order is complete.";
    case "cancelled":
      return "This reservation was cancelled. No payment or refund was processed by this app.";
    case "expired":
      return "The reservation expired before completion. Payments and automatic refunds are not enabled.";
  }
}

function formatRemaining(expiresAt: string, now: number) {
  const expiry = new Date(expiresAt).getTime();
  if (!Number.isFinite(expiry)) return "Expiry unavailable";
  const remaining = expiry - now;
  if (remaining <= 0) return "Reservation expired";
  const seconds = Math.floor(remaining / 1000);
  const days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600);
  const minutes = Math.floor((seconds % 3600) / 60);
  const secs = seconds % 60;
  if (days > 0) return `${days}d ${hours}h remaining`;
  return `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")} remaining`;
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
      aria-label={`Open order ${title}, ${statusLabel(order.status)}`}
    >
      <span className="workspace-card-topline">
        <span className="workspace-asset-type">{order.asset_type === "ton_nft" ? "TON NFT" : "TELEGRAM GIFT"}</span>
        <span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span>
      </span>
      <span className="workspace-card-title">{title}</span>
      <span className="workspace-card-price">{order.price_amount} {order.price_currency}</span>
      <span className="workspace-card-meta">
        <span>{role === "buyer" ? "Purchase" : "Sale"} · {getDate(order.created_at)}</span>
        <span className="workspace-card-arrow" aria-hidden="true">↗</span>
      </span>
    </button>
  );
}

function OrderDetails({
  order,
  role,
  busy,
  onClose,
  onCancel,
}: {
  order: MarketplaceOrder;
  role: OrderRole;
  busy: boolean;
  onClose: () => void;
  onCancel: (orderId: string) => void;
}) {
  const now = useClock();
  const [copied, setCopied] = useState(false);
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [copyError, setCopyError] = useState("");
  const isTerminal = order.status === "cancelled" || order.status === "expired";
  const activeIndex = statusOrder.indexOf(order.status);

  async function copyOrderId() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(order.id);
      setCopied(true);
      setCopyError("");
      window.setTimeout(() => setCopied(false), 1800);
    } catch {
      setCopyError("Copy is unavailable here. Select and copy the ID manually.");
    }
  }

  return (
    <section className="order-detail-panel" aria-labelledby="order-detail-title">
      <div className="order-detail-toolbar">
        <button className="text-button" type="button" onClick={onClose}>← Back to orders</button>
        <span className="workspace-asset-type">ORDER DETAILS</span>
      </div>
      <div className="order-detail-hero">
        <div className="order-detail-symbol" aria-hidden="true">{order.asset_type === "ton_nft" ? "◇" : "✳"}</div>
        <div className="order-detail-heading">
          <p className="eyebrow">{order.asset_type === "ton_nft" ? "TON NFT" : "TELEGRAM GIFT"}</p>
          <h1 id="order-detail-title">{getOrderTitle(order)}</h1>
          <p className="order-detail-price">{order.price_amount} {order.price_currency}</p>
        </div>
        <span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span>
      </div>

      <div className="order-detail-grid">
        <div className="order-detail-main">
          <section className="workspace-section" aria-labelledby="lifecycle-heading">
            <div className="workspace-section-heading">
              <div><p className="eyebrow">ORDER JOURNEY</p><h2 id="lifecycle-heading">Lifecycle</h2></div>
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
                      <span className="lifecycle-step-copy"><strong>{statusLabel(status)}</strong>{current && <small>Current stage</small>}</span>
                    </li>
                  );
                })}
              </ol>
            )}
            <p className="order-guidance">{statusGuidance(order.status)}</p>
            <p className="payment-disclaimer">Payments are not enabled in VILTARA SHOP. This app does not provide escrow, custody, automatic refunds, or payment processing.</p>
          </section>

          <section className="workspace-section" aria-labelledby="timeline-heading">
            <div className="workspace-section-heading"><div><p className="eyebrow">AUDIT TRAIL</p><h2 id="timeline-heading">Event timeline</h2></div><span className="workspace-count">{order.events.length} events</span></div>
            {order.events.length ? (
              <ol className="event-timeline">
                {[...order.events].sort((a, b) => getTimestamp(a.created_at) - getTimestamp(b.created_at)).map((event, index) => (
                  <li key={`${event.to_status}-${event.created_at}-${index}`}>
                    <span className="event-timeline-dot" aria-hidden="true" />
                    <div className="event-timeline-copy"><strong>{statusLabel(event.to_status)}</strong><span>{event.actor_type === "system" ? "System" : event.actor_type === "buyer" ? "Buyer" : "Seller"} update</span></div>
                    <time dateTime={event.created_at}>{getDate(event.created_at)}</time>
                  </li>
                ))}
              </ol>
            ) : <p className="workspace-muted">No lifecycle events are available yet.</p>}
          </section>
        </div>

        <aside className="order-detail-aside">
          {order.status === "reserved" && (
            <section className="expiry-card" aria-live="polite">
              <p className="eyebrow">RESERVATION WINDOW</p>
              <strong className="expiry-countdown">{formatRemaining(order.expires_at, now)}</strong>
              <p>Expires {getDate(order.expires_at)}</p>
            </section>
          )}
          <section className="workspace-section order-facts">
            <p className="eyebrow">ORDER INFORMATION</p>
            <dl>
              <div><dt>Your role</dt><dd>{role === "buyer" ? "Buyer · Purchase" : "Seller · Sale"}</dd></div>
              <div><dt>Order ID</dt><dd className="order-id-value"><code>{order.id}</code><button className="copy-id-button" type="button" onClick={() => void copyOrderId()} aria-label="Copy order ID">{copied ? "Copied" : "Copy ID"}</button></dd></div>
              {copyError && <p className="copy-id-error" role="status">{copyError}</p>}
              <div><dt>Listing ID</dt><dd><code>{order.listing_id}</code></dd></div>
              <div><dt>Asset type</dt><dd>{order.asset_type === "ton_nft" ? "TON NFT" : "Telegram gift"}</dd></div>
              <div><dt>Created</dt><dd>{getDate(order.created_at)}</dd></div>
              <div><dt>Last updated</dt><dd>{getDate(order.updated_at)}</dd></div>
              <div><dt>Reservation expires</dt><dd>{getDate(order.expires_at)}</dd></div>
            </dl>
          </section>
          {role === "buyer" && order.status === "reserved" && (
            <section className="cancel-order-card">
              {!confirmCancel ? (
                <><strong>Need to cancel?</strong><p>You can cancel while this order is still reserved.</p><button className="danger-button" type="button" onClick={() => setConfirmCancel(true)}>Cancel order</button></>
              ) : (
                <div className="cancel-confirmation" role="group" aria-label="Confirm order cancellation">
                  <strong>Cancel this reservation?</strong>
                  <p>This cannot be undone. No payment or refund will be processed.</p>
                  <div><button className="danger-button" type="button" disabled={busy} onClick={() => onCancel(order.id)}>{busy ? "Cancelling…" : "Confirm cancellation"}</button><button className="secondary-button" type="button" disabled={busy} onClick={() => setConfirmCancel(false)}>Keep order</button></div>
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

  useEffect(() => {
    if (!initialOrderId || !userId) {
      setLinkedOrder(null);
      setLinkedOrderError("");
      return;
    }
    const controller = new AbortController();
    setLinkedOrder(null);
    setLinkedOrderError("");
    fetchOrder(initialOrderId, accessToken, controller.signal)
      .then((order) => {
        if (order.buyer_id !== userId && order.seller_id !== userId) {
          throw new Error("This order is not available for this account.");
        }
        setLinkedOrder(order);
        setRole(order.buyer_id === userId ? "buyer" : "seller");
        setSelectedOrder(order);
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) setLinkedOrderError(reason instanceof Error ? reason.message : "Unable to open this order.");
      });
    return () => controller.abort();
  }, [accessToken, initialOrderId, userId]);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetchOrders(role, accessToken, controller.signal)
      .then(setOrders)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Unable to load orders.");
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
    setSelectedOrder(order);
    setDetailLoading(true);
    setDetailError("");
    try {
      const fullOrder = await fetchOrder(order.id, accessToken);
      if (userId && fullOrder.buyer_id !== userId && fullOrder.seller_id !== userId) {
        throw new Error("This order is not available for this account.");
      }
      setSelectedOrder(fullOrder);
      setOrders((current) => current.map((item) => item.id === fullOrder.id ? fullOrder : item));
      setLinkedOrder((current) => current?.id === fullOrder.id ? fullOrder : current);
    } catch (reason) {
      setDetailError(reason instanceof Error ? reason.message : "Unable to load order details.");
    } finally {
      setDetailLoading(false);
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
      setActionError(reason instanceof Error ? reason.message : "Unable to cancel this order.");
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
        {detailLoading && <p className="workspace-inline-loading" role="status">Refreshing order details…</p>}
        {detailError && <div className="orders-error" role="alert"><span>{detailError}</span><button className="text-button" type="button" onClick={() => void openOrder(selectedOrder)}>Retry</button></div>}
        <OrderDetails order={selectedOrder} role={userId ? (selectedOrder.buyer_id === userId ? "buyer" : "seller") : role} busy={busyOrderId === selectedOrder.id} onClose={() => setSelectedOrder(null)} onCancel={(id) => void handleCancel(id)} />
      </div>
    );
  }

  return (
    <section className="orders-view" aria-labelledby="orders-title">
      <div className="workspace-page-heading">
        <div><p className="eyebrow">YOUR MARKETPLACE ACTIVITY</p><h1 id="orders-title">Order workspace</h1><p className="workspace-subtitle">Track reservations, transfers and completed orders in one place.</p></div>
        <button className="secondary-button refresh-button" type="button" disabled={loading} onClick={() => { setRefreshing(true); setRetry((value) => value + 1); }}><span aria-hidden="true">↻</span> {refreshing ? "Refreshing…" : "Refresh"}</button>
      </div>

      <div className="workspace-role-tabs" role="tablist" aria-label="Order type">
        <button role="tab" id="purchases-tab" aria-selected={role === "buyer"} type="button" onClick={() => { setRole("buyer"); setFilter("all"); }}><span>Purchases</span><span className="workspace-tab-count">{role === "buyer" ? counts.all : "—"}</span></button>
        <button role="tab" id="sales-tab" aria-selected={role === "seller"} type="button" onClick={() => { setRole("seller"); setFilter("all"); }}><span>Sales</span><span className="workspace-tab-count">{role === "seller" ? counts.all : "—"}</span></button>
      </div>

      {actionError && <p className="orders-error" role="alert">{actionError}</p>}
      {linkedOrderError && <p className="orders-error" role="alert">{linkedOrderError}</p>}

      <div className="workspace-toolbar">
        <label className="workspace-search"><span aria-hidden="true">⌕</span><span className="sr-only">Search orders by asset title or order ID</span><input type="search" value={search} onChange={(event) => setSearch(event.target.value)} placeholder="Search title or order ID" /></label>
        <label className="workspace-sort"><span className="sr-only">Sort orders</span><select value={sort} onChange={(event) => setSort(event.target.value as SortMode)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="price">Highest price</option></select></label>
      </div>

      <div className="workspace-filter-row" role="group" aria-label="Filter orders by status">
        {([{ value: "all", label: "All", count: counts.all }, { value: "active", label: "Active", count: counts.active }, { value: "completed", label: "Completed", count: counts.completed }, { value: "closed", label: "Cancelled / expired", count: counts.closed }] as const).map((item) => (
          <button key={item.value} type="button" className={filter === item.value ? "workspace-filter is-active" : "workspace-filter"} aria-pressed={filter === item.value} onClick={() => setFilter(item.value)}>{item.label}<span>{item.count}</span></button>
        ))}
      </div>

      {loading ? (
        <div className="workspace-order-grid" aria-label="Loading orders" role="status"><span className="sr-only">Loading orders...</span>{[1, 2, 3, 4].map((item) => <div className="workspace-skeleton" key={item}><span /><span /><span /><span /></div>)}</div>
      ) : error ? (
        <div className="orders-message workspace-empty" role="alert"><span className="workspace-empty-icon" aria-hidden="true">!</span><h2>Orders unavailable</h2><p>{error}</p><button className="primary-button" type="button" onClick={() => setRetry((value) => value + 1)}>Try again</button></div>
      ) : visibleOrders.length === 0 ? (
        <div className="orders-message workspace-empty" role="status"><span className="workspace-empty-icon" aria-hidden="true">◇</span><h2>{search || filter !== "all" ? "No matching orders" : `No ${role === "buyer" ? "purchases" : "sales"} yet`}</h2><p>{search || filter !== "all" ? "Try another search or status filter." : "When you reserve a listing or sell an asset, your order activity will appear here."}</p>{search || filter !== "all" ? <button className="secondary-button" type="button" onClick={() => { setSearch(""); setFilter("all"); }}>Clear filters</button> : onCatalog ? <button className="primary-button" type="button" onClick={onCatalog}>Explore catalog</button> : null}</div>
      ) : (
        <>
          <div className="workspace-results-heading"><span>{visibleOrders.length} {visibleOrders.length === 1 ? "order" : "orders"}</span><span>Updated from your account</span></div>
          <div className="workspace-order-grid">{visibleOrders.map((order) => <OrderCard key={order.id} order={order} role={role} highlighted={order.id === linkedOrder?.id} onOpen={() => void openOrder(order)} />)}</div>
        </>
      )}
    </section>
  );
}
