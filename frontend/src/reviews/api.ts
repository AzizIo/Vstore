import { API_BASE_URL } from "../api/config";

export interface ReviewItem {
  id: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

export interface SellerReviewPage {
  seller_id: string;
  average_rating: number;
  review_count: number;
  rating_distribution: Record<string, number>;
  items: ReviewItem[];
  limit: number;
  offset: number;
  has_more: boolean;
}

export interface ReviewEligibility {
  order_id: string;
  eligible: boolean;
  already_reviewed: boolean;
}

export interface CreatedReview {
  id: string;
  order_id: string;
  rating: number;
  comment: string | null;
  created_at: string;
}

async function requestJson<T>(url: string, token?: string, init?: RequestInit): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: { ...(token ? { Authorization: `Bearer ${token}` } : {}), ...(init?.headers ?? {}) },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Не удалось связаться с сервисом отзывов. Попробуйте ещё раз.");
  }
  if (!response.ok) {
    let message = `Запрос завершился ошибкой (${response.status}).`;
    try {
      const body: unknown = await response.json();
      if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") message = body.detail;
    } catch { /* keep status message */ }
    throw new Error(message);
  }
  return response.json() as Promise<T>;
}

function isReviewPage(value: unknown): value is SellerReviewPage {
  if (!value || typeof value !== "object") return false;
  const page = value as Partial<SellerReviewPage>;
  return typeof page.seller_id === "string" && typeof page.average_rating === "number" &&
    typeof page.review_count === "number" && Array.isArray(page.items) &&
    page.items.every((item) => !!item && typeof item === "object" && typeof (item as ReviewItem).id === "string" &&
      Number.isInteger((item as ReviewItem).rating) && typeof (item as ReviewItem).created_at === "string") &&
    typeof page.limit === "number" && typeof page.offset === "number" && typeof page.has_more === "boolean";
}

function isEligibility(value: unknown): value is ReviewEligibility {
  return !!value && typeof value === "object" && typeof (value as ReviewEligibility).order_id === "string" &&
    typeof (value as ReviewEligibility).eligible === "boolean" && typeof (value as ReviewEligibility).already_reviewed === "boolean";
}

function isCreatedReview(value: unknown): value is CreatedReview {
  if (!value || typeof value !== "object") return false;
  const review = value as Partial<CreatedReview>;
  return typeof review.id === "string" && typeof review.order_id === "string" &&
    typeof review.rating === "number" && Number.isInteger(review.rating) &&
    review.rating >= 1 && review.rating <= 5 &&
    (review.comment === null || typeof review.comment === "string") &&
    typeof review.created_at === "string";
}

export async function fetchSellerReviews(sellerId: string, limit = 10, offset = 0, signal?: AbortSignal): Promise<SellerReviewPage> {
  const value = await requestJson<unknown>(`${API_BASE_URL}/api/reviews/sellers/${encodeURIComponent(sellerId)}?limit=${limit}&offset=${offset}`, undefined, { signal });
  if (!isReviewPage(value)) throw new Error("Сервис отзывов вернул некорректный ответ.");
  return value;
}

export async function fetchReviewEligibility(orderId: string, token: string, signal?: AbortSignal): Promise<ReviewEligibility> {
  const value = await requestJson<unknown>(`${API_BASE_URL}/api/reviews/eligibility?order_id=${encodeURIComponent(orderId)}`, token, { signal });
  if (!isEligibility(value)) throw new Error("Сервис отзывов вернул некорректный ответ о возможности публикации.");
  return value;
}

export async function createReview(orderId: string, rating: number, comment: string, token: string): Promise<CreatedReview> {
  const value = await requestJson<unknown>(`${API_BASE_URL}/api/reviews`, token, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ order_id: orderId, rating, comment }),
  });
  if (!isCreatedReview(value)) throw new Error("Сервис отзывов вернул некорректные данные отзыва.");
  return value;
}
