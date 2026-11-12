import { API_BASE_URL } from "./config";

export interface OverviewCounts {
  draft: number;
  active: number;
  reserved: number;
  sold: number;
  cancelled: number;
  expired: number;
  total: number;
}

export interface SellerActivityItem {
  id: string;
  kind: "listing" | "order";
  role: "buyer" | "seller" | null;
  listing_id: string;
  title: string;
  status: string;
  created_at: string;
  price_amount: string;
  price_currency: string;
}

export interface SellerOverview {
  listings: OverviewCounts;
  orders_as_seller: OverviewCounts;
  orders_as_buyer: OverviewCounts;
  reserved_order_snapshot_values: Record<string, string>;
  completed_order_snapshot_values: Record<string, string>;
  recent_activity: SellerActivityItem[];
}

function isCounts(value: unknown): value is OverviewCounts {
  if (!value || typeof value !== "object") return false;
  const counts = value as Partial<OverviewCounts>;
  return ["draft", "active", "reserved", "sold", "cancelled", "expired", "total"]
    .every((key) => Number.isInteger(counts[key as keyof OverviewCounts]) && (counts[key as keyof OverviewCounts] as number) >= 0);
}

function isActivity(value: unknown): value is SellerActivityItem {
  if (!value || typeof value !== "object") return false;
  const item = value as Partial<SellerActivityItem>;
  return typeof item.id === "string" &&
    (item.kind === "listing" || item.kind === "order") &&
    (item.role === null || item.role === "buyer" || item.role === "seller") &&
    typeof item.listing_id === "string" &&
    typeof item.title === "string" &&
    typeof item.status === "string" &&
    typeof item.created_at === "string" &&
    typeof item.price_amount === "string" &&
    typeof item.price_currency === "string";
}

function isSnapshotMap(value: unknown): value is Record<string, string> {
  return !!value && typeof value === "object" &&
    Object.values(value).every((amount) => typeof amount === "string");
}

export async function fetchSellerOverview(
  accessToken: string,
  signal?: AbortSignal,
): Promise<SellerOverview> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/users/me/overview`, {
      signal,
      headers: { Authorization: `Bearer ${accessToken}` },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Could not connect to your seller overview. Please try again.");
  }

  if (!response.ok) {
    let message = `Request failed (${response.status}).`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
        message = body.detail;
      }
    } catch {
      // Keep the HTTP status message when the server response is not JSON.
    }
    throw new Error(message);
  }

  const result: unknown = await response.json();
  if (
    !result || typeof result !== "object" ||
    !isCounts((result as SellerOverview).listings) ||
    !isCounts((result as SellerOverview).orders_as_seller) ||
    !isCounts((result as SellerOverview).orders_as_buyer) ||
    !isSnapshotMap((result as SellerOverview).reserved_order_snapshot_values) ||
    !isSnapshotMap((result as SellerOverview).completed_order_snapshot_values) ||
    !Array.isArray((result as SellerOverview).recent_activity) ||
    !(result as SellerOverview).recent_activity.every(isActivity)
  ) {
    throw new Error("The marketplace returned an invalid seller overview.");
  }
  return result as SellerOverview;
}
