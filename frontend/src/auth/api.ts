import { API_BASE_URL } from "../api/config";

export interface AuthenticatedUser {
  id: string;
  telegram_id: number;
  username: string | null;
  first_name: string;
  last_name: string | null;
}

export interface UserProfile extends AuthenticatedUser {
  language_code: string | null;
}

interface TelegramAuthResponse {
  access_token: string;
  token_type: "bearer";
  expires_in: number;
  user: AuthenticatedUser;
}

export class AuthApiError extends Error {
  constructor(readonly status: number, message: string) {
    super(message);
    this.name = "AuthApiError";
  }
}

async function parseError(response: Response): Promise<AuthApiError> {
  let message = `Ошибка авторизации (${response.status}).`;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      message = body.detail;
    }
  } catch {
    // Keep the HTTP status message when the server does not return JSON.
  }
  return new AuthApiError(response.status, message);
}

function isAuthenticatedUser(value: unknown): value is AuthenticatedUser {
  if (!value || typeof value !== "object") return false;
  const user = value as Partial<AuthenticatedUser>;
  return typeof user.id === "string" &&
    typeof user.telegram_id === "number" &&
    (user.username === null || typeof user.username === "string") &&
    typeof user.first_name === "string" &&
    (user.last_name === null || typeof user.last_name === "string");
}

function isTelegramAuthResponse(value: unknown): value is TelegramAuthResponse {
  if (!value || typeof value !== "object") return false;
  const response = value as Partial<TelegramAuthResponse>;
  return typeof response.access_token === "string" && response.access_token.length > 0 &&
    response.token_type === "bearer" && typeof response.expires_in === "number" &&
    isAuthenticatedUser(response.user);
}

function isUserProfile(value: unknown): value is UserProfile {
  if (!isAuthenticatedUser(value)) return false;
  const profile = value as Partial<UserProfile>;
  return profile.language_code === null || typeof profile.language_code === "string";
}

async function readJson(response: Response): Promise<unknown> {
  if (!response.ok) throw await parseError(response);
  try {
    return await response.json();
  } catch {
    throw new Error("Сервис авторизации вернул некорректный ответ.");
  }
}

export async function authenticateTelegram(initData: string, signal?: AbortSignal): Promise<string> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/auth/telegram`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ init_data: initData }),
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Не удалось связаться с сервисом авторизации.");
  }

  const body = await readJson(response);
  if (!isTelegramAuthResponse(body)) {
    throw new Error("Сервис авторизации вернул некорректную сессию.");
  }
  return body.access_token;
}

export async function fetchCurrentUser(accessToken: string, signal?: AbortSignal): Promise<UserProfile> {
  let response: Response;
  try {
    response = await fetch(`${API_BASE_URL}/api/users/me`, {
      headers: { Authorization: `Bearer ${accessToken}` },
      signal,
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Не удалось связаться с сервисом профиля.");
  }

  const body = await readJson(response);
  if (!isUserProfile(body)) {
    throw new Error("Сервис профиля вернул некорректный ответ.");
  }
  return body;
}