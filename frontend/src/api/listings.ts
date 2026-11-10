import { API_BASE_URL } from "./config";

export type AssetType = "ton_nft" | "telegram_gift";
export type PriceCurrency = "TON" | "XTR";
export type ListingSort = "newest" | "price_asc" | "price_desc";

export interface ListingCollection {
  id: string;
  address: string;
  network: string;
  name: string | null;
  marketplace_name: string | null;
}

export interface ListingAsset {
  id: string;
  asset_type: AssetType;
  external_id: string;
  item_address: string | null;
  name: string | null;
  description: string | null;
  image_url: string | null;
  verification_status: string;
  collection?: ListingCollection | null;
}

export interface ListingSeller {
  id: string;
  username: string | null;
  first_name: string;
}

export interface Listing {
  id: string;
  status: string;
  price_amount: string;
  price_currency: PriceCurrency;
  title: string | null;
  description: string | null;
  created_at: string;
  asset: ListingAsset;
  seller: ListingSeller;
}

export interface ListingPage {
  items: Listing[];
  total: number;
  limit: number;
  offset: number;
}

export interface ListingFilters {
  search: string;
  assetType: AssetType | "all";
  sort: ListingSort;
  limit?: number;
  offset?: number;
}

function isCollection(value: unknown): value is ListingCollection | null {
  if (value === null || value === undefined) return true;
  if (typeof value !== "object") return false;
  const collection = value as Partial<ListingCollection>;
  return (
    typeof collection.id === "string" &&
    typeof collection.address === "string" &&
    typeof collection.network === "string" &&
    (collection.name === null || typeof collection.name === "string") &&
    (collection.marketplace_name === null ||
      typeof collection.marketplace_name === "string")
  );
}

export function isListing(value: unknown): value is Listing {
  if (!value || typeof value !== "object") return false;
  const listing = value as Partial<Listing>;
  const asset = listing.asset;
  const seller = listing.seller;
  const nullableString = (field: unknown) => field === null || typeof field === "string";
  return (
    typeof listing.id === "string" &&
    typeof listing.status === "string" &&
    typeof listing.price_amount === "string" &&
    (listing.price_currency === "TON" || listing.price_currency === "XTR") &&
    nullableString(listing.title) && nullableString(listing.description) &&
    typeof listing.created_at === "string" &&
    !!asset && typeof asset.id === "string" &&
    (asset.asset_type === "ton_nft" || asset.asset_type === "telegram_gift") &&
    typeof asset.external_id === "string" &&
    nullableString(asset.item_address) && nullableString(asset.name) &&
    nullableString(asset.description) && nullableString(asset.image_url) &&
    typeof asset.verification_status === "string" &&
    isCollection(asset.collection) &&
    !!seller && typeof seller.id === "string" &&
    nullableString(seller.username) && typeof seller.first_name === "string"
  );
}

async function requestJson<T>(url: string, signal?: AbortSignal, headers?: HeadersInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { signal, headers });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Could not connect to the marketplace. Please try again.");
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // Retain the HTTP status message if the server response is not JSON.
    }
    throw new Error(message);
  }

  try {
    return (await response.json()) as T;
  } catch {
    throw new Error("The marketplace returned an invalid response.");
  }
}

export async function fetchListings(filters: ListingFilters, signal?: AbortSignal) {
  const limit = filters.limit ?? 24;
  const offset = filters.offset ?? 0;
  const params = new URLSearchParams({ limit: String(limit), offset: String(offset), sort: filters.sort });
  const search = filters.search.trim();
  if (search) params.set("search", search);
  if (filters.assetType !== "all") params.set("asset_type", filters.assetType);
  const page = await requestJson<unknown>(`${API_BASE_URL}/api/listings?${params}`, signal);
  if (
    !page || typeof page !== "object" || !Array.isArray((page as Partial<ListingPage>).items) ||
    !Number.isInteger((page as Partial<ListingPage>).total) ||
    (page as ListingPage).total < 0 ||
    (page as ListingPage).limit !== limit ||
    (page as ListingPage).offset !== offset ||
    (page as ListingPage).items.length > limit ||
    !(page as ListingPage).items.every(isListing)
  ) {
    throw new Error("The marketplace returned an invalid catalog response.");
  }
  return page as ListingPage;
}

export async function fetchListing(id: string, signal?: AbortSignal) {
  const listing = await requestJson<unknown>(`${API_BASE_URL}/api/listings/${encodeURIComponent(id)}`, signal);
  if (!isListing(listing)) throw new Error("The marketplace returned an invalid listing.");
  return listing;
}

export async function fetchMyListings(accessToken: string, signal?: AbortSignal): Promise<Listing[]> {
  const listings = await requestJson<unknown>(
    `${API_BASE_URL}/api/listings/me`,
    signal,
    { Authorization: `Bearer ${accessToken}` },
  );
  if (!Array.isArray(listings) || !listings.every(isListing)) {
    throw new Error("The marketplace returned an invalid listings response.");
  }
  return listings;
}

export interface ListingUpdate {
  price_amount?: string;
  title?: string | null;
  description?: string | null;
}

async function requestSellerListing(
  path: string,
  accessToken: string,
  init: RequestInit,
): Promise<Listing> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/listings/${path}`, {
      ...init,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(init.headers ?? {}),
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Could not connect to the marketplace. Please try again.");
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // Keep the HTTP status message when the server does not return JSON.
    }
    throw new Error(message);
  }

  let result: unknown;
  try {
    result = await response.json();
  } catch {
    throw new Error("The marketplace returned an invalid listing response.");
  }
  if (!isListing(result)) {
    throw new Error("The marketplace returned an invalid listing response.");
  }
  return result;
}

export async function publishListing(
  listingId: string,
  accessToken: string,
  signal?: AbortSignal,
): Promise<Listing> {
  return requestSellerListing(
    `${encodeURIComponent(listingId)}/publish`,
    accessToken,
    { method: "POST", signal },
  );
}

export async function updateListing(
  listingId: string,
  accessToken: string,
  payload: ListingUpdate,
  signal?: AbortSignal,
): Promise<Listing> {
  return requestSellerListing(
    encodeURIComponent(listingId),
    accessToken,
    {
      method: "PATCH",
      signal,
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    },
  );
}

export async function cancelListing(
  listingId: string,
  accessToken: string,
  signal?: AbortSignal,
): Promise<Listing> {
  return requestSellerListing(
    `${encodeURIComponent(listingId)}/cancel`,
    accessToken,
    { method: "POST", signal },
  );
}
