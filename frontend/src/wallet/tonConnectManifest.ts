export interface TonConnectManifest {
  url: string;
  name: string;
  iconUrl: string;
}

/**
 * Build the manifest against the actual public Mini App origin.
 * Localhost is permitted for development; deployed origins must use HTTPS.
 */
export function createTonConnectManifest(appUrl: string): TonConnectManifest {
  let parsed: URL;
  try {
    parsed = new URL(appUrl);
  } catch {
    throw new Error("Укажите корректный абсолютный адрес VITE_TONCONNECT_APP_URL.");
  }

  const isLocalhost = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
  if (parsed.protocol !== "https:" && !(isLocalhost && parsed.protocol === "http:")) {
    throw new Error("Для подключения TON Connect требуется HTTPS. Исключение — локальная разработка.");
  }
  if (parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) {
    throw new Error("VITE_TONCONNECT_APP_URL должен содержать только адрес сайта без пути и параметров.");
  }

  const origin = parsed.origin;
  return {
    url: origin,
    name: "VILTARA SHOP",
    iconUrl: new URL("/tonconnect-icon.png", origin).toString(),
  };
}
