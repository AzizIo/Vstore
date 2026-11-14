import { getApiErrorMessage } from "../api/errors";
import { API_BASE_URL } from "../api/config";

export type ModerationAction = "approve" | "reject" | "suspend" | "restore";
export type ModerationStatus = "pending_review" | "active" | "reserved" | "sold" | "cancelled" | "expired" | "suspended";
export type ModerationReasonCode = "policy_violation" | "ownership_unverified" | "misleading_metadata" | "duplicate_listing" | "other";

export interface ModerationItem {
  id: string;
  status: ModerationStatus;
  title: string | null;
  price_amount: string;
  price_currency: string;
  created_at: string;
  expires_at: string | null;
  seller: { id: string; username: string | null; first_name: string };
  asset: { name: string | null; image_url: string | null; verification_status: string };
  queue_reasons: string[];
}
export interface AuditEntry {
  id: string; actor_id: string; target_type: string; target_id: string; action: string;
  reason_code: ModerationReasonCode; reason: string; before_snapshot: Record<string, unknown>;
  after_snapshot: Record<string, unknown>; request_id: string | null; idempotency_key: string; occurred_at: string;
}
export interface Page<T> { items: T[]; total: number; limit: number; offset: number; }

async function request<T>(path: string, accessToken: string, init: RequestInit = {}): Promise<T> {
  let response: Response;
  try {
    response = await fetch(API_BASE_URL + "/api/admin" + path, {
      ...init, headers: { Authorization: "Bearer " + accessToken, ...(init.headers ?? {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Не удалось связаться с сервисом модерации. Попробуйте ещё раз.");
  }
  if (!response.ok) {
    let message = "Ошибка запроса модерации (" + response.status + ").";
    try {
      const body: unknown = await response.json();
      message = getApiErrorMessage(body, message);
    } catch { /* Keep HTTP status message. */ }
    const apiError = new Error(message) as Error & { status?: number };
    apiError.status = response.status;
    throw apiError;
  }
  try { return await response.json() as T; }
  catch { throw new Error("Сервис модерации вернул некорректные данные."); }
}
export async function fetchAdminAccess(accessToken: string, signal?: AbortSignal): Promise<boolean> {
  const result = await request<{ is_admin: boolean }>("/access", accessToken, { signal });
  return result.is_admin === true;
}
export function fetchModerationQueue(accessToken: string, options: { limit: number; offset: number; status?: string }, signal?: AbortSignal): Promise<Page<ModerationItem>> {
  const params = new URLSearchParams({ limit: String(options.limit), offset: String(options.offset) });
  if (options.status) params.set("status", options.status);
  return request("/moderation?" + params.toString(), accessToken, { signal });
}
export function fetchAuditHistory(accessToken: string, listingId: string, signal?: AbortSignal): Promise<Page<AuditEntry>> {
  return request("/listings/" + encodeURIComponent(listingId) + "/audit?limit=25&offset=0", accessToken, { signal });
}
export function submitModerationDecision(accessToken: string, listingId: string, input: { action: ModerationAction; reason_code: ModerationReasonCode; reason: string }, idempotencyKey = crypto.randomUUID()): Promise<AuditEntry> {
  return request("/listings/" + encodeURIComponent(listingId) + "/decision", accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json", "Idempotency-Key": idempotencyKey, "X-Request-ID": crypto.randomUUID() },
    body: JSON.stringify(input),
  });
}

export function fetchAdminAuditLog(
  accessToken: string,
  options: { limit: number; offset: number; action?: string } = { limit: 25, offset: 0 },
  signal?: AbortSignal,
): Promise<Page<AuditEntry>> {
  const params = new URLSearchParams({
    limit: String(options.limit),
    offset: String(options.offset),
  });
  if (options.action) params.set("action", options.action);
  return request("/audit?" + params.toString(), accessToken, { signal });
}


export interface AdminUser {
  id: string;
  first_name: string;
  last_name: string | null;
  username: string | null;
  telegram_id: number;
  registered_at: string;
  is_blocked: boolean;
  listing_count: number;
  deal_count: number;
  confirmed_wallet_count: number;
}
export interface AdminUserDetail extends AdminUser {
  verified_wallets: Array<{
    address_short: string;
    network: string;
    is_primary: boolean;
  }>;
}
export interface AdminUserListing {
  id: string;
  status: string;
  title: string | null;
  asset_name: string | null;
  price_amount: string;
  price_currency: string;
  created_at: string;
  updated_at: string;
  expires_at: string | null;
}
export interface AdminUserOrder {
  id: string;
  role: "buyer" | "seller";
  status: string;
  listing_id: string;
  listing_title: string | null;
  asset_name: string | null;
  counterparty_name: string;
  counterparty_username: string | null;
  price_amount: string;
  price_currency: string;
  created_at: string;
  updated_at: string;
  delivery_status: string | null;
  delivery_verified_at: string | null;
}
export interface AdminOrder {
  id: string;
  listing_id: string;
  listing_title: string | null;
  asset_name: string | null;
  buyer_id: string;
  buyer_name: string;
  buyer_username: string | null;
  seller_id: string;
  seller_name: string;
  seller_username: string | null;
  price_amount: string;
  price_currency: string;
  status: string;
  created_at: string;
  updated_at: string;
  delivery_status: string | null;
  delivery_verified_at: string | null;
}
export interface AdminUserAuditEntry {
  id: string;
  actor_id: string;
  target_user_id?: string;
  target_type?: "listing" | "user";
  target_id: string;
  action: string;
  reason_code: string | null;
  reason: string;
  before_snapshot: Record<string, unknown>;
  after_snapshot: Record<string, unknown>;
  request_id: string | null;
  idempotency_key: string;
  occurred_at: string;
}
export interface AdminPlatformEvent {
  id: string;
  entity_type: "order" | "listing_moderation" | "user_access";
  entity_id: string;
  summary: string;
  occurred_at: string;
}
export interface AdminOverview {
  counts: {
    total_users: number;
    new_users_24h: number;
    new_users_7d: number;
    blocked_users: number;
    unblocked_users: number;
    total_listings: number;
    active_listings: number;
    listings_on_moderation: number;
    reserved_listings: number;
    completed_deals: number;
    deals_in_progress: number;
  };
  recent_registrations: AdminUser[];
  recent_platform_events: AdminPlatformEvent[];
}
export interface AdminUserAccessAuditRecord {
  id: string;
  actor_id: string;
  target_user_id: string;
  action: "blocked" | "unblocked";
  reason: string;
  before_snapshot: Record<string, unknown>;
  after_snapshot: Record<string, unknown>;
  request_id: string | null;
  idempotency_key: string;
  occurred_at: string;
}
export interface AdminUserAccessDecision {
  user_id: string;
  is_blocked: boolean;
  audit: AdminUserAccessAuditRecord;
}
export type AdminAuditLogEntry = {
  id: string;
  target_type: "listing" | "user";
  target_id: string;
  actor_id: string;
  action: string;
  reason_code: string | null;
  reason: string;
  before_snapshot: Record<string, unknown>;
  after_snapshot: Record<string, unknown>;
  request_id: string | null;
  idempotency_key: string;
  occurred_at: string;
};

function adminParams(options: Record<string, string | number | boolean | undefined | null>) {
  const params = new URLSearchParams();
  for (const [key, value] of Object.entries(options)) {
    if (value !== undefined && value !== null && value !== "") {
      params.set(key, String(value));
    }
  }
  return params;
}

export function fetchAdminOverview(accessToken: string, signal?: AbortSignal): Promise<AdminOverview> {
  return request("/overview", accessToken, { signal });
}

export function fetchAdminUsers(
  accessToken: string,
  options: {
    limit: number;
    offset: number;
    q?: string;
    blocked?: boolean | null;
    sort_by?: "registered_at" | "listings" | "deals";
    sort_order?: "asc" | "desc";
  },
  signal?: AbortSignal,
): Promise<Page<AdminUser>> {
  const params = adminParams(options);
  return request("/users?" + params.toString(), accessToken, { signal });
}

export function fetchAdminUserDetail(accessToken: string, userId: string, signal?: AbortSignal): Promise<AdminUserDetail> {
  return request("/users/" + encodeURIComponent(userId), accessToken, { signal });
}

export function fetchAdminUserListings(
  accessToken: string,
  userId: string,
  options: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<Page<AdminUserListing>> {
  return request(
    "/users/" + encodeURIComponent(userId) + "/listings?" + adminParams(options).toString(),
    accessToken,
    { signal },
  );
}

export function fetchAdminUserOrders(
  accessToken: string,
  userId: string,
  options: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<Page<AdminUserOrder>> {
  return request(
    "/users/" + encodeURIComponent(userId) + "/orders?" + adminParams(options).toString(),
    accessToken,
    { signal },
  );
}

export function fetchAdminUserAudit(
  accessToken: string,
  userId: string,
  options: { limit: number; offset: number },
  signal?: AbortSignal,
): Promise<Page<AdminAuditLogEntry>> {
  return request(
    "/users/" + encodeURIComponent(userId) + "/audit?" + adminParams(options).toString(),
    accessToken,
    { signal },
  );
}

export function fetchAdminOrders(
  accessToken: string,
  options: { limit: number; offset: number; q?: string; status?: string },
  signal?: AbortSignal,
): Promise<Page<AdminOrder>> {
  return request("/orders?" + adminParams(options).toString(), accessToken, { signal });
}

export function fetchCombinedAdminAuditLog(
  accessToken: string,
  options: {
    limit: number;
    offset: number;
    target_type?: "listing" | "user";
    action?: string;
  },
  signal?: AbortSignal,
): Promise<Page<AdminAuditLogEntry>> {
  return request("/audit-log?" + adminParams(options).toString(), accessToken, { signal });
}

export function submitUserAccessDecision(
  accessToken: string,
  userId: string,
  action: "block" | "unblock",
  reason: string,
  idempotencyKey: string = crypto.randomUUID(),
): Promise<AdminUserAccessDecision> {
  return request("/users/" + encodeURIComponent(userId) + "/" + action, accessToken, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      "Idempotency-Key": idempotencyKey,
      "X-Request-ID": crypto.randomUUID(),
    },
    body: JSON.stringify({ reason }),
  });
}
