export interface TelegramWebApp {
  initData?: string;
  initDataUnsafe?: { start_param?: string };
  ready?: () => void;
  expand?: () => void;
}

declare global {
  interface Window {
    Telegram?: {
      WebApp?: TelegramWebApp;
    };
  }
}

export type TelegramStartParam =
  | { type: "order"; id: string }
  | { type: "listing"; id: string };

function readTelegramInitData(): string | null {
  const webApp = window.Telegram?.WebApp;
  if (!webApp) return null;

  if (typeof webApp.ready === "function") webApp.ready();
  if (typeof webApp.expand === "function") webApp.expand();

  return typeof webApp.initData === "string" && webApp.initData.length > 0
    ? webApp.initData
    : null;
}

export function getTelegramInitData(signal?: AbortSignal): Promise<string | null> {
  const initData = readTelegramInitData();
  if (initData || window.Telegram?.WebApp) return Promise.resolve(initData);

  const script = document.querySelector<HTMLScriptElement>(
    'script[src="https://telegram.org/js/telegram-web-app.js"]',
  );
  if (!script) return Promise.resolve(null);

  return new Promise((resolve) => {
    let settled = false;
    const finish = () => {
      if (settled) return;
      settled = true;
      window.clearTimeout(timeout);
      script.removeEventListener("load", finish);
      script.removeEventListener("error", finish);
      signal?.removeEventListener("abort", onAbort);
      resolve(readTelegramInitData());
    };
    const onAbort = () => finish();
    const timeout = window.setTimeout(finish, 2500);

    script.addEventListener("load", finish, { once: true });
    script.addEventListener("error", finish, { once: true });
    signal?.addEventListener("abort", onAbort, { once: true });
    if (signal?.aborted) finish();
  });
}

function normalizeUuid(hex: string): string {
  const value = hex.toLowerCase();
  return [
    value.slice(0, 8),
    value.slice(8, 12),
    value.slice(12, 16),
    value.slice(16, 20),
    value.slice(20),
  ].join("-");
}

/**
 * Parses Telegram's untrusted start_param only as a navigation hint.
 * Authentication must always use the separately verified initData flow.
 */
export function getTelegramStartParam(): TelegramStartParam | null {
  const startParam = window.Telegram?.WebApp?.initDataUnsafe?.start_param;
  if (typeof startParam !== "string") return null;

  const match = /^(order|listing)_([0-9a-f]{32})$/i.exec(startParam);
  if (!match) return null;

  const type = match[1].toLowerCase();
  if (type !== "order" && type !== "listing") return null;

  return { type, id: normalizeUuid(match[2]) };
}

/** Backwards-compatible helper for callers that only consume order links. */
export function getTelegramStartOrderId(): string | null {
  const startParam = getTelegramStartParam();
  return startParam?.type === "order" ? startParam.id : null;
}
