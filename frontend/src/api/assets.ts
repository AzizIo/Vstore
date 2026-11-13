import { getApiErrorMessage } from "./errors";
import { API_BASE_URL } from "./config";
import { isListing, type Listing, type ListingAsset, type PriceCurrency } from "./listings";

export interface InventoryAsset extends ListingAsset {
  item_address: string;
  collection_address: string | null;
  eligible_for_listing: boolean;
}

export interface InventoryPage {
  items: InventoryAsset[];
  wallet_id: string;
  limit: number;
  offset: number;
  next_offset: number;
  has_more: boolean;
}

export interface InventoryPageRequest {
  limit?: number;
  offset?: number;
  walletId?: string;
}

export interface InventorySyncResponse {
  wallet_id: string;
  synced_at: string;
  discovered_count: number;
  verified_count: number;
  stale_count: number;
  invalid_count: number;
  unsupported_count: number;
  cancelled_listing_count: number;
}

export interface CreateListingDraftRequest {
  asset_id: string;
  price_amount: string;
  price_currency: PriceCurrency;
  title?: string;
  description?: string;
  expires_at?: string | null;
}

async function requestJson<T>(url: string, accessToken: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...init?.headers,
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Не удалось связаться с сервисом объявлений. Попробуйте ещё раз.");
  }

  if (!response.ok) {
    let message = `Запрос завершился ошибкой (${response.status}).`;
    try {
      const body: unknown = await response.json();
      message = getApiErrorMessage(body, message);
    } catch {
      // Keep the HTTP status message if the server response is not JSON.
    }
    throw new Error(message);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new Error("Сервис объявлений вернул некорректный ответ.");
  }
}

function isInventoryAsset(value: unknown): value is InventoryAsset {
  if (!value || typeof value !== "object") return false;
  const asset = value as Partial<InventoryAsset>;
  return (
    typeof asset.id === "string" &&
    asset.asset_type === "ton_nft" &&
    typeof asset.external_id === "string" &&
    typeof asset.item_address === "string" &&
    (asset.collection_address === null || typeof asset.collection_address === "string") &&
    (asset.name === null || typeof asset.name === "string") &&
    (asset.description === null || typeof asset.description === "string") &&
    (asset.image_url === null || typeof asset.image_url === "string") &&
    asset.verification_status === "verified" &&
    asset.eligible_for_listing === true
  );
}

export async function fetchMyInventory(
  accessToken: string,
  pageRequest: InventoryPageRequest = {},
  signal?: AbortSignal,
): Promise<InventoryPage> {
  const limit = pageRequest.limit ?? 24;
  const offset = pageRequest.offset ?? 0;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset) });
  if (pageRequest.walletId) params.set("wallet_id", pageRequest.walletId);

  const page = await requestJson<unknown>(`${API_BASE_URL}/api/assets/me?${params}`, accessToken, { signal });
  if (!page || typeof page !== "object") {
    throw new Error("Сервис объявлений вернул некорректный инвентарь.");
  }
  const data = page as Partial<InventoryPage>;
  if (
    !Array.isArray(data.items) || !data.items.every(isInventoryAsset) ||
    typeof data.wallet_id !== "string" ||
    data.limit !== limit || data.offset !== offset ||
    !Number.isInteger(data.next_offset) || (data.next_offset ?? -1) < offset ||
    (data.has_more === true && (data.next_offset ?? offset) <= offset) ||
    data.items.length > limit ||
    typeof data.has_more !== "boolean"
  ) {
    throw new Error("Сервис объявлений вернул некорректный инвентарь.");
  }
  if (pageRequest.walletId && data.wallet_id !== pageRequest.walletId) {
    throw new Error("Сервис объявлений вернул инвентарь другого кошелька.");
  }
  return data as InventoryPage;
}

export async function createListingDraft(
  accessToken: string,
  payload: CreateListingDraftRequest,
  signal?: AbortSignal,
): Promise<Listing> {
  const listing = await requestJson<unknown>(`${API_BASE_URL}/api/listings`, accessToken, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    signal,
  });
  if (!isListing(listing) || listing.status !== "draft") {
    throw new Error("Сервис объявлений вернул некорректный ответ при создании черновика.");
  }
  return listing;
}


export async function syncMyInventory(
  accessToken: string,
  walletId?: string,
  signal?: AbortSignal,
): Promise<InventorySyncResponse> {
  const params = new URLSearchParams();
  if (walletId) params.set("wallet_id", walletId);
  const suffix = params.size ? `?${params.toString()}` : "";
  const response = await requestJson<unknown>(
    `${API_BASE_URL}/api/assets/me/sync${suffix}`,
    accessToken,
    { method: "POST", signal },
  );
  if (!response || typeof response !== "object") {
    throw new Error("Сервис объявлений вернул некорректный ответ синхронизации инвентаря.");
  }
  const result = response as Partial<InventorySyncResponse>;
  const countKeys = [
    "discovered_count",
    "verified_count",
    "stale_count",
    "invalid_count",
    "unsupported_count",
    "cancelled_listing_count",
  ] as const;
  if (
    typeof result.wallet_id !== "string" ||
    typeof result.synced_at !== "string" ||
    !Number.isFinite(Date.parse(result.synced_at)) ||
    countKeys.some((key) => !Number.isInteger(result[key]) || (result[key] ?? -1) < 0)
  ) {
    throw new Error("Сервис объявлений вернул некорректный ответ синхронизации инвентаря.");
  }
  return result as InventorySyncResponse;
}
