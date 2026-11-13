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
        title: "E2E Admin Moderation Listing Resubmitted",
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
    expect((await publishResponse.json()).status).toBe("pending_review");

    const editPendingResponse = await context.request.patch(
      "http://127.0.0.1:8000/api/listings/" + draft.id,
      { headers, data: { title: "E2E Admin Moderation Listing Resubmitted" } },
    );
    expect(editPendingResponse.status()).toBe(200);
    expect((await editPendingResponse.json()).status).toBe("draft");
    const resubmitResponse = await context.request.post(
      "http://127.0.0.1:8000/api/listings/" + draft.id + "/publish",
      { headers },
    );
    expect(resubmitResponse.status()).toBe(200);
    expect((await resubmitResponse.json()).status).toBe("pending_review");

    const hiddenFromCatalogue = await context.request.get(
      "http://127.0.0.1:8000/api/listings/" + draft.id,
    );
    expect(hiddenFromCatalogue.status()).toBe(404);

    const queueResponse = await context.request.get("http://127.0.0.1:8000/api/admin/moderation", { headers });
    const queue = await queueResponse.json() as { items: Array<{ id: string; title: string | null; status: string }>; detail?: string };
    expect(queueResponse.status(), JSON.stringify(queue)).toBe(200);
    expect(queue.items.some((item) => item.id === draft.id && item.status === "pending_review"), JSON.stringify(queue)).toBe(true);

    await page.goto("/admin");
    await expect(page.getByRole("heading", { name: "Модерация и аудит" })).toBeVisible();
    const card = page.locator(".admin-listing").filter({ hasText: "E2E Admin Moderation Listing" });
    await expect(card).toBeVisible();
    await card.getByRole("button", { name: "Одобрить", exact: true }).click();
    const approveDialog = page.getByRole("dialog", { name: "Одобрить объявление" });
    await approveDialog.getByLabel("Пояснение (5–500 символов)").fill("Fresh ownership verified before publication");
    await approveDialog.getByRole("button", { name: "Подтвердить одобрение" }).click();
    await expect(card.getByText("Активно", { exact: true })).toBeVisible();

    await card.getByRole("button", { name: "Приостановить", exact: true }).click();
    const suspendDialog = page.getByRole("dialog", { name: "Приостановить объявление" });
    await suspendDialog.getByLabel("Пояснение (5–500 символов)").fill("API-backed moderation acceptance");
    await suspendDialog.getByRole("button", { name: "Подтвердить приостановку" }).click();
    await expect(card.getByText("Приостановлено", { exact: true })).toBeVisible();
    await card.getByRole("button", { name: "История аудита" }).click();
    await expect(card.getByText(/Приостановлено.*API-backed moderation acceptance/i)).toBeVisible();

    await card.getByRole("button", { name: "Восстановить", exact: true }).click();
    const restoreDialog = page.getByRole("dialog", { name: "Восстановить объявление" });
    await restoreDialog.getByLabel("Пояснение (5–500 символов)").fill("Fresh ownership verified for restoration");
    await restoreDialog.getByRole("button", { name: "Подтвердить восстановление" }).click();
    await expect(card.getByText("Активно", { exact: true })).toBeVisible();
    await expect(card.getByText(/Восстановлено.*Fresh ownership verified for restoration/i)).toBeVisible();

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

    const rejectedDraftResponse = await context.request.post("http://127.0.0.1:8000/api/listings", {
      headers,
      data: {
        asset_id: asset!.id,
        price_amount: "16.25",
        price_currency: "TON",
        title: "E2E Rejected Moderation Listing",
        description: "Disposable rejection-path test listing",
      },
    });
    expect(rejectedDraftResponse.status()).toBe(201);
    const rejectedDraft = await rejectedDraftResponse.json() as { id: string };
    const rejectedSubmission = await context.request.post(
      "http://127.0.0.1:8000/api/listings/" + rejectedDraft.id + "/publish",
      { headers },
    );
    expect(rejectedSubmission.status()).toBe(200);
    expect((await rejectedSubmission.json()).status).toBe("pending_review");

    const pendingQueueResponse = await context.request.get(
      "http://127.0.0.1:8000/api/admin/moderation",
      { headers },
    );
    const pendingQueue = await pendingQueueResponse.json() as {
      items: Array<{ id: string; status: string }>;
    };
    expect(pendingQueueResponse.status()).toBe(200);
    expect(
      pendingQueue.items.some((item) => item.id === rejectedDraft.id && item.status === "pending_review"),
      JSON.stringify(pendingQueue),
    ).toBe(true);

    const rejectionResponse = await context.request.post(
      "http://127.0.0.1:8000/api/admin/listings/" + rejectedDraft.id + "/decision",
      {
        headers: {
          ...headers,
          "Idempotency-Key": "reject-e2e-request-0001",
          "X-Request-ID": "reject-e2e-request-0001",
        },
        data: {
          action: "reject",
          reason_code: "policy_violation",
          reason: "Rejected by the moderation acceptance test",
        },
      },
    );
    expect(rejectionResponse.status()).toBe(200);
    expect((await rejectionResponse.json()).action).toBe("rejected");
    const sellerListingsResponse = await context.request.get(
      "http://127.0.0.1:8000/api/listings/me",
      { headers },
    );
    const sellerListings = await sellerListingsResponse.json() as {
      items: Array<{ id: string; status: string }>;
    };
    expect(sellerListings.items.find((item) => item.id === rejectedDraft.id)?.status).toBe("cancelled");
  } finally {
    await context.close();
  }
});
