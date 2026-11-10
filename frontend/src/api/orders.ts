import { API_BASE_URL } from "./config";
import type { AssetType, PriceCurrency } from "./listings";

export type OrderStatus = "pending_payment" | "cancelled" | "expired";
export type OrderRole = "buyer" | "seller";

export interface OrderEvent {
  from_status: OrderStatus | null;
  to_status: OrderStatus;
  actor_type: "buyer" | "system";
  created_at: string;
}

export interface MarketplaceOrder {
  id: string;
  listing_id: string;
  buyer_id: string;
  seller_id: string;
  status: OrderStatus;
  price_amount: string;
  price_currency: PriceCurrency;
  title: string | null;
  asset_name: string | null;
  asset_type: AssetType;
  expires_at: string;
  created_at: string;
  updated_at: string;
  events: OrderEvent[];
}

function isOrderStatus(value: unknown): value is OrderStatus {
  return value === "pending_payment" || value === "cancelled" || value === "expired";
}

function isOrder(value: unknown): value is MarketplaceOrder {
  if (!value || typeof value !== "object") return false;
  const order = value as Partial<MarketplaceOrder>;
  return (
    typeof order.id === "string" &&
    typeof order.listing_id === "string" &&
    typeof order.buyer_id === "string" &&
    typeof order.seller_id === "string" &&
    isOrderStatus(order.status) &&
    typeof order.price_amount === "string" &&
    (order.price_currency === "TON" || order.price_currency === "XTR") &&
    (order.title === null || typeof order.title === "string") &&
    (order.asset_name === null || typeof order.asset_name === "string") &&
    (order.asset_type === "ton_nft" || order.asset_type === "telegram_gift") &&
    typeof order.expires_at === "string" &&
    typeof order.created_at === "string" &&
    typeof order.updated_at === "string" &&
    Array.isArray(order.events) &&
    order.events.every((event) =>
      !!event && typeof event === "object" &&
      ((event as OrderEvent).from_status === null || isOrderStatus((event as OrderEvent).from_status)) &&
      isOrderStatus((event as OrderEvent).to_status) &&
      ((event as OrderEvent).actor_type === "buyer" || (event as OrderEvent).actor_type === "system") &&
      typeof (event as OrderEvent).created_at === "string"
    )
  );
}

async function requestJson<T>(url: string, accessToken: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(init?.headers ?? {}),
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Could not connect to orders. Please try again.");
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // Keep the HTTP status message when the response is not JSON.
    }
    throw new Error(message);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new Error("Orders returned an invalid response.");
  }
}

export async function createOrder(
  listingId: string,
  accessToken: string,
  idempotencyKey: string,
): Promise<MarketplaceOrder> {
  const order = await requestJson<unknown>(`${API_BASE_URL}/api/orders`, accessToken, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
    },
    body: JSON.stringify({ listing_id: listingId }),
  });
  if (!isOrder(order)) throw new Error("Orders returned an invalid order.");
  return order;
}

export async function fetchOrders(
  role: OrderRole,
  accessToken: string,
  signal?: AbortSignal,
): Promise<MarketplaceOrder[]> {
  const response = await requestJson<unknown>(
    `${API_BASE_URL}/api/orders?role=${role}&limit=100`,
    accessToken,
    { signal },
  );
  if (
    !response || typeof response !== "object" ||
    !Array.isArray((response as { items?: unknown }).items) ||
    !(response as { items: unknown[] }).items.every(isOrder)
  ) {
    throw new Error("Orders returned an invalid list.");
  }
  return (response as { items: MarketplaceOrder[] }).items;
}

export async function cancelOrder(
  orderId: string,
  accessToken: string,
): Promise<MarketplaceOrder> {
  const order = await requestJson<unknown>(
    `${API_BASE_URL}/api/orders/${encodeURIComponent(orderId)}/cancel`,
    accessToken,
    { method: "POST" },
  );
  if (!isOrder(order)) throw new Error("Orders returned an invalid order.");
  return order;
}


export async function fetchOrder(
  orderId: string,
  accessToken: string,
  signal?: AbortSignal,
): Promise<MarketplaceOrder> {
  const order = await requestJson<unknown>(
    `${API_BASE_URL}/api/orders/${encodeURIComponent(orderId)}`,
    accessToken,
    { signal },
  );
  if (!isOrder(order)) throw new Error("Orders returned an invalid order.");
  return order;
}
