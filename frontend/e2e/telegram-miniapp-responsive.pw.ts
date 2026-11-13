import { expect, test } from "@playwright/test";
import { mockMarketplaceApi } from "./fixtures/marketplace";

test.describe("Telegram Mini App responsive shell", () => {
  test("keeps bottom navigation reachable without horizontal overflow on phone widths", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    const navigation = page.getByRole("navigation", { name: "Разделы маркетплейса" });
    await expect(navigation).toBeVisible();
    await page.addStyleTag({
      content: `:root {
        --tg-safe-area-inset-top: 20px;
        --tg-safe-area-inset-right: 12px;
        --tg-safe-area-inset-left: 14px;
        --tg-content-safe-area-inset-bottom: 28px;
      }`,
    });

    for (const width of [320, 360, 390, 430]) {
      await page.setViewportSize({ width, height: 844 });

      const layout = await navigation.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const buttons = Array.from(element.querySelectorAll("button")).map((button) => {
          const buttonRect = button.getBoundingClientRect();
          const labelRect = button.querySelector(".navigation-label")?.getBoundingClientRect();
          return {
            height: buttonRect.height,
            left: buttonRect.left,
            right: buttonRect.right,
            bottom: buttonRect.bottom,
            labelLeft: labelRect?.left ?? -1,
            labelRight: labelRect?.right ?? Infinity,
            iconCount: button.querySelectorAll(".navigation-icon").length,
            pseudoIcon: getComputedStyle(button, "::before").content,
          };
        });
        const shell = document.querySelector(".app-shell");
        const shellRect = shell?.getBoundingClientRect();

        return {
          position: getComputedStyle(element).position,
          bottom: rect.bottom,
          height: rect.height,
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
          viewportWidth: window.innerWidth,
          documentWidth: document.documentElement.scrollWidth,
          bodyPaddingTop: getComputedStyle(document.body).paddingTop,
          bodyPaddingRight: getComputedStyle(document.body).paddingRight,
          bodyPaddingBottom: getComputedStyle(document.body).paddingBottom,
          bodyPaddingLeft: getComputedStyle(document.body).paddingLeft,
          shellTop: shellRect?.top ?? -1,
          shellMinHeight: shell ? Number.parseFloat(getComputedStyle(shell).minHeight) : -1,
          buttons,
        };
      });

      expect(layout.position, `bottom navigation should be fixed at ${width}px`).toBe("fixed");
      expect(layout.bottom, `navigation should stay at the viewport bottom at ${width}px`).toBeGreaterThanOrEqual(844 - 2);
      expect(layout.height).toBeGreaterThanOrEqual(56);
      expect(layout.scrollWidth, `navigation should not overflow at ${width}px`).toBeLessThanOrEqual(layout.clientWidth);
      expect(layout.documentWidth, `page should not overflow horizontally at ${width}px`).toBeLessThanOrEqual(layout.viewportWidth);
      expect(layout.buttons).toHaveLength(4);
      expect(layout.bodyPaddingTop).toBe("20px");
      expect(layout.bodyPaddingRight).toBe("12px");
      expect(layout.bodyPaddingBottom).toBe("28px");
      expect(layout.bodyPaddingLeft).toBe("14px");
      expect(layout.shellTop).toBe(20);
      expect(layout.shellMinHeight).toBe(796);

      for (const button of layout.buttons) {
        expect(button.height).toBeGreaterThanOrEqual(44);
        expect(button.left).toBeGreaterThanOrEqual(14);
        expect(button.right).toBeLessThanOrEqual(width - 12);
        expect(button.bottom).toBeLessThanOrEqual(844 - 28);
        expect(button.labelLeft).toBeGreaterThanOrEqual(button.left);
        expect(button.labelRight).toBeLessThanOrEqual(button.right);
        expect(button.iconCount).toBe(1);
        expect(button.pseudoIcon).toBe("none");
      }
    }

    await page.getByRole("button", { name: "Мои NFT", exact: true }).click();
    await expect(page.getByRole("button", { name: "Мои NFT", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Каталог", exact: true }).click();
    await expect(page.getByRole("button", { name: "Каталог", exact: true })).toHaveAttribute("aria-pressed", "true");
  });
});


test("keeps seller listings and order cards compact on Telegram phone widths", async ({ page }) => {
  await mockMarketplaceApi(page, { authenticated: true });
  await page.goto("/");

  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });

    await page.getByRole("button", { name: "Мои объявления", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Мои объявления" })).toBeVisible();
    const listingCard = page.locator(".my-listing-card").first();
    await expect(listingCard).toBeVisible();

    const listingLayout = await listingCard.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        width: rect.width,
        scrollWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
      };
    });
    expect(listingLayout.left).toBeGreaterThanOrEqual(0);
    expect(listingLayout.right).toBeLessThanOrEqual(width);
    expect(listingLayout.scrollWidth).toBeLessThanOrEqual(listingLayout.viewportWidth);

    await page.getByRole("button", { name: "Заказы", exact: true }).click();
    await expect(page.getByRole("heading", { name: "Заказы" })).toBeVisible();
    const orderCard = page.locator(".workspace-order-card").first();
    await expect(orderCard).toBeVisible();

    const orderLayout = await orderCard.evaluate((element) => {
      const rect = element.getBoundingClientRect();
      return {
        left: rect.left,
        right: rect.right,
        width: rect.width,
        scrollWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
      };
    });
    expect(orderLayout.left).toBeGreaterThanOrEqual(0);
    expect(orderLayout.right).toBeLessThanOrEqual(width);
    expect(orderLayout.scrollWidth).toBeLessThanOrEqual(orderLayout.viewportWidth);
  }
});


test("listing detail product layout stays within Telegram viewport", async ({ page }) => {
  await mockMarketplaceApi(page);
  await page.goto("/");

  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });
    await page.getByRole("button", { name: /Moon Lantern/ }).click();

    await expect(page.getByRole("heading", { name: "Moon Lantern" })).toBeVisible();
    await expect(page.locator(".detail-media-frame")).toBeVisible();
    await expect(page.locator(".detail-price-card")).toContainText("12,5 TON");
    await expect(page.locator(".detail-verification-label")).toContainText("Владение подтверждено");

    const layout = await page.evaluate(() => {
      const media = document.querySelector(".detail-media-column")?.getBoundingClientRect();
      const copy = document.querySelector(".detail-copy")?.getBoundingClientRect();
      return {
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        mediaLeft: media?.left ?? -1,
        mediaRight: media?.right ?? Infinity,
        copyLeft: copy?.left ?? -1,
        copyRight: copy?.right ?? Infinity,
      };
    });

    expect(layout.scrollWidth, `detail page overflow at ${width}px`).toBeLessThanOrEqual(layout.clientWidth);
    expect(layout.mediaLeft).toBeGreaterThanOrEqual(0);
    expect(layout.mediaRight).toBeLessThanOrEqual(width);
    expect(layout.copyLeft).toBeGreaterThanOrEqual(0);
    expect(layout.copyRight).toBeLessThanOrEqual(width);

    await page.getByRole("button", { name: /Назад в каталог/ }).click();
  }
});

test("seller draft builder is usable at Telegram phone widths", async ({ page }) => {
  await mockMarketplaceApi(page, { authenticated: true });
  await page.goto("/");
  await page.getByRole("button", { name: "Мои объявления", exact: true }).click();
  await page.getByRole("button", { name: "Создать объявление" }).click();

  await expect(page.getByRole("heading", { name: "Выберите NFT для продажи" })).toBeVisible();
  const assetChoice = page.getByRole("button", { name: "Выбрать NFT Moon Lantern NFT" });
  await expect(assetChoice).toBeVisible();

  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });
    const layout = await page.evaluate(() => ({
      scrollWidth: document.documentElement.scrollWidth,
      clientWidth: document.documentElement.clientWidth,
      right: document.querySelector(".asset-picker-heading")?.getBoundingClientRect().right ?? Infinity,
    }));
    expect(layout.scrollWidth, `asset picker overflow at ${width}px`).toBeLessThanOrEqual(layout.clientWidth);
    expect(layout.right).toBeLessThanOrEqual(width);
  }

  await assetChoice.click();
  await expect(page.getByRole("heading", { name: "Настройте предложение" })).toBeVisible();
  await expect(page.getByText("Укажите цену")).toBeVisible();

  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });
    const layout = await page.evaluate(() => {
      const form = document.querySelector(".draft-form")?.getBoundingClientRect();
      return {
        scrollWidth: document.documentElement.scrollWidth,
        clientWidth: document.documentElement.clientWidth,
        left: form?.left ?? -1,
        right: form?.right ?? Infinity,
      };
    });
    expect(layout.scrollWidth, `draft form overflow at ${width}px`).toBeLessThanOrEqual(layout.clientWidth);
    expect(layout.left).toBeGreaterThanOrEqual(0);
    expect(layout.right).toBeLessThanOrEqual(width);
  }

  await page.getByRole("spinbutton", { name: "Цена" }).fill("1.5");
  await expect(page.locator(".draft-price-preview")).toContainText("1.5 TON");
});


test("catalog cards and filter controls stay balanced on Telegram phone widths", async ({ page }) => {
  await mockMarketplaceApi(page);
  await page.goto("/");

  for (const width of [320, 360, 390, 430]) {
    await page.setViewportSize({ width, height: 844 });

    const card = page.locator(".listing-card").first();
    const search = page.locator(".catalog-controls .search-control");
    const filter = page.locator(".catalog-controls .select-control").first();

    await expect(card).toBeVisible();
    await expect(search).toBeVisible();
    await expect(filter).toBeVisible();

    const layout = await page.evaluate(() => {
      const rectOf = (selector: string) => {
        const rect = document.querySelector(selector)?.getBoundingClientRect();
        return rect ? { left: rect.left, right: rect.right, height: rect.height } : null;
      };
      const card = document.querySelector(".listing-card");
      const artwork = card?.querySelector(".artwork");
      return {
        documentWidth: document.documentElement.scrollWidth,
        viewportWidth: window.innerWidth,
        card: rectOf(".listing-card"),
        search: rectOf(".catalog-controls .search-control"),
        filter: rectOf(".catalog-controls .select-control"),
        artwork: artwork ? {
          width: artwork.getBoundingClientRect().width,
          height: artwork.getBoundingClientRect().height,
        } : null,
        cardRadius: card ? Number.parseFloat(getComputedStyle(card).borderTopLeftRadius) : 0,
      };
    });

    expect(layout.documentWidth, `catalog should not overflow at ${width}px`).toBeLessThanOrEqual(layout.viewportWidth);
    expect(layout.card?.left ?? -1).toBeGreaterThanOrEqual(0);
    expect(layout.card?.right ?? Infinity).toBeLessThanOrEqual(width);
    expect(layout.search?.height ?? 0).toBeGreaterThanOrEqual(44);
    expect(layout.filter?.height ?? 0).toBeGreaterThanOrEqual(42);
    expect(layout.artwork?.width ?? 0).toBeGreaterThan(0);
    expect(layout.artwork?.height ?? 0).toBeGreaterThan(0);
    expect(layout.cardRadius).toBeGreaterThan(0);
  }
});
