import { useEffect, useState } from "react";

import {
  cancelOrder,
  fetchOrder,
  fetchOrders,
  type MarketplaceOrder,
  type OrderRole,
} from "../api/orders";

function getOrderTitle(order: MarketplaceOrder) {
  return order.title || order.asset_name || "Untitled asset";
}

function getDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium", timeStyle: "short" }).format(date);
}

function statusLabel(status: MarketplaceOrder["status"]) {
  switch (status) {
    case "reserved": return "Reserved";
    case "awaiting_transfer": return "Awaiting transfer";
    case "observing_transfer": return "Verifying transfer";
    case "completed": return "Completed";
    case "cancelled": return "Cancelled";
    case "expired": return "Expired";
  }
}

function OrderCard({
  order,
  role,
  busy,
  onCancel,
  highlighted = false,
}: {
  order: MarketplaceOrder;
  role: OrderRole;
  busy: boolean;
  onCancel: (orderId: string) => void;
  highlighted?: boolean;
}) {
  return (
    <article className={highlighted ? "order-card order-card-linked" : "order-card"}>
      {highlighted && <p className="eyebrow">OPENED FROM TELEGRAM NOTIFICATION</p>}
      <div className="order-card-heading">
        <h2>{getOrderTitle(order)}</h2>
        <span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span>
      </div>
      <p className="order-card-price">{order.price_amount} {order.price_currency}</p>
      <p className="order-card-note">
        {order.status === "reserved"
          ? "The listing is reserved. NFT transfer has not started. Payments are not enabled."
          : order.status === "awaiting_transfer"
            ? "The seller is preparing the direct NFT transfer to the verified buyer wallet."
            : order.status === "observing_transfer"
              ? "The transfer is being independently checked on TON. Do not treat it as delivered yet."
              : order.status === "completed"
                ? "The exact NFT transfer to the buyer was confirmed by the server."
                : `Order ${order.status} on ${getDate(order.updated_at)}.`}
      </p>
      <p className="order-card-date">Created {getDate(order.created_at)}</p>
      <ol className="order-history" aria-label="Order history">
        {order.events.map((event, index) => (
          <li key={`${event.to_status}-${event.created_at}-${index}`}>
            {statusLabel(event.to_status)} · {getDate(event.created_at)}
          </li>
        ))}
      </ol>
      {role === "buyer" && order.status === "reserved" && (
        <button
          className="text-button"
          type="button"
          disabled={busy}
          onClick={() => onCancel(order.id)}
        >
          {busy ? "Cancelling..." : "Cancel order"}
        </button>
      )}
    </article>
  );
}

export function Orders({
  accessToken,
  userId,
  initialOrderId = null,
}: {
  accessToken: string;
  userId?: string;
  initialOrderId?: string | null;
}) {
  const [role, setRole] = useState<OrderRole>("buyer");
  const [orders, setOrders] = useState<MarketplaceOrder[]>([]);
  const [linkedOrder, setLinkedOrder] = useState<MarketplaceOrder | null>(null);
  const [linkedOrderError, setLinkedOrderError] = useState("");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyOrderId, setBusyOrderId] = useState("");
  const [retry, setRetry] = useState(0);

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
      })
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setLinkedOrderError(
            reason instanceof Error ? reason.message : "Unable to open this order.",
          );
        }
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
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [accessToken, retry, role]);

  async function handleCancel(orderId: string) {
    setBusyOrderId(orderId);
    setActionError("");
    try {
      const updated = await cancelOrder(orderId, accessToken);
      setOrders((current) => current.map((order) => order.id === updated.id ? updated : order));
      setLinkedOrder((current) => current?.id === updated.id ? updated : current);
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Unable to cancel this order.");
    } finally {
      setBusyOrderId("");
    }
  }

  const visibleOrders = linkedOrder
    ? [linkedOrder, ...orders.filter((order) => order.id !== linkedOrder.id)]
    : orders;

  return (
    <section className="orders-view" aria-labelledby="orders-title">
      <div className="orders-heading">
        <div>
          <p className="eyebrow">ORDER ACTIVITY</p>
          <h1 id="orders-title">{role === "buyer" ? "My Orders" : "Sales"}</h1>
        </div>
        <label className="select-control">
          <span className="sr-only">Order role</span>
          <select value={role} onChange={(event) => setRole(event.target.value as OrderRole)}>
            <option value="buyer">Purchases</option>
            <option value="seller">Sales</option>
          </select>
        </label>
      </div>

      {actionError && <p className="orders-error" role="alert">{actionError}</p>}
      {linkedOrderError && <p className="orders-error" role="alert">{linkedOrderError}</p>}
      {loading ? (
        <p className="orders-message" role="status">Loading orders...</p>
      ) : error ? (
        <div className="orders-message" role="alert">
          <h2>Orders unavailable</h2>
          <p>{error}</p>
          <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>
            Try again
          </button>
        </div>
      ) : visibleOrders.length === 0 ? (
        <div className="orders-message" role="status">
          <h2>No {role === "buyer" ? "purchases" : "sales"} yet</h2>
          <p>Order activity will appear here.</p>
        </div>
      ) : (
        <div className="orders-list">
          {visibleOrders.map((order) => (
            <OrderCard
              key={order.id}
              order={order}
              role={role}
              busy={busyOrderId === order.id}
              onCancel={(orderId) => void handleCancel(orderId)}
              highlighted={order.id === linkedOrder?.id}
            />
          ))}
        </div>
      )}
    </section>
  );
}
