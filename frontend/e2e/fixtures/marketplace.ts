import type { Page } from "@playwright/test";

export const listingIds = {
  moon: "11111111-1111-4111-8111-111111111111",
  dragon: "22222222-2222-4222-8222-222222222222",
  rose: "33333333-3333-4333-8333-333333333333",
};

export const orderId = "aaaaaaaa-aaaa-4aaa-8aaa-aaaaaaaaaaaa";

export const moonLantern = {
  id: listingIds.moon,
  status: "active",
  price_amount: "12.5",
  price_currency: "TON",
  title: "Moon Lantern",
  description: "A collectible lantern.",
  created_at: "2026-01-03T00:00:00Z",
  expires_at: null,
  asset: {
    id: "asset-moon",
    asset_type: "ton_nft",
    external_id: "moon-nft-001",
    item_address: "0:aaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaaa",
    name: "Moon Lantern NFT",
    description: "A verified TON collectible.",
    image_url: null,
    verification_status: "verified",
    collection: {
      id: "collection-moon",
      address: "0:bbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbbb",
      network: "mainnet",
      name: "Night Sky",
      marketplace_name: "VILTARA",
    },
  },
  seller: { id: "seller-1", username: "collector", first_name: "Ari" },
};

export const dragonEgg = {
  ...moonLantern,
  id: listingIds.dragon,
  price_amount: "5",
  title: "Dragon Egg",
  created_at: "2026-01-02T00:00:00Z",
  asset: {
    ...moonLantern.asset,
    id: "asset-dragon",
    external_id: "dragon-egg-001",
    name: "Dragon Egg NFT",
  },
};

export const roseGift = {
  ...moonLantern,
  id: listingIds.rose,
  price_amount: "20",
  price_currency: "XTR",
  title: "Rose Bouquet",
  created_at: "2026-01-01T00:00:00Z",
  asset: {
    ...moonLantern.asset,
    id: "asset-rose",
    asset_type: "telegram_gift",
    external_id: "telegram-gift-rose-001",
    item_address: null,
    name: "Rose Gift",
    collection: null,
  },
  seller: { id: "seller-2", username: "giftmaker", first_name: "Mira" },
};

const catalogListings = [moonLantern, dragonEgg, roseGift];

const verifiedInventoryAsset = {
  id: "asset-moon",
  asset_type: "ton_nft",
  external_id: moonLantern.asset.external_id,
  item_address: moonLantern.asset.item_address,
  collection_address: moonLantern.asset.collection.address,
  name: "Moon Lantern NFT",
  description: "A verified TON collectible.",
  image_url: null,
  verification_status: "verified",
  eligible_for_listing: true,
};

const inventoryPage = {
  items: [verifiedInventoryAsset],
  wallet_id: "wallet-e2e",
  limit: 24,
  offset: 0,
  next_offset: 1,
  has_more: false,
};

const draftListing = {
  ...moonLantern,
  id: "bbbbbbbb-bbbb-4bbb-8bbb-bbbbbbbbbbbb",
  status: "draft",
  price_amount: "1.5",
  title: "Draft Moon Lantern",
};

const profile = {
  id: "buyer-1",
  telegram_id: 123456789,
  username: "e2e_buyer",
  first_name: "Alex",
  last_name: "Example",
  language_code: "ru",
};

const authResponse = {
  access_token: "e2e-mock-access-token",
  token_type: "bearer",
  expires_in: 3600,
  user: {
    id: profile.id,
    telegram_id: profile.telegram_id,
    username: profile.username,
    first_name: profile.first_name,
    last_name: profile.last_name,
  },
};

const linkedOrder = {
  id: orderId,
  listing_id: listingIds.moon,
  buyer_id: profile.id,
  seller_id: "seller-1",
  status: "reserved",
  price_amount: "12.5",
  price_currency: "TON",
  title: "Moon Lantern",
  asset_name: "Moon Lantern NFT",
  asset_type: "ton_nft",
  expires_at: "2099-01-01T00:15:00Z",
  created_at: "2026-01-01T00:00:00Z",
  updated_at: "2026-01-01T00:00:00Z",
  events: [
    {
      from_status: null,
      to_status: "reserved",
      actor_type: "buyer",
      created_at: "2026-01-01T00:00:00Z",
    },
  ],
};

export interface MarketplaceMockOptions {
  authenticated?: boolean;
  startParam?: string;
  catalogFailures?: number;
  missingListingDetail?: boolean;
  myListingsFailure?: boolean;
  inventoryFailure?: boolean;
  draftCreationFailure?: boolean;
  ordersFailure?: boolean;
  orderDetailFailure?: boolean;
  sellerReviewsFailure?: boolean;
}

function jsonBody(body: unknown) {
  return JSON.stringify(body);
}

/**
 * Stubs Telegram's WebApp bridge and all backend endpoints. No request from
 * these tests can reach a real API, database, Telegram account or wallet.
 */
export async function mockMarketplaceApi(
  page: Page,
  options: MarketplaceMockOptions = {},
): Promise<string[]> {
  const requests: string[] = [];
  let remainingCatalogFailures = options.catalogFailures ?? 0;

  await page.addInitScript(
    ({ initData, startParam }) => {
      const webApp = {
        initData,
        initDataUnsafe: startParam ? { start_param: startParam } : {},
        ready: () => undefined,
        expand: () => undefined,
      };
      (window as Window & { Telegram?: { WebApp?: typeof webApp } }).Telegram = {
        WebApp: webApp,
      };
    },
    {
      initData: options.authenticated ? "query_id=e2e&hash=not-a-real-signature" : "",
      startParam: options.startParam ?? null,
    },
  );

  // The real Telegram script is deliberately not downloaded in browser tests.
  await page.route("https://telegram.org/js/telegram-web-app.js", (route) => route.abort());

  await page.route((url) => new URL(url).pathname.startsWith("/api/"), async (route) => {
    const request = route.request();
    const url = new URL(request.url());
    const method = request.method();
    const path = url.pathname;
    requests.push(`${method} ${path}${url.search}`);

    const fulfillJson = (body: unknown, status = 200) =>
      route.fulfill({
        status,
        contentType: "application/json",
        body: jsonBody(body),
      });

    if (path === "/api/auth/telegram" && method === "POST") {
      return options.authenticated
        ? fulfillJson(authResponse)
        : fulfillJson({ detail: "Авторизация Telegram отключена в этом тесте." }, 401);
    }

    if (path === "/api/users/me" && method === "GET" && options.authenticated) {
      return fulfillJson(profile);
    }

    if (path === "/api/listings" && method === "GET") {
      if (remainingCatalogFailures > 0) {
        remainingCatalogFailures -= 1;
        return fulfillJson({ detail: "Каталог временно недоступен." }, 503);
      }

      const search = (url.searchParams.get("search") ?? "").trim().toLowerCase();
      const assetType = url.searchParams.get("asset_type");
      const currency = url.searchParams.get("currency");
      const minPrice = url.searchParams.get("min_price");
      const maxPrice = url.searchParams.get("max_price");
      const sort = url.searchParams.get("sort") ?? "newest";
      const limit = Number(url.searchParams.get("limit") ?? 24);
      const offset = Number(url.searchParams.get("offset") ?? 0);

      let items = [...catalogListings];
      if (search) {
        items = items.filter((listing) =>
          [listing.title, listing.asset.name, listing.description]
            .some((value) => value?.toLowerCase().includes(search)),
        );
      }
      if (assetType) {
        items = items.filter((listing) => listing.asset.asset_type === assetType);
      }
      if (currency) {
        items = items.filter((listing) => listing.price_currency === currency);
      }
      if (minPrice) {
        items = items.filter((listing) => Number(listing.price_amount) >= Number(minPrice));
      }
      if (maxPrice) {
        items = items.filter((listing) => Number(listing.price_amount) <= Number(maxPrice));
      }
      if (sort === "price_asc") {
        items.sort((a, b) => Number(a.price_amount) - Number(b.price_amount));
      } else if (sort === "price_desc") {
        items.sort((a, b) => Number(b.price_amount) - Number(a.price_amount));
      } else {
        items.sort((a, b) => b.created_at.localeCompare(a.created_at));
      }

      return fulfillJson({
        items: items.slice(offset, offset + limit),
        total: items.length,
        limit,
        offset,
      });
    }

    if (path === "/api/listings/me" && method === "GET" && options.authenticated) {
      if (options.myListingsFailure) {
        return fulfillJson({ detail: "Ваши объявления временно недоступны." }, 503);
      }
      return fulfillJson([moonLantern]);
    }

    if (path === "/api/assets/me" && method === "GET" && options.authenticated) {
      if (options.inventoryFailure) {
        return fulfillJson({ detail: "Инвентарь временно недоступен." }, 503);
      }
      const limit = Number(url.searchParams.get("limit") ?? 24);
      const offset = Number(url.searchParams.get("offset") ?? 0);
      return fulfillJson({
        ...inventoryPage,
        items: inventoryPage.items.slice(offset, offset + limit),
        limit,
        offset,
        next_offset: offset + inventoryPage.items.slice(offset, offset + limit).length,
      });
    }

    if (path === "/api/listings" && method === "POST" && options.authenticated) {
      if (options.draftCreationFailure) {
        return fulfillJson({ detail: "Не удалось сохранить черновик. Попробуйте ещё раз." }, 503);
      }
      const payload = request.postDataJSON() as {
        title?: string | null;
        price_amount?: string;
        price_currency?: string;
        description?: string | null;
      };
      return fulfillJson({
        ...draftListing,
        title: payload.title ?? draftListing.title,
        price_amount: payload.price_amount ?? draftListing.price_amount,
        price_currency: payload.price_currency ?? draftListing.price_currency,
        description: payload.description ?? draftListing.description,
      }, 201);
    }

    const listingMatch = /^\/api\/listings\/([^/]+)$/.exec(path);
    if (listingMatch && method === "GET") {
      if (options.missingListingDetail) {
        return fulfillJson({ detail: "Объявление не найдено." }, 404);
      }
      const id = decodeURIComponent(listingMatch[1]);
      const listing = catalogListings.find((item) => item.id === id);
      return listing
        ? fulfillJson(listing)
        : fulfillJson({ detail: "Listing not found." }, 404);
    }

    if (path === "/api/reviews/sellers/seller-1" && method === "GET") {
      if (options.sellerReviewsFailure) {
        return fulfillJson({ detail: "Отзывы временно недоступны." }, 503);
      }
      return fulfillJson({
        seller_id: "seller-1",
        average_rating: 0,
        review_count: 0,
        rating_distribution: { "1": 0, "2": 0, "3": 0, "4": 0, "5": 0 },
        items: [],
        limit: 10,
        offset: 0,
        has_more: false,
      });
    }

    if (path === "/api/orders" && method === "POST" && options.authenticated) {
      return fulfillJson(linkedOrder, 201);
    }

    if (path === `/api/orders/${orderId}/cancel` && method === "POST" && options.authenticated) {
      return fulfillJson({
        ...linkedOrder,
        status: "cancelled",
        updated_at: "2026-01-01T00:05:00Z",
        events: [
          ...linkedOrder.events,
          {
            from_status: "reserved",
            to_status: "cancelled",
            actor_type: "buyer",
            created_at: "2026-01-01T00:05:00Z",
          },
        ],
      });
    }

    if (path === `/api/orders/${orderId}` && method === "GET" && options.authenticated) {
      if (options.orderDetailFailure) {
        return fulfillJson({ detail: "Данные заказа временно недоступны." }, 503);
      }
      return fulfillJson(linkedOrder);
    }

    if (path === "/api/orders" && method === "GET" && options.authenticated) {
      if (options.ordersFailure) {
        return fulfillJson({ detail: "Список заказов временно недоступен." }, 503);
      }
      return fulfillJson({ items: [linkedOrder] });
    }

    return fulfillJson({ detail: `Для метода ${method} и пути ${path} нет тестовой заглушки.` }, 404);
  });

  return requests;
}
