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
    throw new Error("VITE_TONCONNECT_APP_URL must be an absolute URL.");
  }

  const isLocalhost = ["localhost", "127.0.0.1", "[::1]"].includes(parsed.hostname);
  if (parsed.protocol !== "https:" && !(isLocalhost && parsed.protocol === "http:")) {
    throw new Error("TON Connect requires HTTPS outside localhost development.");
  }
  if (parsed.username || parsed.password || parsed.pathname !== "/" || parsed.search || parsed.hash) {
    throw new Error("VITE_TONCONNECT_APP_URL must contain only the app origin.");
  }

  const origin = parsed.origin;
  return {
    url: origin,
    name: "VILTARA SHOP",
    iconUrl: new URL("/tonconnect-icon.png", origin).toString(),
  };
}
