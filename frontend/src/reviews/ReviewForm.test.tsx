import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { ReviewForm } from "./ReviewForm";

function response(body: unknown, status = 200) {
  return { ok: status >= 200 && status < 300, status, json: async () => body } as Response;
}

const eligibility = { order_id: "order-1", eligible: true, already_reviewed: false };

describe("ReviewForm", () => {
  beforeEach(() => {
    vi.resetAllMocks();
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(eligibility)));
  });

  it("shows the form only for eligible orders and submits one review", async () => {
    vi.mocked(fetch).mockImplementation(async (input, init) => {
      if (String(input).includes("/eligibility")) return response(eligibility);
      expect(init?.method).toBe("POST");
      return response({ id: "review-1", order_id: "order-1", rating: 5, comment: "Great", created_at: "2026-01-01T00:00:00Z" }, 201);
    });
    render(<ReviewForm orderId="order-1" accessToken="token" />);
    expect(await screen.findByRole("heading", { name: "Оставить отзыв" })).toBeInTheDocument();
    fireEvent.click(screen.getByLabelText("5 звёзд"));
    fireEvent.change(screen.getByRole("textbox"), { target: { value: "  Great  " } });
    fireEvent.click(screen.getByRole("button", { name: "Отправить отзыв" }));
    await waitFor(() => expect(screen.getByText(/Отзыв отправлен/)).toBeInTheDocument());
    expect(vi.mocked(fetch).mock.calls.filter(([input]) => String(input).endsWith("/api/reviews")).length).toBe(1);
  });

  it("does not render a CTA for an already reviewed order", async () => {
    vi.mocked(fetch).mockResolvedValueOnce(response({ order_id: "order-1", eligible: false, already_reviewed: true }));
    render(<ReviewForm orderId="order-1" accessToken="token" />);
    expect(await screen.findByText("Вы уже оставили отзыв на этот заказ.")).toBeInTheDocument();
    expect(screen.queryByRole("button", { name: "Отправить отзыв" })).not.toBeInTheDocument();
  });
  it("shows an error when create returns an invalid review response", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => {
      if (String(input).includes("/eligibility")) return response(eligibility);
      return response({ malformed: true }, 201);
    });
    render(<ReviewForm orderId="order-1" accessToken="token" />);
    await screen.findByRole("heading", { name: "Оставить отзыв" });
    fireEvent.click(screen.getByLabelText("5 звёзд"));
    fireEvent.click(screen.getByRole("button", { name: "Отправить отзыв" }));
    expect(await screen.findByRole("alert")).toHaveTextContent("некорректные данные отзыва");
  });

});
