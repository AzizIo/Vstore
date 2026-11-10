import { API_BASE_URL } from "./config";

export type AssetType = "ton_nft" | "telegram_gift";
export type PriceCurrency = "TON" | "XTR";
export type ListingSort = "newest" | "price_asc" | "price_desc";

export interface ListingAsset {
  id: string;
  asset_type: AssetType;
  external_id: string;
  item_address: string | null;
  name: string | null;
  description: string | null;
  image_url: string | null;
  verification_status: string;
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
}

function isListing(value: unknown): value is Listing {
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
    !!seller && typeof seller.id === "string" &&
    nullableString(seller.username) && typeof seller.first_name === "string"
  );
}

async function requestJson<T>(url: string, signal?: AbortSignal): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, { signal });
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
  const params = new URLSearchParams({ limit: "100", offset: "0", sort: filters.sort });
  const search = filters.search.trim();
  if (search) params.set("search", search);
  if (filters.assetType !== "all") params.set("asset_type", filters.assetType);
  const page = await requestJson<unknown>(`${API_BASE_URL}/api/listings?${params}`, signal);
  if (
    !page || typeof page !== "object" || !Array.isArray((page as Partial<ListingPage>).items) ||
    typeof (page as Partial<ListingPage>).total !== "number" ||
    typeof (page as Partial<ListingPage>).limit !== "number" ||
    typeof (page as Partial<ListingPage>).offset !== "number" ||
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