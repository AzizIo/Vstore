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
    case "reserved": return "Reservation pending";
    case "awaiting_transfer": return "Awaiting transfer";
    case "observing_transfer": return "Verifying transfer";
    case "completed": return "Completed";
    case "cancelled": return "Cancelled";
    case "expired": return "Expired";
  }
}
function guidance(status: OrderStatus, order?: MarketplaceOrder) {
  switch (status) {
    case "reserved": return "The listing is reserved. NFT transfer has not started. Payments are not enabled.";
    case "awaiting_transfer": return "The seller is preparing the direct NFT transfer to the verified buyer wallet.";
    case "observing_transfer": return "The transfer is being independently checked on TON. Do not treat it as delivered yet.";
    case "completed": return "The exact NFT transfer to the buyer was confirmed by the server.";
    case "cancelled": return `Order cancelled on ${dateLabel(order?.updated_at ?? "")}.`;
    case "expired": return `Order expired on ${dateLabel(order?.updated_at ?? "")}.`;
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
          {terminal ? <div className={`lifecycle-terminal lifecycle-${order.status}`}><strong>{statusLabel(order.status)}</strong><p>{guidance(order.status, order)}</p></div> :
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
function OrderCard({ order, role, onOpen, onCancel, busy, highlighted }: { order: MarketplaceOrder; role: OrderRole; onOpen: () => void; onCancel: (id: string) => void; busy: boolean; highlighted: boolean }) {
  const [confirmCancel, setConfirmCancel] = useState(false);
  return <article className={`workspace-order-card-wrap ${highlighted ? "is-linked" : ""}`}>
    <button type="button" className="workspace-order-open" onClick={onOpen} aria-label={`Open order ${titleOf(order)}, ${statusLabel(order.status)}`}>
      <span className="workspace-card-top"><span className="eyebrow">{order.asset_type === "ton_nft" ? "TON NFT" : "TELEGRAM GIFT"}</span><span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span></span>
      <strong className="workspace-card-title">{titleOf(order)}</strong><span className="workspace-card-price">{order.price_amount} {order.price_currency}</span>
      <span className="workspace-card-guidance">{guidance(order.status, order)}</span>
      <span className="workspace-card-bottom">{role === "buyer" ? "Purchase" : "Sale"} · {dateLabel(order.created_at)} <span aria-hidden="true">↗</span></span>
    </button>
    {role === "buyer" && order.status === "reserved" && (!confirmCancel
      ? <div className="workspace-card-actions"><button className="text-button" type="button" onClick={()=>setConfirmCancel(true)}>Cancel order</button></div>
      : <div className="workspace-card-confirm" role="group" aria-label="Confirm order cancellation"><span>Cancel this reservation?</span><button className="danger-button" type="button" disabled={busy} onClick={()=>onCancel(order.id)}>{busy ? "Cancelling…" : "Confirm cancel"}</button><button className="secondary-button" type="button" disabled={busy} onClick={()=>setConfirmCancel(false)}>Keep order</button></div>)}
  </article>;
}
