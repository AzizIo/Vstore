import { useEffect, useState } from "react";

import { fetchSellerOverview, type SellerActivityItem, type SellerOverview } from "../api/overview";

interface Props {
  accessToken: string;
  onOpenOrders: (orderId?: string) => void;
  onOpenListing: (listingId: string) => void;
}

function formatDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function statusLabel(status: string) {
  const labels: Record<string, string> = {
    draft: "Draft",
    active: "Active",
    reserved: "Reserved",
    sold: "Sold",
    cancelled: "Cancelled",
    expired: "Expired",
    awaiting_transfer: "Awaiting transfer",
    observing_transfer: "Verifying transfer",
    completed: "Completed",
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
      <span className="seller-activity-kind">{isOrder ? (item.role === "buyer" ? "BUY" : "SALE") : "LISTING"}</span>
      <span className="seller-activity-main">
        <strong>{item.title}</strong>
        <span>{isOrder ? "Order" : "Listing"} · {statusLabel(item.status)} · {formatDate(item.created_at)}</span>
      </span>
      <span className="seller-activity-price">{item.price_amount} {item.price_currency}</span>
      <span className="seller-activity-arrow" aria-hidden="true">↗</span>
    </button>
  );
}

export function SellerOverview({ accessToken, onOpenOrders, onOpenListing }: Props) {
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
          setError(reason instanceof Error ? reason.message : "Unable to load your seller overview.");
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [accessToken, retry]);

  if (loading) {
    return <section className="seller-overview-message" role="status" aria-busy="true">Loading seller overview…</section>;
  }
  if (error || !overview) {
    return (
      <section className="seller-overview-message" role="alert">
        <h2>Overview unavailable</h2>
        <p>{error || "The seller overview could not be loaded."}</p>
        <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Try again</button>
      </section>
    );
  }

  const listingCards = [
    { label: "Active listings", value: overview.listings.active },
    { label: "Reserved listings", value: overview.listings.reserved },
    { label: "Drafts", value: overview.listings.draft },
    { label: "All listings", value: overview.listings.total },
  ];
  const orderCards = [
    { label: "Orders received", value: overview.orders_as_seller.total },
    { label: "Orders placed", value: overview.orders_as_buyer.total },
    { label: "Awaiting transfer", value: overview.orders_as_seller.awaiting_transfer + overview.orders_as_seller.reserved + overview.orders_as_seller.observing_transfer },
    { label: "Completed transfers", value: overview.orders_as_seller.completed },
  ];

  return (
    <section className="seller-overview" aria-labelledby="seller-overview-title">
      <div className="seller-overview-heading">
        <div>
          <p className="eyebrow">YOUR MARKETPLACE</p>
          <h1 id="seller-overview-title">Seller overview</h1>
          <p>Store activity, reservations and order progress in one place.</p>
        </div>
        <button className="refresh-button" type="button" onClick={() => setRetry((value) => value + 1)}>Refresh</button>
      </div>

      <section className="seller-overview-section" aria-labelledby="seller-listings-heading">
        <div className="seller-overview-section-heading">
          <h2 id="seller-listings-heading">Listings</h2>
          <button className="text-button" type="button" onClick={() => onOpenListing("")}>Manage listings ↗</button>
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
          <h2 id="seller-orders-heading">Orders</h2>
          <button className="text-button" type="button" onClick={() => onOpenOrders()}>Open orders ↗</button>
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
            <span>Reserved order-price snapshots</span>
            <strong>{formatSnapshots(overview.reserved_order_snapshot_values)}</strong>
          </article>
          <article>
            <span>Completed order-price snapshots</span>
            <strong>{formatSnapshots(overview.completed_order_snapshot_values)}</strong>
          </article>
        </div>
        <p className="seller-overview-disclaimer">
          These figures are listing/order price snapshots only. Reservations are not payments; no funds are collected or held by VILTARA.
        </p>
      </section>

      <section className="seller-overview-section" aria-labelledby="seller-activity-heading">
        <div className="seller-overview-section-heading">
          <h2 id="seller-activity-heading">Recent activity</h2>
          <span>{overview.recent_activity.length} recent items</span>
        </div>
        {overview.recent_activity.length ? (
          <div className="seller-activity-list">
            {overview.recent_activity.map((item) => (
              <ActivityRow key={`${item.kind}-${item.id}`} item={item} onOpenOrders={onOpenOrders} onOpenListing={onOpenListing} />
            ))}
          </div>
        ) : (
          <div className="seller-overview-empty">
            <h3>No activity yet</h3>
            <p>Create your first listing or reserve an item to see activity here.</p>
          </div>
        )}
      </section>
    </section>
  );
}
