import { describe, expect, it } from "vitest";

import { createEscrowHttpContract } from "../../escrow/httpContract";

describe("TON escrow HTTP contract", () => {
  it("maps reads to the testnet escrow API namespace", () => {
    const contract = createEscrowHttpContract("/api-host");
    expect(contract.marketplaceListings()).toBe("/api-host/api/escrow/marketplace/listing-intents?limit=50&offset=0");
    expect(contract.sellerListings()).toBe("/api-host/api/escrow/listing-intents?limit=50&offset=0");
    expect(contract.buyerDeals()).toBe("/api-host/api/escrow/buyer/deals?limit=50&offset=0");
    expect(contract.sellerDeals()).toBe("/api-host/api/escrow/seller/deals?limit=50&offset=0");
    expect(contract.listingDetails("listing/1")).toContain("/listing-intents/listing%2F1");
    expect(contract.dealDetails("deal/1")).toContain("/deals/deal%2F1");
  });

  it("adds an idempotency key to every write operation", () => {
    const contract = createEscrowHttpContract();
    const context = {
      escrow_address: "0:" + "2".repeat(64),
      nft: { asset_id: "asset", title: "NFT", image_url: null, item_address: "0:" + "1".repeat(64), collection_address: null },
      price_nano: "1000000000",
      fee_bps: 0 as const,
    };
    const operations = [
      contract.createListingIntent({ asset_id: "asset", seller_wallet_id: "wallet", price_nano: "1000000000" }),
      contract.createBuyerDealIntent({ listing_id: "listing", buyer_wallet_id: "wallet" }),
      contract.prepareDealEscrow({ deal_id: "deal", wallet_id: "wallet", context }),
      contract.prepareDealActivation({ deal_id: "deal", wallet_id: "wallet", context }),
      contract.prepareNftDeposit({ deal_id: "deal", wallet_id: "wallet", context }),
      contract.prepareBuyerFunding({ deal_id: "deal", wallet_id: "wallet", context }),
      contract.prepareBuyerAcceptance({ deal_id: "deal", wallet_id: "wallet", context }),
      contract.prepareDispute({ deal_id: "deal", reason: "Test reason", context }),
      contract.prepareBuyerNftReturn({ deal_id: "deal", wallet_id: "wallet", context }),
      contract.prepareUnsoldNftWithdrawal({ deal_id: "deal", wallet_id: "wallet", context }),
      contract.prepareFailedOutboundRetry({ deal_id: "deal", query_id: "18446744073709551615", context }),
      contract.submitWalletReference({ action_id: "action", action: "retry_failed_outbound_action", reference: "digest" }),
    ];

    for (const operation of operations) {
      expect(operation.method).toBe("POST");
      expect(operation.headers?.["Idempotency-Key"]).toBeTruthy();
      expect((operation.headers?.["Idempotency-Key"] ?? "").length).toBeGreaterThan(8);
    }
  });

  it("maps retry discovery to a read and retry preparation to an idempotent write", () => {
    const contract = createEscrowHttpContract("/api-host");
    expect(contract.retryableOutboundActions("deal/1")).toBe(
      "/api-host/api/escrow/deals/deal%2F1/retryable-outbound-actions",
    );
    const retry = contract.prepareFailedOutboundRetry({
      deal_id: "deal/1",
      query_id: "18446744073709551615",
      context: {
        escrow_address: "0:" + "2".repeat(64),
        nft: { asset_id: "asset", title: "NFT", image_url: null, item_address: "0:" + "1".repeat(64), collection_address: null },
        price_nano: "1000000000",
        fee_bps: 0,
      },
    });
    expect(retry.url).toBe(
      "/api-host/api/escrow/deals/deal%2F1/prepare/retry-failed-outbound-action",
    );
    expect(retry.body).toEqual({ query_id: "18446744073709551615" });
    expect(retry.headers?.["Idempotency-Key"]).toBeTruthy();
  });


  it("maps seller activation to the dedicated idempotent preparation route", () => {
    const contract = createEscrowHttpContract("/api-host");
    const activation = contract.prepareDealActivation({
      deal_id: "deal/1",
      wallet_id: "seller-wallet",
      context: {
        escrow_address: "0:" + "2".repeat(64),
        nft: { asset_id: "asset", title: "NFT", image_url: null, item_address: "0:" + "1".repeat(64), collection_address: null },
        price_nano: "1000000000",
        fee_bps: 0,
      },
    });
    expect(activation.url).toBe("/api-host/api/escrow/deals/deal%2F1/prepare/activate-deal");
    expect(activation.body).toBeUndefined();
    expect(activation.headers?.["Idempotency-Key"]).toBeTruthy();
  });

  it("keeps dispute reason in the request body and wallet actions address-scoped", () => {
    const contract = createEscrowHttpContract();
    const dispute = contract.prepareDispute({ deal_id: "deal-id", reason: "NFT was not deposited" });
    expect(dispute.url).toContain("/deals/deal-id/prepare/dispute");
    expect(dispute.body).toEqual({ reason: "NFT was not deposited" });

    const funding = contract.prepareBuyerFunding({
      deal_id: "deal-id",
      wallet_id: "wallet-id",
      context: {
        escrow_address: "0:" + "2".repeat(64),
        nft: { asset_id: "asset", title: "NFT", image_url: null, item_address: "0:" + "1".repeat(64), collection_address: null },
        price_nano: "1000000000",
        fee_bps: 0,
      },
    });
    expect(funding.url).toContain("/deals/deal-id/prepare/funding");
    expect(funding.body).toBeUndefined();
  });
});
