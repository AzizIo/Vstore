import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import { beforeEach, describe, expect, it, vi } from "vitest";
import { AdminCenter } from "./AdminCenter";
const listing = { id: "listing-1", status: "active" as const, title: "Moon Lantern", price_amount: "12.5", price_currency: "TON", created_at: "2026-01-01T00:00:00Z", expires_at: null, seller: { id: "seller-1", username: "seller", first_name: "Seller" }, asset: { name: "Lantern", image_url: null, verification_status: "verified" }, queue_reasons: ["active_listing_review"] };
const page = { items: [listing], total: 1, limit: 25, offset: 0 };
const auditPage = { items: [], total: 0, limit: 25, offset: 0 };
function response(body: unknown, status = 200) { return { ok: status >= 200 && status < 300, status, json: async () => body } as Response; }
describe("AdminCenter", () => {
  beforeEach(() => { vi.stubGlobal("fetch", vi.fn().mockResolvedValue(response(page))); });
  it("loads the queue and exposes listing audit history", async () => {
    vi.mocked(fetch).mockImplementation(async (input) => String(input).includes("/audit") ? response(auditPage) : response(page));
    render(<AdminCenter accessToken="verified-session" active />);
    expect(await screen.findByText("Moon Lantern")).toBeInTheDocument();
    fireEvent.click(screen.getByRole("button", { name: "Audit history" }));
    expect(await screen.findByText("No moderation decisions recorded.")).toBeInTheDocument();
  });
  it("requires a reason before confirming a moderation decision", async () => {
    render(<AdminCenter accessToken="verified-session" active />);
    await screen.findByText("Moon Lantern");
    fireEvent.click(screen.getByRole("button", { name: "Suspend" }));
    expect(screen.getByRole("dialog", { name: "Suspend listing" })).toBeInTheDocument();
    expect(screen.getByRole("button", { name: "Confirm suspend" })).toBeDisabled();
    fireEvent.change(screen.getByLabelText("Explanation (5–500 characters)"), { target: { value: "Policy review required" } });
    expect(screen.getByRole("button", { name: "Confirm suspend" })).toBeEnabled();
  });
  it("shows a retryable error if the queue API is forbidden", async () => {
    vi.mocked(fetch).mockResolvedValue(response({ detail: "Administrator access required" }, 403));
    render(<AdminCenter accessToken="regular-user-token" active />);
    expect(await screen.findByRole("alert")).toHaveTextContent("Administrator access required");
    await waitFor(() => expect(fetch).toHaveBeenCalled());
  });
});
