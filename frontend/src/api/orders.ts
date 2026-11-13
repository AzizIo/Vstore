import { API_BASE_URL } from "./config";
import type { AssetType, PriceCurrency } from "./listings";

export type OrderStatus = "reserved" | "awaiting_transfer" | "observing_transfer" | "completed" | "cancelled" | "expired";
export type OrderRole = "buyer" | "seller";
export type DeliveryAttemptStatus = "prepared" | "observing" | "verified" | "failed" | "manual_review" | "cancelled";

export interface DeliveryAttempt {
  id: string;
  status: DeliveryAttemptStatus;
  network: "mainnet" | "testnet";
  item_address: string;
  seller_address: string;
  buyer_address: string;
  query_id: string;
  prepared_at: string;
  deadline: string;
  submitted_at: string | null;
  candidate_transaction_hash: string | null;
  transaction_hash: string | null;
  trace_id: string | null;
  masterchain_seqno: number | null;
  verified_at: string | null;
}

export interface OrderDeliveryState {
  order_id: string;
  order_status: OrderStatus;
  attempt: DeliveryAttempt | null;
}

export interface OrderEvent {
  from_status: OrderStatus | null;
  to_status: OrderStatus;
  actor_type: "buyer" | "seller" | "system";
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
  return value === "reserved" || value === "awaiting_transfer" || value === "observing_transfer" || value === "completed" || value === "cancelled" || value === "expired";
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
      (["buyer", "seller", "system"] as string[]).includes((event as OrderEvent).actor_type) &&
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
    throw new Error("Не удалось связаться с сервисом заказов. Попробуйте ещё раз.");
  }

  if (!response.ok) {
    let message = `Запрос завершился ошибкой (${response.status}).`;
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
    throw new Error("Сервис заказов вернул некорректный ответ.");
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
  if (!isOrder(order)) throw new Error("Сервис заказов вернул некорректные данные заказа.");
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
    throw new Error("Сервис заказов вернул некорректный список.");
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
  if (!isOrder(order)) throw new Error("Сервис заказов вернул некорректные данные заказа.");
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
  if (!isOrder(order)) throw new Error("Сервис заказов вернул некорректные данные заказа.");
  return order;
}



function isDeliveryAttempt(value: unknown): value is DeliveryAttempt {
  if (!value || typeof value !== "object") return false;
  const attempt = value as Partial<DeliveryAttempt>;
  return typeof attempt.id === "string" &&
    ["prepared", "observing", "verified", "failed", "manual_review", "cancelled"].includes(String(attempt.status)) &&
    (attempt.network === "mainnet" || attempt.network === "testnet") &&
    typeof attempt.item_address === "string" &&
    typeof attempt.seller_address === "string" &&
    typeof attempt.buyer_address === "string" &&
    typeof attempt.query_id === "string" &&
    typeof attempt.prepared_at === "string" &&
    typeof attempt.deadline === "string";
}

function isDeliveryState(value: unknown): value is OrderDeliveryState {
  if (!value || typeof value !== "object") return false;
  const state = value as Partial<OrderDeliveryState>;
  return typeof state.order_id === "string" &&
    isOrderStatus(state.order_status) &&
    (state.attempt === null || isDeliveryAttempt(state.attempt));
}

async function requestDeliveryState(
  url: string,
  accessToken: string,
  init?: RequestInit,
): Promise<OrderDeliveryState> {
  const state = await requestJson<unknown>(url, accessToken, init);
  if (!isDeliveryState(state)) throw new Error("Сервис заказов вернул некорректный статус передачи.");
  return state;
}

export async function fetchDeliveryState(
  orderId: string,
  accessToken: string,
  signal?: AbortSignal,
): Promise<OrderDeliveryState> {
  return requestDeliveryState(
    `${API_BASE_URL}/api/orders/${encodeURIComponent(orderId)}/delivery`,
    accessToken,
    { signal },
  );
}

export async function prepareDelivery(
  orderId: string,
  sellerWalletId: string,
  accessToken: string,
  idempotencyKey: string,
): Promise<OrderDeliveryState> {
  return requestDeliveryState(
    `${API_BASE_URL}/api/orders/${encodeURIComponent(orderId)}/delivery/prepare`,
    accessToken,
    {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        "Idempotency-Key": idempotencyKey,
      },
      body: JSON.stringify({ seller_wallet_id: sellerWalletId }),
    },
  );
}

export async function submitDeliveryCandidate(
  orderId: string,
  transactionHash: string,
  accessToken: string,
): Promise<OrderDeliveryState> {
  return requestDeliveryState(
    `${API_BASE_URL}/api/orders/${encodeURIComponent(orderId)}/delivery/submissions`,
    accessToken,
    {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ transaction_hash: transactionHash }),
    },
  );
}
