import { API_BASE_URL } from "../api/config";

export type ModerationAction = "approve" | "reject" | "suspend" | "restore";
export type ModerationStatus = "draft" | "active" | "reserved" | "sold" | "cancelled" | "expired" | "suspended";
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
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") message = body.detail;
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
