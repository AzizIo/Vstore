import { act, cleanup, render, screen } from "@testing-library/react";
import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { afterEach, describe, expect, it, vi } from "vitest";

import { SessionProvider, useSession } from "../auth/SessionProvider";

const profile = {
  id: "user-1",
  telegram_id: 12345,
  username: "collector",
  first_name: "Collector",
  last_name: null,
  language_code: "ru",
  is_blocked: false,
};

function jsonResponse(body: unknown): Response {
  return {
    ok: true,
    status: 200,
    json: async () => body,
  } as Response;
}

function SessionProbe() {
  const session = useSession();
  return (
    <output>
      {session.status === "authenticated"
        ? `authenticated:${session.accessToken}`
        : session.status}
    </output>
  );
}

async function flushPromises() {
  for (let index = 0; index < 12; index += 1) await Promise.resolve();
}

afterEach(() => {
  cleanup();
  vi.useRealTimers();
  vi.unstubAllGlobals();
  Reflect.deleteProperty(window, "Telegram");
});

describe("SessionProvider", () => {
  it("renews the Telegram session before JWT expiry and clears private cached data", async () => {
    vi.useFakeTimers();
    window.Telegram = { WebApp: { initData: "raw-telegram-init-data" } };

    let authRequests = 0;
    const fetchMock = vi.fn(async (input: RequestInfo | URL) => {
      const url = String(input);
      if (url.endsWith("/api/auth/telegram")) {
        authRequests += 1;
        return jsonResponse({
          access_token: `token-${authRequests}`,
          token_type: "bearer",
          expires_in: 60,
          user: profile,
        });
      }
      if (url.endsWith("/api/users/me")) return jsonResponse(profile);
      throw new Error(`Unexpected request: ${url}`);
    });
    vi.stubGlobal("fetch", fetchMock);

    const queryClient = new QueryClient();
    queryClient.setQueryDefaults(["private-user-data"], { meta: { private: true } });
    queryClient.setQueryData(["private-user-data"], "sensitive-cached-value");

    render(
      <QueryClientProvider client={queryClient}>
        <SessionProvider>
          <SessionProbe />
        </SessionProvider>
      </QueryClientProvider>,
    );

    await act(async () => {
      await flushPromises();
    });

    expect(screen.getByText("authenticated:token-1")).toBeInTheDocument();
    expect(authRequests).toBe(1);

    // 60 seconds lifetime with a 10% refresh lead means refresh at 54 seconds.
    await act(async () => {
      await vi.advanceTimersByTimeAsync(54_000);
      await flushPromises();
    });

    expect(screen.getByText("authenticated:token-2")).toBeInTheDocument();
    expect(authRequests).toBe(2);
    expect(queryClient.getQueryData(["private-user-data"])).toBeUndefined();
  });
});
