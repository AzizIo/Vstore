import { useEffect, useMemo, useState } from "react";
import { cancelOrder, fetchOrder, fetchOrders, type MarketplaceOrder, type OrderRole, type OrderStatus } from "../api/orders";

type StatusFilter = "all" | "active" | "completed" | "closed";
type SortMode = "newest" | "oldest" | "price";
const lifecycle: OrderStatus[] = ["reserved", "awaiting_transfer", "observing_transfer", "completed"];
const titleOf = (order: MarketplaceOrder) => order.title || order.asset_name || "Untitled asset";
const timestamp = (value: string) => { const parsed = new Date(value).getTime(); return Number.isFinite(parsed) ? parsed : 0; };
function dateLabel(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Date unavailable" : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}
function statusLabel(status: OrderStatus) {
  switch (status) {
    case "reserved": return "Reserved";
    case "awaiting_transfer": return "Awaiting transfer";
    case "observing_transfer": return "Verifying transfer";
    case "completed": return "Completed";
    case "cancelled": return "Cancelled";
    case "expired": return "Expired";
  }
}
function guidance(status: OrderStatus) {
  switch (status) {
    case "reserved": return "The listing is reserved. NFT transfer has not started. Payments are not enabled.";
    case "awaiting_transfer": return "The seller is preparing a direct NFT transfer. This app does not process payments.";
    case "observing_transfer": return "The transfer is being checked against on-chain evidence. Do not treat it as delivered until verification completes.";
    case "completed": return "The server confirmed the exact NFT transfer to the buyer.";
    case "cancelled": return "This reservation was cancelled. No payment or refund was processed by this app.";
    case "expired": return "The reservation expired. Payments and automatic refunds are not enabled.";
  }
}
function remaining(expiresAt: string, now: number) {
  const end = new Date(expiresAt).getTime();
  if (!Number.isFinite(end)) return "Expiry unavailable";
  const delta = end - now;
  if (delta <= 0) return "Reservation expired";
  const seconds = Math.floor(delta / 1000), days = Math.floor(seconds / 86400);
  const hours = Math.floor((seconds % 86400) / 3600), minutes = Math.floor((seconds % 3600) / 60), secs = seconds % 60;
  return days ? `${days}d ${hours}h remaining` : `${String(hours).padStart(2, "0")}:${String(minutes).padStart(2, "0")}:${String(secs).padStart(2, "0")} remaining`;
}
function useClock() {
  const [now, setNow] = useState(Date.now);
  useEffect(() => { const timer = window.setInterval(() => setNow(Date.now()), 1000); return () => window.clearInterval(timer); }, []);
  return now;
}
function OrderDetails({ order, role, busy, onBack, onCancel }: { order: MarketplaceOrder; role: OrderRole; busy: boolean; onBack: () => void; onCancel: (id: string) => void }) {
  const now = useClock();
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [copyLabel, setCopyLabel] = useState("Copy ID");
  const [copyError, setCopyError] = useState("");
  const terminal = order.status === "cancelled" || order.status === "expired";
  const activeIndex = lifecycle.indexOf(order.status);
  async function copyId() {
    try {
      if (!navigator.clipboard?.writeText) throw new Error("Clipboard unavailable");
      await navigator.clipboard.writeText(order.id); setCopyLabel("Copied"); setCopyError("");
    } catch { setCopyError("Clipboard unavailable. Select and copy the ID manually."); }
  }
  return <section className="orders-view order-detail-view" aria-labelledby="order-detail-title">
    <div className="order-detail-toolbar"><button className="text-button" type="button" onClick={onBack}>← Back to orders</button><span className="eyebrow">ORDER DETAILS</span></div>
    <header className="order-detail-hero">
      <div className="order-detail-art" aria-hidden="true">{order.asset_type === "ton_nft" ? "◇" : "✳"}</div>
      <div className="order-detail-title"><p className="eyebrow">{order.asset_type === "ton_nft" ? "TON NFT" : "TELEGRAM GIFT"}</p><h1 id="order-detail-title">{titleOf(order)}</h1><p className="order-detail-price">{order.price_amount} {order.price_currency}</p></div>
      <span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span>
    </header>
    <div className="order-detail-columns">
      <div>
        <section className="workspace-panel"><p className="eyebrow">ORDER JOURNEY</p><h2>Lifecycle</h2>
          {terminal ? <div className={`lifecycle-terminal lifecycle-${order.status}`}><strong>{statusLabel(order.status)}</strong><p>{guidance(order.status)}</p></div> :
            <ol className="lifecycle-steps">{lifecycle.map((status, index) => <li key={status} className={`lifecycle-step ${index <= activeIndex ? "is-done" : ""} ${index === activeIndex ? "is-current" : ""}`}><span>{index < activeIndex ? "✓" : index + 1}</span><div><strong>{statusLabel(status)}</strong>{index === activeIndex && <small>Current stage</small>}</div></li>)}</ol>}
          <p className="order-guidance">{guidance(order.status)}</p><p className="payment-disclaimer">Payments are not enabled. VILTARA SHOP does not provide escrow, custody, payment processing or automatic refunds.</p>
        </section>
        <section className="workspace-panel"><p className="eyebrow">AUDIT TRAIL</p><h2>Event timeline</h2>
          {order.events.length ? <ol className="event-timeline">{[...order.events].sort((a,b)=>timestamp(a.created_at)-timestamp(b.created_at)).map((event,index)=><li key={`${event.to_status}-${event.created_at}-${index}`}><span className="event-dot" aria-hidden="true"/><div><strong>{statusLabel(event.to_status)}</strong><small>{event.actor_type === "system" ? "System" : event.actor_type === "buyer" ? "Buyer" : "Seller"} update</small></div><time dateTime={event.created_at}>{dateLabel(event.created_at)}</time></li>)}</ol> : <p className="workspace-muted">No lifecycle events are available yet.</p>}
        </section>
      </div>
      <aside className="order-detail-sidebar">
        {order.status === "reserved" && <section className="expiry-card" aria-live="polite"><p className="eyebrow">RESERVATION WINDOW</p><strong>{remaining(order.expires_at, now)}</strong><p>Expires {dateLabel(order.expires_at)}</p></section>}
        <section className="workspace-panel order-facts"><p className="eyebrow">ORDER INFORMATION</p><dl>
          <div><dt>Your role</dt><dd>{role === "buyer" ? "Buyer · Purchase" : "Seller · Sale"}</dd></div>
          <div><dt>Order ID</dt><dd className="order-id-row"><code>{order.id}</code><button className="copy-id-button" type="button" onClick={() => void copyId()}>{copyLabel}</button></dd></div>
          {copyError && <p className="copy-error" role="status">{copyError}</p>}
          <div><dt>Listing ID</dt><dd><code>{order.listing_id}</code></dd></div><div><dt>Asset type</dt><dd>{order.asset_type === "ton_nft" ? "TON NFT" : "Telegram gift"}</dd></div>
          <div><dt>Created</dt><dd>{dateLabel(order.created_at)}</dd></div><div><dt>Last updated</dt><dd>{dateLabel(order.updated_at)}</dd></div><div><dt>Expires</dt><dd>{dateLabel(order.expires_at)}</dd></div>
        </dl></section>
        {role === "buyer" && order.status === "reserved" && <section className="cancel-panel">{!confirmCancel ? <><strong>Cancel reservation?</strong><p>Cancellation is only available while the order is reserved.</p><button className="danger-button" type="button" onClick={()=>setConfirmCancel(true)}>Cancel order</button></> : <div role="group" aria-label="Confirm cancellation"><strong>Confirm cancellation</strong><p>This cannot be undone. No payment or refund will be processed.</p><div className="cancel-actions"><button className="danger-button" type="button" disabled={busy} onClick={()=>onCancel(order.id)}>{busy ? "Cancelling…" : "Confirm cancel"}</button><button className="secondary-button" type="button" disabled={busy} onClick={()=>setConfirmCancel(false)}>Keep order</button></div></div>}</section>}
      </aside>
    </div>
  </section>;
}
function OrderCard({ order, role, onOpen, highlighted }: { order: MarketplaceOrder; role: OrderRole; onOpen: () => void; highlighted: boolean }) {
  return <button type="button" className={`workspace-order-card ${highlighted ? "is-linked" : ""}`} onClick={onOpen} aria-label={`Open order ${titleOf(order)}, ${statusLabel(order.status)}`}>
    <span className="workspace-card-top"><span className="eyebrow">{order.asset_type === "ton_nft" ? "TON NFT" : "TELEGRAM GIFT"}</span><span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span></span>
    <strong className="workspace-card-title">{titleOf(order)}</strong><span className="workspace-card-price">{order.price_amount} {order.price_currency}</span>
    <span className="workspace-card-bottom">{role === "buyer" ? "Purchase" : "Sale"} · {dateLabel(order.created_at)} <span aria-hidden="true">↗</span></span>
  </button>;
}
export function Orders({ accessToken, userId, initialOrderId = null, onCatalog }: { accessToken: string; userId?: string; initialOrderId?: string | null; onCatalog?: () => void }) {
  const [role, setRole] = useState<OrderRole>("buyer"), [orders, setOrders] = useState<MarketplaceOrder[]>([]);
  const [selected, setSelected] = useState<MarketplaceOrder | null>(null), [linked, setLinked] = useState<MarketplaceOrder | null>(null);
  const [loading, setLoading] = useState(true), [error, setError] = useState(""), [detailError, setDetailError] = useState("");
  const [actionError, setActionError] = useState(""), [busyId, setBusyId] = useState(""), [retry, setRetry] = useState(0);
  const [search, setSearch] = useState(""), [filter, setFilter] = useState<StatusFilter>("all"), [sort, setSort] = useState<SortMode>("newest");
  useEffect(() => {
    if (!initialOrderId || !userId) { setLinked(null); return; }
    const controller = new AbortController();
    fetchOrder(initialOrderId, accessToken, controller.signal).then(order => {
      if (order.buyer_id !== userId && order.seller_id !== userId) throw new Error("This order is not available for this account.");
      setLinked(order); setSelected(order); setRole(order.buyer_id === userId ? "buyer" : "seller");
    }).catch((reason: unknown) => { if (!controller.signal.aborted) setDetailError(reason instanceof Error ? reason.message : "Unable to open this order."); });
    return () => controller.abort();
  }, [initialOrderId, userId, accessToken]);
  useEffect(() => {
    const controller = new AbortController(); setLoading(true); setError("");
    fetchOrders(role, accessToken, controller.signal).then(setOrders).catch((reason: unknown) => {
      if (!controller.signal.aborted) { setError(reason instanceof Error ? reason.message : "Unable to load orders."); setOrders([]); }
    }).finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [role, accessToken, retry]);
  async function openOrder(order: MarketplaceOrder) {
    setSelected(order); setDetailError("");
    try {
      const detail = await fetchOrder(order.id, accessToken);
      if (userId && detail.buyer_id !== userId && detail.seller_id !== userId) throw new Error("This order is not available for this account.");
      setSelected(detail); setOrders(current => current.map(item => item.id === detail.id ? detail : item));
    } catch (reason) { setDetailError(reason instanceof Error ? reason.message : "Unable to load order details."); }
  }
  async function handleCancel(id: string) {
    setBusyId(id); setActionError("");
    try {
      const updated = await cancelOrder(id, accessToken);
      setOrders(current => current.map(order => order.id === updated.id ? updated : order));
      setLinked(current => current?.id === updated.id ? updated : current); setSelected(current => current?.id === updated.id ? updated : current);
    } catch (reason) { setActionError(reason instanceof Error ? reason.message : "Unable to cancel this order."); }
    finally { setBusyId(""); }
  }
  const counts = useMemo(() => ({
    all: orders.length,
    active: orders.filter(o => ["reserved","awaiting_transfer","observing_transfer"].includes(o.status)).length,
    completed: orders.filter(o => o.status === "completed").length,
    closed: orders.filter(o => o.status === "cancelled" || o.status === "expired").length,
  }), [orders]);
  const visible = useMemo(() => {
    const source = linked ? [linked, ...orders.filter(o => o.id !== linked.id)] : orders;
    const query = search.trim().toLowerCase();
    return source.filter(o => (!query || titleOf(o).toLowerCase().includes(query) || o.id.toLowerCase().includes(query)) &&
      (filter === "all" || (filter === "active" && ["reserved","awaiting_transfer","observing_transfer"].includes(o.status)) || (filter === "completed" && o.status === "completed") || (filter === "closed" && (o.status === "cancelled" || o.status === "expired"))))
      .sort((a,b) => sort === "price" ? Number(b.price_amount)-Number(a.price_amount) : (sort === "newest" ? 1 : -1) * (timestamp(b.created_at)-timestamp(a.created_at)));
  }, [orders, linked, search, filter, sort]);
  if (selected) return <div className="orders-detail-wrap">
    {detailError && <p className="orders-error" role="alert">{detailError}<button className="text-button" type="button" onClick={()=>void openOrder(selected)}>Retry</button></p>}
    <OrderDetails order={selected} role={userId ? (selected.buyer_id === userId ? "buyer" : "seller") : role} busy={busyId === selected.id} onBack={()=>setSelected(null)} onCancel={id=>void handleCancel(id)}/>
  </div>;
  return <section className="orders-view" aria-labelledby="orders-title">
    <header className="workspace-heading"><div><p className="eyebrow">YOUR MARKETPLACE ACTIVITY</p><h1 id="orders-title">Order workspace</h1><p>Track reservations, transfers and completed orders.</p></div><button className="secondary-button" type="button" disabled={loading} onClick={()=>setRetry(v=>v+1)}>↻ Refresh</button></header>
    <div className="workspace-role-tabs" role="tablist" aria-label="Order type">
      <button role="tab" aria-selected={role==="buyer"} type="button" onClick={()=>{setRole("buyer");setFilter("all");}}>Purchases <span>{role==="buyer"?counts.all:"—"}</span></button>
      <button role="tab" aria-selected={role==="seller"} type="button" onClick={()=>{setRole("seller");setFilter("all");}}>Sales <span>{role==="seller"?counts.all:"—"}</span></button>
    </div>
    {actionError && <p className="orders-error" role="alert">{actionError}</p>}
    <div className="workspace-toolbar"><label className="workspace-search"><span aria-hidden="true">⌕</span><span className="sr-only">Search by asset title or order ID</span><input type="search" value={search} onChange={e=>setSearch(e.target.value)} placeholder="Search title or order ID"/></label><label><span className="sr-only">Sort orders</span><select value={sort} onChange={e=>setSort(e.target.value as SortMode)}><option value="newest">Newest first</option><option value="oldest">Oldest first</option><option value="price">Highest price</option></select></label></div>
    <div className="workspace-filters" role="group" aria-label="Filter orders by status">
      {([{value:"all",label:"All",count:counts.all},{value:"active",label:"Active",count:counts.active},{value:"completed",label:"Completed",count:counts.completed},{value:"closed",label:"Cancelled / expired",count:counts.closed}] as const).map(item=><button key={item.value} type="button" className={filter===item.value?"is-active":""} aria-pressed={filter===item.value} onClick={()=>setFilter(item.value)}>{item.label}<span>{item.count}</span></button>)}
    </div>
    {loading ? <div className="workspace-order-grid" role="status" aria-label="Loading orders" aria-busy="true">{[1,2,3,4].map(n=><div className="workspace-skeleton" key={n}><i/><i/><i/><i/></div>)}</div>
      : error ? <div className="workspace-empty" role="alert"><span className="workspace-empty-mark">!</span><h2>Orders unavailable</h2><p>{error}</p><button className="primary-button" type="button" onClick={()=>setRetry(v=>v+1)}>Try again</button></div>
      : visible.length===0 ? <div className="workspace-empty" role="status"><span className="workspace-empty-mark">◇</span><h2>{search||filter!=="all"?"No matching orders":`No ${role==="buyer"?"purchases":"sales"} yet`}</h2><p>{search||filter!=="all"?"Try another search or status filter.":"Your order activity will appear here after you reserve a listing or make a sale."}</p>{search||filter!=="all"?<button className="secondary-button" type="button" onClick={()=>{setSearch("");setFilter("all");}}>Clear filters</button>:onCatalog?<button className="primary-button" type="button" onClick={onCatalog}>Explore catalog</button>:null}</div>
      : <><p className="workspace-results-count">{visible.length} {visible.length===1?"order":"orders"}</p><div className="workspace-order-grid">{visible.map(order=><OrderCard key={order.id} order={order} role={role} highlighted={order.id===linked?.id} onOpen={()=>void openOrder(order)}/>)}</div></>}
  </section>;
}
