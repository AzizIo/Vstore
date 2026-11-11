import { expect, test } from "@playwright/test";

import {
  listingIds,
  mockMarketplaceApi,
  moonLantern,
  orderId,
} from "./fixtures/marketplace";

test.describe("public catalog", () => {
  test("opens the Mini App and renders listings from the public API", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Explore listings" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Dragon Egg/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Rose Bouquet/ })).toBeVisible();
    await expect(page.getByText("3 items")).toBeVisible();
  });

  test("searches listings and shows only matching results", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("searchbox", { name: "Search listings" }).fill("dragon");

    await expect(page.getByRole("button", { name: /Dragon Egg/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toHaveCount(0);
    await expect(page.getByText("1 item")).toBeVisible();
  });

  test("filters listings by asset type", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("combobox", { name: "Asset type" }).selectOption("telegram_gift");

    await expect(page.getByRole("button", { name: /Rose Bouquet/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toHaveCount(0);
    await expect(page.getByText("1 item")).toBeVisible();
  });

  test("sorts catalog results by price from high to low", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("combobox", { name: "Sort listings" }).selectOption("price_desc");

    const catalogCards = page.getByRole("region", { name: "Marketplace catalog" }).getByRole("button");
    await expect(catalogCards.first()).toContainText("Rose Bouquet");
    await expect(catalogCards.nth(1)).toContainText("Moon Lantern");
    await expect(catalogCards.nth(2)).toContainText("Dragon Egg");
  });

  test("shows the empty state when search has no matches", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("searchbox", { name: "Search listings" }).fill("no-such-collectible");

    await expect(page.getByRole("heading", { name: "No listings found" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toHaveCount(0);
  });

  test("shows an API error and recovers after the user retries", async ({ page }) => {
    await mockMarketplaceApi(page, { catalogFailures: 1 });
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Catalog unavailable" })).toBeVisible();
    await expect(page.getByRole("alert")).toContainText("Catalog temporarily unavailable.");

    await page.getByRole("button", { name: "Try again" }).click();

    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Catalog unavailable" })).toHaveCount(0);
  });
});

test.describe("listing details", () => {
  test("opens a listing card, shows seller details and returns to the catalog", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("button", { name: /Moon Lantern/ }).click();

    await expect(page.getByRole("heading", { name: "Moon Lantern" })).toBeVisible();
    await expect(page.getByText("12.5 TON")).toBeVisible();
    await expect(page.getByText("Ari")).toBeVisible();
    await expect(page.getByText("@collector")).toBeVisible();

    await page.getByRole("button", { name: /Back to catalog/ }).click();

    await expect(page.getByRole("heading", { name: "Explore listings" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
  });

  test("shows a recoverable error for a listing that no longer exists", async ({ page }) => {
    await mockMarketplaceApi(page, { missingListingDetail: true });
    await page.goto("/");

    await page.getByRole("button", { name: /Moon Lantern/ }).click();

    await expect(page.getByRole("alert")).toContainText("Listing not found.");
    await expect(page.getByRole("button", { name: "Try again" })).toBeVisible();
  });
});

test.describe("Telegram deep links", () => {
  test("opens the requested public listing from a listing start_param without a session", async ({ page }) => {
    const startParam = `listing_${listingIds.moon.replace(/-/g, "")}`;
    const requests = await mockMarketplaceApi(page, { startParam });
    await page.goto(`/?startapp=${startParam}`);

    await expect(page.getByRole("heading", { name: moonLantern.title })).toBeVisible();
    await expect(page.getByText("Open this Mini App in Telegram to sign in and place an order.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Place order" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Catalog" })).toHaveAttribute("aria-pressed", "true");
    expect(requests).toContain(`GET /api/listings/${listingIds.moon}`);
    expect(requests.some((request) => request === "POST /api/auth/telegram")).toBe(false);
    expect(requests.some((request) => request.startsWith("POST /api/orders"))).toBe(false);
  });

  test("opens the exact order from an order start_param", async ({ page }) => {
    const startParam = `order_${orderId.replace(/-/g, "")}`;
    const requests = await mockMarketplaceApi(page, {
      authenticated: true,
      startParam,
    });
    await page.goto(`/?startapp=${startParam}`);

    await expect(page.getByRole("heading", { name: "My Orders" })).toBeVisible();
    await expect(page.getByText("OPENED FROM TELEGRAM NOTIFICATION")).toBeVisible();
    await expect(page.getByRole("button", { name: "Orders" })).toHaveAttribute("aria-pressed", "true");
    expect(requests).toContain(`GET /api/orders/${orderId}`);
  });

  test("ignores a malformed start_param and leaves the catalog usable", async ({ page }) => {
    const requests = await mockMarketplaceApi(page, {
      startParam: "listing_not-a-32-character-hex-id",
    });
    await page.goto("/?startapp=listing_not-a-32-character-hex-id");

    await expect(page.getByRole("heading", { name: "Explore listings" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Catalog" })).toHaveAttribute("aria-pressed", "true");
    expect(requests.some((request) => request.startsWith("GET /api/listings/"))).toBe(false);
  });
});

test.describe("navigation and unauthenticated access", () => {
  test("keeps the catalog public and shows an authentication gate in private sections", async ({ page }) => {
    const requests = await mockMarketplaceApi(page);
    await page.goto("/");

    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();

    await page.getByRole("button", { name: "My NFT" }).click();
    await expect(page.getByRole("heading", { name: "Sign in to view your inventory" })).toBeVisible();

    await page.getByRole("button", { name: "My Listings" }).click();
    await expect(page.getByRole("heading", { name: "My Listings" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Open VILTARA in Telegram" })).toBeVisible();

    await page.getByRole("button", { name: "Orders" }).click();
    await expect(page.getByRole("heading", { name: "Sign in to view orders" })).toBeVisible();

    await page.getByRole("button", { name: "Catalog" }).click();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();

    expect(requests.some((request) => request.startsWith("GET /api/assets/me"))).toBe(false);
    expect(requests.some((request) => request.startsWith("GET /api/listings/me"))).toBe(false);
    expect(requests.some((request) => request.startsWith("GET /api/orders"))).toBe(false);
  });
});
