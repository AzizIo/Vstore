import { createHmac } from "node:crypto";
import { expect, test, type Page } from "@playwright/test";

interface TelegramUser {
  id: number;
  first_name: string;
  last_name: string;
  username: string;
  language_code: string;
}

function signedInitData(user: TelegramUser): string {
  const botToken = process.env.BOT_TOKEN;
  if (!botToken) throw new Error("BOT_TOKEN is required only by the isolated API-backed E2E job.");
  const params = new URLSearchParams({
    auth_date: String(Math.floor(Date.now() / 1000)),
    query_id: "admin-moderation-" + user.id,
    user: JSON.stringify(user),
  });
  const checkString = Array.from(params.entries())
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => key + "=" + value)
    .join("\n");
  const secret = createHmac("sha256", "WebAppData").update(botToken).digest();
  params.set("hash", createHmac("sha256", secret).update(checkString).digest("hex"));
  return params.toString();
}

async function installTelegramBridge(page: Page, user: TelegramUser): Promise<void> {
  const initData = signedInitData(user);
  await page.addInitScript((signedData) => {
    const webApp = { initData: signedData, initDataUnsafe: {}, ready: () => undefined, expand: () => undefined };
    (window as Window & { Telegram?: { WebApp?: typeof webApp } }).Telegram = { WebApp: webApp };
  }, initData);
}

const adminSeller: TelegramUser = {
  id: 990000001, first_name: "E2E Seller", last_name: "Fixture",
  username: "e2e_seller", language_code: "en",
};
const regularBuyer: TelegramUser = {
  id: 990000002, first_name: "E2E Buyer", last_name: "Fixture",
  username: "e2e_buyer", language_code: "en",
};

test("admin moderates a real PostgreSQL listing and preserves an immutable audit trail", async ({ browser }) => {
  const context = await browser.newContext();
  const page = await context.newPage();
  try {
    await installTelegramBridge(page, adminSeller);
    const auth = await context.request.post("http://127.0.0.1:8000/api/auth/telegram", {
      data: { init_data: signedInitData(adminSeller) },
    });
    expect(auth.status()).toBe(200);
    const session = await auth.json() as { access_token: string };
    const headers = { Authorization: "Bearer " + session.access_token };

    const inventoryResponse = await context.request.get("http://127.0.0.1:8000/api/assets/me?limit=100", { headers });
    expect(inventoryResponse.status()).toBe(200);
    const inventory = await inventoryResponse.json() as { items: Array<{ id: string; name: string | null }> };
    const asset = inventory.items.find((item) => item.name === "E2E Verified NFT");
    expect(asset, JSON.stringify(inventory)).toBeTruthy();

    const draftResponse = await context.request.post("http://127.0.0.1:8000/api/listings", {
      headers,
      data: {
        asset_id: asset!.id,
        price_amount: "15.75",
        price_currency: "TON",
        title: "E2E Admin Moderation Listing",
        description: "Disposable API-backed moderation test listing",
      },
    });
    expect(draftResponse.status()).toBe(201);
    const draft = await draftResponse.json() as { id: string };
    const publishResponse = await context.request.post(
      "http://127.0.0.1:8000/api/listings/" + draft.id + "/publish",
      { headers },
    );
    expect(publishResponse.status()).toBe(200);
    expect((await publishResponse.json()).status).toBe("active");

    const queueResponse = await context.request.get("http://127.0.0.1:8000/api/admin/moderation", { headers });
    const queue = await queueResponse.json() as { items: Array<{ id: string; title: string | null }>; detail?: string };
    expect(queueResponse.status(), JSON.stringify(queue)).toBe(200);
    expect(queue.items.some((item) => item.id === draft.id), JSON.stringify(queue)).toBe(true);

    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Moderation & Audit" })).toBeVisible();
    const card = page.locator(".admin-listing").filter({ hasText: "E2E Admin Moderation Listing" });
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "Suspend", exact: true }).click();
    const suspendDialog = page.getByRole("dialog", { name: "Suspend listing" });
    await suspendDialog.getByLabel("Explanation (5–500 characters)").fill("API-backed moderation acceptance");
    await suspendDialog.getByRole("button", { name: "Confirm suspend" }).click();
    await expect(card.getByText("suspended", { exact: true })).toBeVisible();
    await card.getByRole("button", { name: "Audit history" }).click();
    await expect(card.getByText(/suspended.*API-backed moderation acceptance/i)).toBeVisible();

    await card.getByRole("button", { name: "Restore", exact: true }).click();
    const restoreDialog = page.getByRole("dialog", { name: "Restore listing" });
    await restoreDialog.getByLabel("Explanation (5–500 characters)").fill("Fresh ownership verified for restoration");
    await restoreDialog.getByRole("button", { name: "Confirm restore" }).click();
    await expect(card.getByText("active", { exact: true })).toBeVisible();
    await expect(card.getByText(/restored.*Fresh ownership verified for restoration/i)).toBeVisible();

    const buyerPage = await context.newPage();
    await installTelegramBridge(buyerPage, regularBuyer);
    const buyerAuth = await context.request.post("http://127.0.0.1:8000/api/auth/telegram", {
      data: { init_data: signedInitData(regularBuyer) },
    });
    expect(buyerAuth.status()).toBe(200);
    const buyerSession = await buyerAuth.json() as { access_token: string };
    const forbidden = await context.request.get("http://127.0.0.1:8000/api/admin/moderation", {
      headers: { Authorization: "Bearer " + buyerSession.access_token },
    });
    expect(forbidden.status()).toBe(403);

    const cancelResponse = await context.request.post(
      "http://127.0.0.1:8000/api/listings/" + draft.id + "/cancel",
      { headers },
    );
    expect(cancelResponse.status()).toBe(200);
    expect((await cancelResponse.json()).status).toBe("cancelled");
  } finally {
    await context.close();
  }
});
