import { API_BASE_URL } from "../api/config";

export interface WalletRecord {
  id: string;
  address: string;
  network: string;
  is_verified: boolean;
  is_primary: boolean;
}

export interface WalletProofChallenge {
  payload: string;
  expires_at: string;
}

export interface TonProofReply {
  timestamp: number;
  domain: { lengthBytes: number; value: string };
  signature: string;
  payload: string;
}

export interface TonWalletAccount {
  address: string;
  chain: string;
  publicKey?: string;
  walletStateInit: string;
}

async function readResponse(response: Response): Promise<unknown> {
  if (response.ok) {
    try {
      return await response.json();
    } catch {
      throw new Error("Сервис кошельков вернул некорректный ответ.");
    }
  }

  let message = `Ошибка запроса кошелька (${response.status}).`;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      message = body.detail;
    }
  } catch {
    // Keep the HTTP status message when the server does not return JSON.
  }
  throw new Error(message);
}

function authHeaders(accessToken: string): HeadersInit {
  return {
    Authorization: `Bearer ${accessToken}`,
    "Content-Type": "application/json",
  };
}

function isWalletRecord(value: unknown): value is WalletRecord {
  if (!value || typeof value !== "object") return false;
  const wallet = value as Partial<WalletRecord>;
  return typeof wallet.id === "string" &&
    typeof wallet.address === "string" &&
    typeof wallet.network === "string" &&
    typeof wallet.is_verified === "boolean" &&
    typeof wallet.is_primary === "boolean";
}

export async function fetchMyWallets(
  accessToken: string,
  signal?: AbortSignal,
): Promise<WalletRecord[]> {
  const response = await fetch(`${API_BASE_URL}/api/wallets/me`, {
    headers: authHeaders(accessToken),
    signal,
  });
  const body = await readResponse(response);
  if (!Array.isArray(body) || !body.every(isWalletRecord)) {
    throw new Error("Сервис кошельков вернул некорректный список.");
  }
  return body;
}

export async function createWalletProofChallenge(
  accessToken: string,
): Promise<WalletProofChallenge> {
  const response = await fetch(`${API_BASE_URL}/api/wallets/proof/challenge`, {
    method: "POST",
    headers: authHeaders(accessToken),
  });
  const body = await readResponse(response);
  if (
    !body ||
    typeof body !== "object" ||
    !("payload" in body) ||
    typeof body.payload !== "string" ||
    !("expires_at" in body) ||
    typeof body.expires_at !== "string"
  ) {
    throw new Error("Сервис кошельков вернул некорректный запрос подтверждения.");
  }
  return { payload: body.payload, expires_at: body.expires_at };
}

export async function verifyConnectedWallet(
  accessToken: string,
  account: TonWalletAccount,
  proof: TonProofReply,
): Promise<WalletRecord> {
  const response = await fetch(`${API_BASE_URL}/api/wallets/proof/verify`, {
    method: "POST",
    headers: authHeaders(accessToken),
    body: JSON.stringify({
      address: account.address,
      network: account.chain,
      ...(account.publicKey ? { public_key: account.publicKey } : {}),
      proof: {
        timestamp: proof.timestamp,
        domain: proof.domain,
        signature: proof.signature,
        payload: proof.payload,
        state_init: account.walletStateInit,
      },
    }),
  });
  const body = await readResponse(response);
  if (!isWalletRecord(body)) {
    throw new Error("Сервис кошельков вернул некорректный результат проверки.");
  }
  return body;
}

export async function setPrimaryWallet(
  accessToken: string,
  walletId: string,
): Promise<WalletRecord> {
  const response = await fetch(`${API_BASE_URL}/api/wallets/${walletId}/primary`, {
    method: "PATCH",
    headers: authHeaders(accessToken),
  });
  const body = await readResponse(response);
  if (!isWalletRecord(body)) {
    throw new Error("Сервис кошельков вернул некорректный результат смены основного кошелька.");
  }
  return body;
}

export async function unlinkWallet(accessToken: string, walletId: string): Promise<void> {
  const response = await fetch(
    `${API_BASE_URL}/api/users/me/wallets/${walletId}`,
    {
      method: "DELETE",
      headers: authHeaders(accessToken),
    },
  );
  if (response.ok) return;

  let message = `Ошибка запроса кошелька (${response.status}).`;
  try {
    const body: unknown = await response.json();
    if (body && typeof body === "object" && "detail" in body && typeof body.detail === "string") {
      message = body.detail;
    }
  } catch {
    // Keep the HTTP status message when the server does not return JSON.
  }
  throw new Error(message);
}
