import { fireEvent, render, screen, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { beforeEach, describe, expect, it, vi } from "vitest";

import { useRetrySession, useSession } from "../auth/SessionProvider";
import { fetchAdminAccess } from "./api";
import { AdminPage } from "./AdminPage";

vi.mock("../auth/SessionProvider", () => ({
  SessionProvider: ({ children }: { children: ReactNode }) => children,
  useSession: vi.fn(),
  useRetrySession: vi.fn(),
}));

vi.mock("./api", () => ({
  fetchAdminAccess: vi.fn(),
}));

vi.mock("./AdminDashboard", () => ({
  AdminDashboard: ({ accessToken }: { accessToken: string }) => (
    <div>Admin Dashboard · {accessToken}</div>
  ),
}));

describe("AdminPage Telegram launch and authorization states", () => {
  const retrySession = vi.fn();

  beforeEach(() => {
    vi.clearAllMocks();
    vi.mocked(useRetrySession).mockReturnValue(retrySession);
    vi.mocked(fetchAdminAccess).mockResolvedValue(true);
  });

  it(
    "explains that the workspace must be launched through the bot when initData is missing",
    () => {
    vi.mocked(useSession).mockReturnValue({
      status: "unauthenticated",
      reason: "missing_init_data",
    });

    render(<AdminPage />);

    expect(screen.getByRole("alert")).toHaveTextContent(
      "Telegram не передал данные запуска",
    );
    expect(screen.getByRole("alert")).toHaveTextContent("/admin");
    expect(fetchAdminAccess).not.toHaveBeenCalled();
    },
  );

  it("explains that an expired Telegram session requires a fresh Mini App launch", () => {
    vi.mocked(useSession).mockReturnValue({
      status: "unauthenticated",
      reason: "invalid_init_data",
    });

    render(<AdminPage />);

    expect(screen.getByRole("alert")).toHaveTextContent("Сессия Telegram устарела");
  });

  it("allows retrying a transient Telegram session error", () => {
    vi.mocked(useSession).mockReturnValue({
      status: "error",
      message: "Не удалось подтвердить сессию Telegram.",
      retryable: true,
    });

    render(<AdminPage />);
    fireEvent.click(screen.getByRole("button", { name: "Повторить проверку сессии" }));

    expect(retrySession).toHaveBeenCalledOnce();
    expect(fetchAdminAccess).not.toHaveBeenCalled();
  });

  it("loads the admin dashboard only after the API confirms admin access", async () => {
    vi.mocked(useSession).mockReturnValue({
      status: "authenticated",
      accessToken: "verified-admin-session",
      user: {
        id: "user-1",
        telegram_id: 123456789,
        username: "admin",
        first_name: "Admin",
        last_name: null,
        language_code: "ru",
        is_blocked: false,
      },
    });

    render(<AdminPage />);

    expect(await screen.findByText("Admin Dashboard · verified-admin-session")).toBeInTheDocument();
    await waitFor(() => expect(fetchAdminAccess).toHaveBeenCalledWith(
      "verified-admin-session",
      expect.any(AbortSignal),
    ));
  });

  it("does not mount the dashboard when the API denies administrator access", async () => {
    vi.mocked(useSession).mockReturnValue({
      status: "authenticated",
      accessToken: "verified-regular-session",
      user: {
        id: "user-2",
        telegram_id: 987654321,
        username: "regular",
        first_name: "Regular",
        last_name: null,
        language_code: "ru",
        is_blocked: false,
      },
    });
    vi.mocked(fetchAdminAccess).mockResolvedValue(false);

    render(<AdminPage />);

    expect(await screen.findByRole("alert")).toHaveTextContent("Требуются права администратора");
    expect(screen.queryByText(/Admin Dashboard/)).not.toBeInTheDocument();
  });
});
