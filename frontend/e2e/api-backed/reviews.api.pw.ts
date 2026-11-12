import { createHmac } from "node:crypto";

import { expect, test } from "@playwright/test";

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
    query_id: `reviews-${user.id}`,
    user: JSON.stringify(user),
  });
  const checkString = [...params.entries()]
    .sort(([left], [right]) => left.localeCompare(right))
    .map(([key, value]) => `${key}=${value}`)
    .join("\n");
  const secret = createHmac("sha256", "WebAppData").update(botToken).digest();
  params.set("hash", createHmac("sha256", secret).update(checkString).digest("hex"));
  return params.toString();
}

const buyer: TelegramUser = {
  id: 990000002,
  first_name: "E2E Buyer",
  last_name: "Fixture",
  username: "e2e_buyer",
  language_code: "en",
};

const foreignUser: TelegramUser = {
  id: 990000003,
  first_name: "E2E Foreign",
  last_name: "Fixture",
  username: "e2e_foreign",
  language_code: "en",
};

test("completed buyer can submit one safe order-verified seller review", async ({ browser }) => {
  const context = await browser.newContext();
  try {
    const auth = await context.request.post("http://127.0.0.1:5173/api/auth/telegram", {
      data: { init_data: signedInitData(buyer) },
    });
    expect(auth.status()).toBe(200);
    const session = await auth.json() as { access_token: string };
    const headers = { Authorization: `Bearer ${session.access_token}` };

    const ordersResponse = await context.request.get(
      "http://127.0.0.1:5173/api/orders?role=buyer&limit=100",
      { headers },
    );
    expect(ordersResponse.status()).toBe(200);
    const orders = await ordersResponse.json() as {
      items: Array<{ id: string; seller_id: string; status: string }>;
    };
    const completed = orders.items.find((order) => order.status === "completed");
    expect(completed, JSON.stringify(orders)).toBeTruthy();

    const eligibility = await context.request.get(
      `http://127.0.0.1:5173/api/reviews/eligibility?order_id=${completed!.id}`,
      { headers },
    );
    expect(eligibility.status()).toBe(200);
    expect(await eligibility.json()).toMatchObject({
      order_id: completed!.id,
      eligible: true,
      already_reviewed: false,
    });

    const publicPage = await context.request.get(
      `http://127.0.0.1:5173/api/reviews/sellers/${completed!.seller_id}?limit=10&offset=0`,
    );
    expect(publicPage.status()).toBe(200);
    const before = await publicPage.json() as {
      seller_id: string;
      items: Array<Record<string, unknown>>;
    };
    expect(before.seller_id).toBe(completed!.seller_id);
    for (const item of before.items) {
      expect(Object.keys(item).sort()).toEqual(["comment", "created_at", "id", "rating"]);
    }

    const create = await context.request.post("http://127.0.0.1:5173/api/reviews", {
      headers,
      data: { order_id: completed!.id, rating: 5, comment: "  Verified   transfer  " },
    });
    expect(create.status()).toBe(201);
    const created = await create.json() as Record<string, unknown>;
    expect(created).toMatchObject({
      order_id: completed!.id,
      rating: 5,
      comment: "Verified transfer",
    });
    expect(created).not.toHaveProperty("seller_id");
    expect(created).not.toHaveProperty("buyer_id");

    const publicAfter = await context.request.get(
      `http://127.0.0.1:5173/api/reviews/sellers/${completed!.seller_id}?limit=10&offset=0`,
    );
    expect(publicAfter.status()).toBe(200);
    const after = await publicAfter.json() as {
      average_rating: number;
      review_count: number;
      items: Array<{ id: string; rating: number; comment: string | null }>;
    };
    expect(after.review_count).toBeGreaterThanOrEqual(1);
    expect(after.average_rating).toBeGreaterThan(0);
    expect(after.items).toContainEqual(expect.objectContaining({
      id: created.id,
      rating: 5,
      comment: "Verified transfer",
    }));

    const duplicate = await context.request.post("http://127.0.0.1:5173/api/reviews", {
      headers,
      data: { order_id: completed!.id, rating: 1 },
    });
    expect(duplicate.status()).toBe(409);

    const foreignAuth = await context.request.post("http://127.0.0.1:5173/api/auth/telegram", {
      data: { init_data: signedInitData(foreignUser) },
    });
    expect(foreignAuth.status()).toBe(200);
    const foreignSession = await foreignAuth.json() as { access_token: string };
    const foreignEligibility = await context.request.get(
      `http://127.0.0.1:5173/api/reviews/eligibility?order_id=${completed!.id}`,
      { headers: { Authorization: `Bearer ${foreignSession.access_token}` } },
    );
    expect(foreignEligibility.status()).toBe(200);
    expect(await foreignEligibility.json()).toMatchObject({ eligible: false });
  } finally {
    await context.close();
  }
});
