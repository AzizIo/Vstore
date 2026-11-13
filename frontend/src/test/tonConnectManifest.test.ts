import { describe, expect, it } from "vitest";

import { createTonConnectManifest } from "../wallet/tonConnectManifest";

describe("TON Connect manifest", () => {
  it("uses the configured public origin and absolute PNG icon URL", () => {
    expect(createTonConnectManifest("https://shop.example.com")).toEqual({
      url: "https://shop.example.com",
      name: "VILTARA SHOP",
      iconUrl: "https://shop.example.com/tonconnect-icon.png",
    });
  });

  it("allows localhost for development", () => {
    expect(createTonConnectManifest("http://localhost:5173").url).toBe("http://localhost:5173");
  });

  it("shows Russian configuration errors for invalid app URLs", () => {
    expect(() => createTonConnectManifest("shop.example.com"))
      .toThrow("Укажите корректный абсолютный адрес VITE_TONCONNECT_APP_URL.");
    expect(() => createTonConnectManifest("http://shop.example.com"))
      .toThrow("Для подключения TON Connect требуется HTTPS. Исключение — локальная разработка.");
    expect(() => createTonConnectManifest("https://shop.example.com/path"))
      .toThrow("VITE_TONCONNECT_APP_URL должен содержать только адрес сайта без пути и параметров.");
  });

  it.each([
    "http://shop.example.com",
    "shop.example.com",
    "https://shop.example.com/path",
    "https://user:pass@shop.example.com",
  ])("rejects an unsafe or non-origin app URL: %s", (value) => {
    expect(() => createTonConnectManifest(value)).toThrow();
  });
});
