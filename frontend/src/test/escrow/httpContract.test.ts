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
    const operations = [
      contract.createListingIntent({ asset_id: "asset", seller_wallet_id: "wallet", price_nano: "1000000000" }),
      contract.createBuyerDealIntent({ listing_id: "listing", buyer_wallet_id: "wallet" }),
      contract.prepareDealEscrow({ deal_id: "deal", wallet_id: "wallet" }),
      contract.prepareDealActivation({ deal_id: "deal", wallet_id: "wallet" }),
      contract.prepareNftDeposit({ deal_id: "deal", wallet_id: "wallet" }),
      contract.prepareBuyerFunding({ deal_id: "deal", wallet_id: "wallet" }),
      contract.prepareBuyerAcceptance({ deal_id: "deal", wallet_id: "wallet" }),
      contract.prepareDispute({ deal_id: "deal", reason: "Test reason" }),
      contract.prepareBuyerNftReturn({ deal_id: "deal", wallet_id: "wallet" }),
      contract.prepareUnsoldNftWithdrawal({ deal_id: "deal", wallet_id: "wallet" }),
      contract.submitWalletReference({ action_id: "action", action: "fund_deal", reference: "digest" }),
    ];

    for (const operation of operations) {
      expect(operation.method).toBe("POST");
      expect(operation.headers?.["Idempotency-Key"]).toBeTruthy();
      expect((operation.headers?.["Idempotency-Key"] ?? "").length).toBeGreaterThan(8);
    }
  });

  it("keeps dispute reason in the request body and wallet actions address-scoped", () => {
    const contract = createEscrowHttpContract();
    const dispute = contract.prepareDispute({ deal_id: "deal-id", reason: "NFT was not deposited" });
    expect(dispute.url).toContain("/deals/deal-id/prepare/dispute");
    expect(dispute.body).toEqual({ reason: "NFT was not deposited" });

    const funding = contract.prepareBuyerFunding({ deal_id: "deal-id", wallet_id: "wallet-id" });
    expect(funding.url).toContain("/deals/deal-id/prepare/funding");
    expect(funding.body).toBeUndefined();

    const activation = contract.prepareDealActivation({ deal_id: "deal-id", wallet_id: "wallet-id" });
    expect(activation.url).toContain("/deals/deal-id/prepare/activate-deal");
    expect(activation.body).toBeUndefined();
  });
});
