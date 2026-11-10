import { useEffect, useState } from "react";

import { cancelOrder, fetchOrders, type MarketplaceOrder, type OrderRole } from "../api/orders";

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
    case "pending_payment": return "Payment pending";
    case "cancelled": return "Cancelled";
    case "expired": return "Expired";
  }
}

export function Orders({ accessToken }: { accessToken: string }) {
  const [role, setRole] = useState<OrderRole>("buyer");
  const [orders, setOrders] = useState<MarketplaceOrder[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [actionError, setActionError] = useState("");
  const [busyOrderId, setBusyOrderId] = useState("");
  const [retry, setRetry] = useState(0);

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
    } catch (reason) {
      setActionError(reason instanceof Error ? reason.message : "Unable to cancel this order.");
    } finally {
      setBusyOrderId("");
    }
  }

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
      ) : orders.length === 0 ? (
        <div className="orders-message" role="status">
          <h2>No {role === "buyer" ? "purchases" : "sales"} yet</h2>
          <p>Order activity will appear here.</p>
        </div>
      ) : (
        <div className="orders-list">
          {orders.map((order) => (
            <article className="order-card" key={order.id}>
              <div className="order-card-heading">
                <h2>{getOrderTitle(order)}</h2>
                <span className={`order-status order-status-${order.status}`}>{statusLabel(order.status)}</span>
              </div>
              <p className="order-card-price">{order.price_amount} {order.price_currency}</p>
              <p className="order-card-note">
                {order.status === "pending_payment"
                  ? "Payment processing is not enabled. The listing remains reserved until this order is cancelled or expires."
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
              {role === "buyer" && order.status === "pending_payment" && (
                <button
                  className="text-button"
                  type="button"
                  disabled={busyOrderId === order.id}
                  onClick={() => void handleCancel(order.id)}
                >
                  {busyOrderId === order.id ? "Cancelling..." : "Cancel order"}
                </button>
              )}
            </article>
          ))}
        </div>
      )}
    </section>
  );
}
