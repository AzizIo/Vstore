export interface TelegramWebApp {
  initData?: string;
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