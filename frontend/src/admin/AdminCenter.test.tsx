import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminCenter } from "./AdminCenter";
const listing = { id: "listing-1", status: "pending_review" as const, title: "Moon Lantern", price_amount: "12.5", price_currency: "TON", created_at: "2026-01-01T00:00:00Z", expires_at: null, seller: { id: "seller-1", username: "seller", first_name: "Seller" }, asset: { name: "Lantern", image_url: null, verification_status: "verified" }, queue_reasons: ["pending_admin_review"] };
const page = { items: [listing], total: 1, limit: 25, offset: 0 };
const auditPage = { items: [], total: 0, limit: 25, offset: 0 };
function response(body: unknown, status = 200) { return { ok: status >= 200 && status < 300, status, json: async () => body } as Response; }
describe("AdminCenter", () => {
  beforeEach(() => { vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(page))); });
  it("loads the queue and exposes listing audit history", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => String(input).includes("/audit") ? response(auditPage) : response(page));
    render(<AdminCenter accessToken="verified-session" active />);
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "История аудита" }));
    expect(await screen.findByText("Решения модерации пока не зафиксированы.")).toBeInTheDocument();
  });
  it("opens the global audit log and displays moderation events", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => String(input).endsWith("/audit?limit=25&offset=0")
      ? response({ ...auditPage, total: 1, items: [{ id: "audit-1", actor_id: "admin-1", target_type: "listing", target_id: "listing-1", action: "approved", reason_code: "other", reason: "Approved after ownership check", before_snapshot: { status: "pending_review" }, after_snapshot: { status: "active" }, request_id: null, idempotency_key: "request-0001", occurred_at: "2026-01-02T00:00:00Z" }] })
      : response(page));
    render(<AdminCenter accessToken="verified-session" active />);
    fireEvent.click(screen.getByRole("button", { name: "Общий журнал аудита" }));
    expect(await screen.findByText(/Одобрено/)).toBeInTheDocument();
    expect(screen.getByText(/Approved after ownership check/)).toBeInTheDocument();
  });
  it("keeps unknown API statuses and queue reasons in Russian", async () => {
    const futureListing = {
      ...listing,
      status: "future_status",
      queue_reasons: ["future_reason"],
    };
    vi.mocked(fetch).mockResolvedValue(response({ ...page, items: [futureListing] }));
    render(<AdminCenter accessToken="verified-session" active />);
    expect(await screen.findByText("Неизвестный статус")).toBeInTheDocument();
    expect(screen.getByText("Дополнительная причина")).toBeInTheDocument();
  });
  it("requires a reason before confirming a moderation decision", async () => {
    render(<AdminCenter accessToken="verified-session" active />);
    await screen.findByText("Moon Lantern");
    fireEvent.click(screen.getByRole("button", { name: "Одобрить" }));
    expect(screen.getByRole("dialog", { name: "Одобрить объявление" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Подтвердить одобрение" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Пояснение (5–500 символов)"), { target: { value: "Policy review required" } });
    expect(screen.getByRole("button", { name: "Подтвердить одобрение" })).toBeEnabled();
  });
  it("shows a retryable error if the queue API is forbidden", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ detail: "Требуются права администратора" }, 403));
    render(<AdminCenter accessToken="regular-user-token" active />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Требуются права администратора");
    await waitFor(() => expect(fetch).toHaveBeenCalled());
  });
});
