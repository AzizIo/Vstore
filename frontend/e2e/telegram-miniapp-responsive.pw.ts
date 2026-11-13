import { expect, test } from "@playwright/test";
import { mockMarketplaceApi } from "./fixtures/marketplace";

test.describe("Telegram Mini App responsive shell", () => {
  test("keeps bottom navigation reachable without horizontal overflow on phone widths", async ({ page }) => {
    await mockMarketplaceApi(page);
    await page.goto("/");

    const navigation = page.getByRole("navigation", { name: "Разделы маркетплейса" });
    await expect(navigation).toBeVisible();

    for (const width of [320, 360, 390, 430]) {
      await page.setViewportSize({ width, height: 844 });

      const layout = await navigation.evaluate((element) => {
        const rect = element.getBoundingClientRect();
        const buttons = Array.from(element.querySelectorAll("button")).map((button) => {
          const buttonRect = button.getBoundingClientRect();
          return {
            height: buttonRect.height,
            left: buttonRect.left,
            right: buttonRect.right,
          };
        });

        return {
          position: getComputedStyle(element).position,
          bottom: rect.bottom,
          height: rect.height,
          clientWidth: element.clientWidth,
          scrollWidth: element.scrollWidth,
          viewportWidth: window.innerWidth,
          documentWidth: document.documentElement.scrollWidth,
          buttons,
        };
      });

      expect(layout.position, `bottom navigation should be fixed at ${width}px`).toBe("fixed");
      expect(layout.bottom, `navigation should stay at the viewport bottom at ${width}px`).toBeGreaterThanOrEqual(844 - 2);
      expect(layout.height).toBeGreaterThanOrEqual(56);
      expect(layout.scrollWidth, `navigation should not overflow at ${width}px`).toBeLessThanOrEqual(layout.clientWidth);
      expect(layout.documentWidth, `page should not overflow horizontally at ${width}px`).toBeLessThanOrEqual(layout.viewportWidth);
      expect(layout.buttons).toHaveLength(4);

      for (const button of layout.buttons) {
        expect(button.height).toBeGreaterThanOrEqual(44);
        expect(button.left).toBeGreaterThanOrEqual(0);
        expect(button.right).toBeLessThanOrEqual(width);
      }
    }

    await page.getByRole("button", { name: "Мои NFT", exact: true }).click();
    await expect(page.getByRole("button", { name: "Мои NFT", exact: true })).toHaveAttribute("aria-pressed", "true");
    await page.getByRole("button", { name: "Каталог", exact: true }).click();
    await expect(page.getByRole("button", { name: "Каталог", exact: true })).toHaveAttribute("aria-pressed", "true");
  });
});
