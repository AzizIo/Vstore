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

    await expect(page.getByRole("heading", { name: "Объявления" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Dragon Egg/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Rose Bouquet/ })).toBeVisible();
    await expect(page.getByText("3 предмета")).toBeVisible();
  });

  test("searches listings and shows only matching results", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("searchbox", { name: "Поиск объявлений" }).fill("dragon");

    await expect(page.getByRole("button", { name: /Dragon Egg/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toHaveCount(0);
    await expect(page.getByText("1 предмет")).toBeVisible();
  });

  test("filters listings by asset type", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("combobox", { name: "Тип актива" }).selectOption("telegram_gift");

    await expect(page.getByRole("button", { name: /Rose Bouquet/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toHaveCount(0);
    await expect(page.getByText("1 предмет")).toBeVisible();
  });

  test("sorts catalog results by price from high to low", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("combobox", { name: "Валюта" }).selectOption("TON");
    await page.getByRole("combobox", { name: "Сортировка объявлений" }).selectOption("price_desc");

    const catalogCards = page.getByRole("region", { name: "Каталог маркетплейса" }).locator(".listing-card");
    await expect(catalogCards).toHaveCount(2);
    await expect(catalogCards.first()).toContainText("Moon Lantern");
    await expect(catalogCards.nth(1)).toContainText("Dragon Egg");
  });

  test("filters price ranges within the selected currency and clears filters", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("combobox", { name: "Валюта" }).selectOption("XTR");
    await page.getByRole("spinbutton", { name: "Минимальная цена" }).fill("15");
    await page.getByRole("spinbutton", { name: "Максимальная цена" }).fill("25");

    await expect(page.getByRole("button", { name: /Rose Bouquet/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toHaveCount(0);
    await expect(page.getByRole("button", { name: /Dragon Egg/ })).toHaveCount(0);
    await expect(page.getByText("1 предмет")).toBeVisible();

    await page.getByRole("button", { name: "Сбросить фильтры" }).click();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Dragon Egg/ })).toBeVisible();
    await expect(page.getByRole("button", { name: /Rose Bouquet/ })).toBeVisible();
  });

  test("shows the empty state when search has no matches", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("searchbox", { name: "Поиск объявлений" }).fill("no-such-collectible");

    await expect(page.getByRole("heading", { name: "Объявления не найдены" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toHaveCount(0);
  });

  test("shows an API error and recovers after the user retries", async ({ page }) => {
    await mockMarketplaceApi(page, { catalogFailures: 2 });
    await page.goto("/");

    await expect(page.getByRole("heading", { name: "Каталог недоступен" })).toBeVisible();
    await expect(page.getByRole("alert")).toContainText("Каталог временно недоступен.");

    await page.getByRole("button", { name: "Повторить" }).click();

    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Каталог недоступен" })).toHaveCount(0);
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

    await expect(page.getByRole("heading", { name: "Объявления" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
  });

  test("shows a recoverable error for a listing that no longer exists", async ({ page }) => {
    await mockMarketplaceApi(page, { missingListingDetail: true });
    await page.goto("/");

    await page.getByRole("button", { name: /Moon Lantern/ }).click();

    await expect(page.getByRole("alert")).toContainText("Объявление не найдено.");
    await expect(page.getByRole("button", { name: "Повторить" })).toBeVisible();
  });
});


  test("confirms a reservation from listing detail on a 320px viewport and navigates to Orders", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 740 });
    const requests = await mockMarketplaceApi(page, { authenticated: true });
    await page.goto("/");
    await page.getByRole("button", { name: /Moon Lantern/ }).click();

    await expect(page.getByRole("heading", { name: "Moon Lantern" })).toBeVisible();
    const detailLayout = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
    }));
    expect(detailLayout.scrollWidth).toBeLessThanOrEqual(detailLayout.clientWidth);

    await page.getByRole("button", { name: "Зарезервировать" }).click();
    const dialog = page.getByRole("dialog", { name: "Зарезервировать это объявление?" });
    await expect(dialog).toContainText("Moon Lantern");
    await expect(dialog).toContainText("12.5 TON");
    await expect(dialog).toContainText("Ari (@collector)");
    await expect(dialog).toContainText("Оплата не подключена, средства не списываются, NFT остаётся у продавца");
    expect(requests.some((request) => request === "POST /api/orders")).toBe(false);

    await dialog.getByRole("button", { name: "Подтвердить резерв" }).click();
    await expect(page.getByRole("dialog", { name: "Резерв подтверждён" })).toBeVisible();
    expect(requests.filter((request) => request === "POST /api/orders")).toHaveLength(1);

    await page.getByRole("dialog").getByRole("button", { name: "Мои заказы" }).click();
    await expect(page.getByRole("heading", { name: "Заказы" })).toBeVisible();
  });

test.describe("order workspace", () => {
  test("filters, opens details, confirms cancellation, and captures desktop/mobile views", async ({ page }) => {
    const requests = await mockMarketplaceApi(page, { authenticated: true });
    await page.goto("/");
    await page.getByRole("button", { name: "Заказы" }).click();

    await expect(page.getByRole("heading", { name: "Заказы" })).toBeVisible();
    await expect(page.getByRole("tab", { name: /Purchases/ })).toHaveAttribute("aria-selected", "true");
    await expect(page.getByRole("button", { name: /Open order Moon Lantern/ })).toBeVisible();

    await page.screenshot({ path: "test-results/order-workspace-desktop.png", fullPage: true });
    await page.getByRole("button", { name: /Active/ }).click();
    await expect(page.getByRole("button", { name: /Open order Moon Lantern/ })).toBeVisible();
    await page.getByRole("searchbox", { name: "Поиск по названию актива или ID заказа" }).fill(orderId);
    await expect(page.getByRole("button", { name: /Open order Moon Lantern/ })).toBeVisible();

    await page.getByRole("button", { name: /Open order Moon Lantern/ }).click();
    await expect(page.getByRole("heading", { name: "Статус заказа" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "История событий" })).toBeVisible();
    await expect(page.getByText(/Payments are not enabled/)).toBeVisible();

    await page.setViewportSize({ width: 390, height: 844 });
    await page.screenshot({ path: "test-results/order-details-mobile.png", fullPage: true });

    await page.getByRole("button", { name: "Отменить заказ" }).click();
    await expect(page.getByText("Отменить этот резерв?")).toBeVisible();
    await page.getByRole("button", { name: "Подтвердить отмену" }).click();
    await expect(page.getByText("Отменено").first()).toBeVisible();
    expect(requests).toContain(`POST /api/orders/${orderId}/cancel`);
  });
});

test.describe("Telegram deep links", () => {
  test("opens the requested public listing from a listing start_param without a session", async ({ page }) => {
    const startParam = `listing_${listingIds.moon.replace(/-/g, "")}`;
    const requests = await mockMarketplaceApi(page, { startParam });
    await page.goto(`/?startapp=${startParam}`);

    await expect(page.getByRole("heading", { name: moonLantern.title })).toBeVisible();
    await expect(page.getByText("Откройте VILTARA в Telegram, чтобы оформить резерв.")).toBeVisible();
    await expect(page.getByRole("button", { name: "Зарезервировать" })).toHaveCount(0);
    await expect(page.getByRole("button", { name: "Каталог", exact: true })).toHaveAttribute("aria-pressed", "true");
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

    await expect(page.getByRole("heading", { name: "Статус заказа" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Moon Lantern" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Заказы", exact: true })).toHaveAttribute("aria-pressed", "true");
    expect(requests).toContain(`GET /api/orders/${orderId}`);
  });

  test("ignores a malformed start_param and leaves the catalog usable", async ({ page }) => {
    const requests = await mockMarketplaceApi(page, {
      startParam: "listing_not-a-32-character-hex-id",
    });
    await page.goto("/?startapp=listing_not-a-32-character-hex-id");

    await expect(page.getByRole("heading", { name: "Объявления" })).toBeVisible();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
    await expect(page.getByRole("button", { name: "Каталог" })).toHaveAttribute("aria-pressed", "true");
    expect(requests.some((request) => request.startsWith("GET /api/listings/"))).toBe(false);
  });
});

test.describe("navigation and unauthenticated access", () => {
  test("keeps the catalog public and shows an authentication gate in private sections", async ({ page }) => {
    const requests = await mockMarketplaceApi(page);
    await page.goto("/");

    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();

    await page.getByRole("button", { name: "Мои NFT" }).click();
    await expect(page.getByRole("heading", { name: "Мои NFT" })).toBeVisible();

    await page.getByRole("button", { name: "Мои объявления" }).click();
    await expect(page.getByRole("heading", { name: "Мои объявления" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "Откройте VILTARA в Telegram" })).toBeVisible();

    await page.getByRole("button", { name: "Заказы" }).click();
    await expect(page.getByRole("heading", { name: "Мои заказы" })).toBeVisible();

    await page.getByRole("button", { name: "Каталог" }).click();
    await expect(page.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();

    expect(requests.some((request) => request.startsWith("GET /api/assets/me"))).toBe(false);
    expect(requests.some((request) => request.startsWith("GET /api/listings/me"))).toBe(false);
    expect(requests.some((request) => request.startsWith("GET /api/orders"))).toBe(false);
  });

  test("returns to the public catalog when the VILTARA brand is clicked from a private section", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    await page.getByRole("button", { name: "Мои объявления" }).click();
    await expect(page.getByRole("heading", { name: "Откройте VILTARA в Telegram" })).toBeVisible();

    await page.getByRole("link", { name: "VILTARA" }).click();

    await expect(page.getByRole("heading", { name: "Объявления" })).toBeVisible();
    await expect(page.getByRole("button", { name: "Каталог", exact: true })).toHaveAttribute("aria-pressed", "true");
  });

  test("applies Telegram safe-area insets without introducing horizontal overflow on a phone viewport", async ({ page }) => {
    await page.setViewportSize({ width: 390, height: 844 });
    await mockMarketplaceApi(page);
    await page.goto("/");
    await page.addStyleTag({
      content: `:root {
        --tg-safe-area-inset-top: 20px;
        --tg-safe-area-inset-right: 12px;
        --tg-safe-area-inset-left: 14px;
        --tg-content-safe-area-inset-bottom: 28px;
      }`,
    });

    for (const width of [320, 360, 390, 430, 768, 1024]) {
      await page.setViewportSize({ width, height: 844 });
      const layout = await page.evaluate(() => ({
        paddingTop: getComputedStyle(document.body).paddingTop,
        paddingRight: getComputedStyle(document.body).paddingRight,
        paddingBottom: getComputedStyle(document.body).paddingBottom,
        paddingLeft: getComputedStyle(document.body).paddingLeft,
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
      }));

      expect(layout).toMatchObject({
        paddingTop: "20px",
        paddingRight: "12px",
        paddingBottom: "28px",
        paddingLeft: "14px",
      });
      expect(layout.scrollWidth, `horizontal overflow at ${width}px`).toBeLessThanOrEqual(layout.clientWidth);
    }
    await expect(page.getByRole("heading", { name: "Объявления" })).toBeVisible();
  });

});
