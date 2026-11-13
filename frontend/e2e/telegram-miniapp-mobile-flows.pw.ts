import { expect, test, type BrowserContext, type Page } from "@playwright/test";

import { mockMarketplaceApi } from "./fixtures/marketplace";

const MOBILE_WIDTHS = [320, 360, 390, 430] as const;

async function expectNoHorizontalOverflow(
  page: Page,
  width: number,
  selectors: string[] = [],
) {
  const metrics = await page.evaluate(() => ({
    documentWidth: document.documentElement.scrollWidth,
    clientWidth: document.documentElement.clientWidth,
    bodyWidth: document.body.scrollWidth,
  }));

  expect(metrics.documentWidth, `document overflow at ${width}px`).toBeLessThanOrEqual(metrics.clientWidth);
  expect(metrics.bodyWidth, `body overflow at ${width}px`).toBeLessThanOrEqual(metrics.clientWidth);

  for (const selector of selectors) {
    const element = page.locator(selector).first();
    await expect(element, `${selector} should be visible at ${width}px`).toBeVisible();
    const bounds = await element.evaluate((node) => {
      const rect = node.getBoundingClientRect();
      return { left: rect.left, right: rect.right, width: rect.width };
    });
    expect(bounds.width, `${selector} should have a measurable width`).toBeGreaterThan(0);
    expect(bounds.left, `${selector} should not leave the left edge at ${width}px`).toBeGreaterThanOrEqual(-1);
    expect(bounds.right, `${selector} should not leave the right edge at ${width}px`).toBeLessThanOrEqual(width + 1);
  }
}

async function openMockedMobilePage(
  context: BrowserContext,
  options: Parameters<typeof mockMarketplaceApi>[1] = {},
  width = 320,
) {
  const mobilePage = await context.newPage();
  await mobilePage.setViewportSize({ width, height: 844 });
  await mockMarketplaceApi(mobilePage, options);
  await mobilePage.goto("/");
  return mobilePage;
}

test.describe("Telegram Mini App mobile user journeys", () => {
  test("shows the buyer session and seller profile clearly on narrow screens", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 });
    await mockMarketplaceApi(page, { authenticated: true });
    await page.goto("/");

    await expect(page.locator(".session-authenticated")).toContainText("Вы вошли как Alex Example");
    await expect(page.locator("#wallet-connect")).toContainText("Подключение кошелька пока не настроено.");

    await page.getByRole("button", { name: /Moon Lantern/ }).click();
    await expect(page.getByRole("region", { name: "Профиль продавца" })).toContainText("Ari");
    await expect(page.getByRole("region", { name: "Профиль продавца" })).toContainText("@collector");
    await expect(page.getByRole("heading", { name: "Отзывы о продавце" })).toBeVisible();
    await expect(page.getByText("Пока нет подтверждённых отзывов.")).toBeVisible();

    for (const width of MOBILE_WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      await expectNoHorizontalOverflow(page, width, [
        ".topbar",
        ".session-banner",
        "#wallet-connect",
        ".detail-media-frame",
        ".seller-profile",
        ".seller-reviews",
      ]);
      await expect(page.getByRole("heading", { name: "Moon Lantern" })).toBeVisible();
      await expect(page.getByRole("heading", { name: "Отзывы о продавце" })).toBeVisible();
    }
  });

  test("creates a listing draft using the mobile asset picker and form", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 });
    const requests = await mockMarketplaceApi(page, { authenticated: true });
    await page.goto("/");

    await page.getByRole("button", { name: "Мои объявления", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Мои объявления" })).toBeVisible();
    await page.getByRole("button", { name: "Создать объявление", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Создать черновик объявления" })).toBeVisible();

    for (const width of MOBILE_WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      await expectNoHorizontalOverflow(page, width, [
        ".create-listing-view",
        ".asset-picker-heading",
        ".inventory-card",
      ]);
    }

    await page.getByRole("button", { name: "Выбрать NFT Moon Lantern NFT" }).click();
    await expect(page.getByRole("heading", { name: "Настройте предложение" })).toBeVisible();

    for (const width of MOBILE_WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      await expectNoHorizontalOverflow(page, width, [
        ".draft-form",
        ".selected-inventory-asset",
        ".draft-price-preview",
      ]);
      const controlHeights = await page.locator(".draft-form input, .draft-form select, .draft-form textarea").evaluateAll((elements) =>
        elements.map((element) => element.getBoundingClientRect().height),
      );
      expect(controlHeights.length).toBeGreaterThanOrEqual(4);
      expect(controlHeights.every((height) => height >= 44)).toBe(true);
    }

    await page.getByRole("spinbutton", { name: "Цена" }).fill("1.5");
    await page.getByRole("textbox", { name: "Название (необязательно)" }).fill("Мобильный черновик");
    await expect(page.locator(".draft-price-preview")).toContainText("1.5 TON");
    await page.getByRole("button", { name: "Сохранить черновик" }).click();

    await expect(page.getByRole("heading", { name: "Черновик создан" })).toBeVisible();
    await expect(page.locator(".creation-success")).toContainText("Мобильный черновик");
    expect(requests).toContain("POST /api/listings");
    for (const width of MOBILE_WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      await expectNoHorizontalOverflow(page, width, [".creation-success"]);
    }
  });

  test("keeps order list, order details and cancel confirmation usable on phones", async ({ page }) => {
    await page.setViewportSize({ width: 320, height: 844 });
    await mockMarketplaceApi(page, { authenticated: true });
    await page.goto("/");

    await page.getByRole("button", { name: "Заказы", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Заказы" })).toBeVisible();
    const orderCard = page.getByRole("button", { name: /Открыть заказ Moon Lantern/ });
    await expect(orderCard).toBeVisible();

    for (const width of MOBILE_WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      await expectNoHorizontalOverflow(page, width, [
        ".workspace-page-heading",
        ".workspace-role-tabs",
        ".workspace-filter-row",
        ".workspace-order-card",
      ]);
    }

    await orderCard.click();
    await expect(page.getByRole("heading", { name: "Статус заказа" })).toBeVisible();
    await expect(page.getByRole("heading", { name: "История событий" })).toBeVisible();

    for (const width of MOBILE_WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      await expectNoHorizontalOverflow(page, width, [
        ".order-detail-toolbar",
        ".order-detail-hero",
        ".order-detail-grid",
        ".order-detail-aside",
      ]);
      await expect(page.getByRole("button", { name: "Отменить заказ" })).toBeVisible();
    }

    await page.getByRole("button", { name: "Отменить заказ" }).click();
    const confirmation = page.getByRole("group", { name: "Подтвердите отмену заказа" });
    await expect(confirmation).toBeVisible();
    for (const width of MOBILE_WIDTHS) {
      await page.setViewportSize({ width, height: 844 });
      await expectNoHorizontalOverflow(page, width, [
        ".cancel-order-card",
        ".cancel-confirmation",
      ]);
      await expect(confirmation.getByRole("button", { name: "Подтвердить отмену" })).toBeVisible();
      await expect(confirmation.getByRole("button", { name: "Оставить заказ" })).toBeVisible();
    }
  });
});

test.describe("Telegram Mini App mobile error states", () => {
  test("catalog, NFT detail and seller review errors stay readable at 320px and 360px", async ({ page }) => {
    test.setTimeout(60_000);
    const context = page.context();

    const catalogPage = await openMockedMobilePage(context, { catalogFailures: 2 });
    await expect(catalogPage.getByRole("heading", { name: "Каталог недоступен" })).toBeVisible();
    await expect(catalogPage.getByRole("alert")).toContainText("Каталог временно недоступен.");
    await expectNoHorizontalOverflow(catalogPage, 320, [".catalog-message"]);
    await catalogPage.getByRole("button", { name: "Повторить" }).click();
    await expect(catalogPage.getByRole("button", { name: /Moon Lantern/ })).toBeVisible();
    await catalogPage.close();

    const detailPage = await openMockedMobilePage(context, { missingListingDetail: true }, 360);
    await detailPage.getByRole("button", { name: /Moon Lantern/ }).click();
    await expect(detailPage.getByRole("alert")).toContainText("Объявление не найдено.");
    await expectNoHorizontalOverflow(detailPage, 360, [".detail-message"]);
    await expect(detailPage.getByRole("button", { name: "Повторить" })).toBeVisible();
    await detailPage.close();

    const reviewsPage = await openMockedMobilePage(context, { sellerReviewsFailure: true }, 320);
    await reviewsPage.getByRole("button", { name: /Moon Lantern/ }).click();
    const reviews = reviewsPage.locator(".seller-reviews");
    await expect(reviews.getByRole("alert")).toContainText("Отзывы временно недоступны.");
    await expect(reviews.getByRole("button", { name: "Повторить" })).toBeVisible();
    await expectNoHorizontalOverflow(reviewsPage, 320, [".seller-reviews", ".reviews-state"]);
    await reviewsPage.close();
  });

  test("seller workspace, inventory, draft, order and order-detail errors fit narrow screens", async ({ page }) => {
    test.setTimeout(60_000);
    const context = page.context();

    const listingsPage = await openMockedMobilePage(context, { authenticated: true, myListingsFailure: true }, 320);
    await listingsPage.getByRole("button", { name: "Мои объявления", exact: true }).click();
    await expect(listingsPage.getByRole("heading", { name: "Объявления недоступны" })).toBeVisible();
    await expectNoHorizontalOverflow(listingsPage, 320, [".my-listings-message"]);
    await listingsPage.close();

    const inventoryPage = await openMockedMobilePage(context, { authenticated: true, inventoryFailure: true }, 360);
    await inventoryPage.getByRole("button", { name: "Мои объявления", exact: true }).click();
    await inventoryPage.getByRole("button", { name: "Создать объявление", exact: true }).click();
    await expect(inventoryPage.getByRole("heading", { name: "Инвентарь недоступен" })).toBeVisible();
    await expectNoHorizontalOverflow(inventoryPage, 360, [".my-listings-message"]);
    await inventoryPage.close();

    const draftPage = await openMockedMobilePage(context, { authenticated: true, draftCreationFailure: true }, 320);
    await draftPage.getByRole("button", { name: "Мои объявления", exact: true }).click();
    await draftPage.getByRole("button", { name: "Создать объявление", exact: true }).click();
    await draftPage.getByRole("button", { name: "Выбрать NFT Moon Lantern NFT" }).click();
    await draftPage.getByRole("spinbutton", { name: "Цена" }).fill("1.5");
    await draftPage.getByRole("button", { name: "Сохранить черновик" }).click();
    await expect(draftPage.getByRole("alert")).toContainText("Не удалось сохранить черновик.");
    await expectNoHorizontalOverflow(draftPage, 320, [".draft-form", ".creation-error"]);
    await draftPage.close();

    const ordersPage = await openMockedMobilePage(context, { authenticated: true, ordersFailure: true }, 360);
    await ordersPage.getByRole("button", { name: "Заказы", exact: true }).click();
    await expect(ordersPage.getByRole("heading", { name: "Заказы недоступны" })).toBeVisible();
    await expectNoHorizontalOverflow(ordersPage, 360, [".workspace-empty"]);
    await ordersPage.close();

    const orderDetailPage = await openMockedMobilePage(context, { authenticated: true, orderDetailFailure: true }, 320);
    await orderDetailPage.getByRole("button", { name: "Заказы", exact: true }).click();
    await orderDetailPage.getByRole("button", { name: /Открыть заказ Moon Lantern/ }).click();
    await expect(orderDetailPage.locator(".orders-error")).toContainText("Данные заказа временно недоступны.");
    await expectNoHorizontalOverflow(orderDetailPage, 320, [".orders-view", ".order-detail-panel", ".orders-error"]);
    await orderDetailPage.close();
  });
});
