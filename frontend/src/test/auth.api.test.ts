import { afterEach, describe, expect, it, vi } from "vitest";

import { AuthApiError, authenticateTelegram } from "../auth/api";

const user = {
  id: "user-1",
  telegram_id: 12345,
  username: "collector",
  first_name: "Collector",
  last_name: null,
};

function jsonResponse(body: unknown, status = 200): Response {
  return {
    ok: status >= 200 && status < 300,
    status,
    json: async () => body,
  } as Response;
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("Telegram authentication API", () => {
  it("returns the server-issued token lifetime for proactive refresh", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      access_token: "access-token",
      token_type: "bearer",
      expires_in: 1800,
      user,
    })));

    await expect(authenticateTelegram("raw-telegram-init-data")).resolves.toEqual({
      accessToken: "access-token",
      expiresIn: 1800,
    });
  });

  it("extracts validation messages from the backend detail array", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      detail: [
        { loc: ["body", "init_data"], msg: "Поле обязательно", type: "missing" },
        { loc: ["body", "init_data"], msg: "Проверьте формат", type: "value_error" },
      ],
    }, 422)));

    await expect(authenticateTelegram("invalid-init-data")).rejects.toMatchObject({
      name: "AuthApiError",
      status: 422,
      message: "Поле обязательно Проверьте формат",
    } satisfies Partial<AuthApiError>);
  });

  it("rejects a non-positive token lifetime instead of scheduling a broken session", async () => {
    vi.stubGlobal("fetch", vi.fn().mockResolvedValue(jsonResponse({
      access_token: "access-token",
      token_type: "bearer",
      expires_in: 0,
      user,
    })));

    await expect(authenticateTelegram("raw-telegram-init-data")).rejects.toThrow(
      "Сервис авторизации вернул некорректную сессию.",
    );
  });
});
