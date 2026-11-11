import { defineConfig } from "vitest/config";
import react from "@vitejs/plugin-react";
import tailwindcss from "@tailwindcss/vite";
import { loadEnv, type Plugin } from "vite";

import { createTonConnectManifest } from "./src/wallet/tonConnectManifest";

function tonConnectManifestPlugin(appUrl: string | undefined): Plugin {
  let manifest: ReturnType<typeof createTonConnectManifest> | null = null;
  if (appUrl) {
    manifest = createTonConnectManifest(appUrl);
  }

  function serveManifest(req: any, res: any, _next: (error?: unknown) => void) {
    if (req.method === "OPTIONS") {
      res.statusCode = 204;
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.setHeader("Access-Control-Allow-Methods", "GET, HEAD, OPTIONS");
      res.setHeader("Access-Control-Allow-Headers", "Content-Type");
      res.end();
      return;
    }
    if (req.method !== "GET" && req.method !== "HEAD") {
      res.statusCode = 405;
      res.setHeader("Allow", "GET, HEAD, OPTIONS");
      res.end();
      return;
    }
    if (!manifest) {
      res.statusCode = 503;
      res.setHeader("Content-Type", "application/json; charset=utf-8");
      res.setHeader("Access-Control-Allow-Origin", "*");
      res.end(JSON.stringify({ error: "Set VITE_TONCONNECT_APP_URL to the public Mini App origin." }));
      return;
    }
    res.statusCode = 200;
    res.setHeader("Content-Type", "application/json; charset=utf-8");
    res.setHeader("Access-Control-Allow-Origin", "*");
    res.setHeader("Cache-Control", "no-store");
    const body = JSON.stringify(manifest);
    res.end(req.method === "HEAD" ? undefined : body);
  }

  return {
    name: "viltara-tonconnect-manifest",
    configureServer(server) {
      server.middlewares.use("/tonconnect-manifest.json", serveManifest);
    },
    configurePreviewServer(server) {
      server.middlewares.use("/tonconnect-manifest.json", serveManifest);
    },
    generateBundle() {
      if (!manifest) {
        this.error("Set VITE_TONCONNECT_APP_URL before building the production Mini App.");
      }
      this.emitFile({
        type: "asset",
        fileName: "tonconnect-manifest.json",
        source: `${JSON.stringify(manifest, null, 2)}\n`,
      });
    },
  };
}

export default defineConfig(({ mode, command }) => {
  const env = loadEnv(mode, process.cwd(), "VITE_");
  const appUrl = env.VITE_TONCONNECT_APP_URL?.trim() || undefined;
  const manifestUrl = env.VITE_TONCONNECT_MANIFEST_URL?.trim() || undefined;

  if (command === "build") {
    if (!appUrl || !manifestUrl) {
      throw new Error(
        "Production builds require VITE_TONCONNECT_APP_URL and VITE_TONCONNECT_MANIFEST_URL.",
      );
    }
    const app = new URL(appUrl);
    const manifest = new URL(manifestUrl);
    if (
      app.protocol !== "https:" ||
      manifest.protocol !== "https:" ||
      app.origin !== manifest.origin ||
      manifest.pathname !== "/tonconnect-manifest.json" ||
      manifest.search ||
      manifest.hash
    ) {
      throw new Error(
        "Use HTTPS for both TON Connect URLs; the manifest must be /tonconnect-manifest.json on the Mini App origin.",
      );
    }
  }

  return {
    plugins: [
      react(),
      tailwindcss(),
      tonConnectManifestPlugin(appUrl),
    ],
    server: {
      host: "0.0.0.0",
      port: 5173,
      strictPort: true,
      // Cloudflare Quick Tunnels use a random *.trycloudflare.com hostname.
      // This is a development server; production should use a reverse proxy.
      allowedHosts: [".trycloudflare.com"],
      proxy: {
        "/api": {
          target: "http://api:8000",
          changeOrigin: true,
        },
      },
    },
    test: {
      environment: "jsdom",
      setupFiles: "./src/test/setup.ts",
      clearMocks: true,
    },
  };
});
