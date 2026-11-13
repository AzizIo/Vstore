import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { SellerReviews } from "./SellerReviews";

function response(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

const page = {
  seller_id: "seller-1",
  average_rating: 4.5,
  review_count: 2,
  rating_distribution: { "1": 0, "2": 0, "3": 0, "4": 1, "5": 1 },
  items: [{ id: "review-1", rating: 5, comment: "Verified transfer", created_at: "2026-01-01T00:00:00Z" }],
  limit: 10,
  offset: 0,
  has_more: false,
};

describe("SellerReviews", () => {
  beforeEach(() => vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(page))));

  it("renders the aggregate and safe public review fields", async () => {
    render(<SellerReviews sellerId="seller-1" accessToken={null} />);
    expect(await screen.findByText("4.5")).toBeInTheDocument();
    expect(screen.getByText("Verified transfer")).toBeInTheDocument();
    expect(screen.queryByText(/telegram|wallet|author/i)).not.toBeInTheDocument();
  });

  it("shows an empty state", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ ...page, review_count: 0, average_rating: 0, items: [] }));
    render(<SellerReviews sellerId="seller-1" accessToken={null} />);
    expect(await screen.findByText("Пока нет подтверждённых отзывов.")).toBeInTheDocument();
  });

  it("loads the next bounded page", async () => {
    vi.mocked(fetch)
      .mockResolvedValueOnce(response({ ...page, has_more: true }))
      .mockResolvedValueOnce(response({ ...page, offset: 1, items: [{ ...page.items[0], id: "review-2" }], has_more: false }));
    render(<SellerReviews sellerId="seller-1" accessToken={null} />);
    await screen.findByText("Verified transfer");
    fireEvent.click(screen.getByRole("button", { name: "Загрузить ещё отзывы" }));
    await waitFor(() => expect(screen.getAllByText("Verified transfer")).toHaveLength(2));
    expect(String(vi.mocked(fetch).mock.calls[1][0])).toContain("offset=1");
  });
});
