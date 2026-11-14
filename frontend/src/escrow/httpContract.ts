import type { EscrowHttpContract, EscrowHttpOperation } from "../api/escrow";
import { API_BASE_URL } from "../api/config";

function idempotencyHeaders(): Record<string, string> {
  return { "Idempotency-Key": crypto.randomUUID() };
}

function post(url: string, body?: unknown): EscrowHttpOperation {
  return {
    url,
    method: "POST",
    headers: idempotencyHeaders(),
    ...(body === undefined ? {} : { body }),
  };
}

/** Concrete testnet-only HTTP mapping for the backend escrow router. */
export function createEscrowHttpContract(baseUrl = API_BASE_URL): EscrowHttpContract {
  const root = `${baseUrl}/api/escrow`;
  const deal = (id: string) => `${root}/deals/${encodeURIComponent(id)}`;
  const listing = (id: string) => `${root}/listing-intents/${encodeURIComponent(id)}`;

  return {
    marketplaceListings: () => `${root}/marketplace/listing-intents?limit=50&offset=0`,
    sellerListings: () => `${root}/listing-intents?limit=50&offset=0`,
    buyerDeals: () => `${root}/buyer/deals?limit=50&offset=0`,
    sellerDeals: () => `${root}/seller/deals?limit=50&offset=0`,
    sellerWithdrawals: () => `${root}/seller/withdrawals`,
    listingDetails: listing,
    dealDetails: deal,
    createListingIntent: (input) => post(`${root}/listing-intents`, input),
    createBuyerDealIntent: (input) => post(`${root}/deals`, input),
    prepareDealEscrow: ({ deal_id }) => post(`${deal(deal_id)}/prepare/create-deal-escrow`),
    prepareNftDeposit: ({ deal_id }) => post(`${deal(deal_id)}/prepare/deposit-nft`),
    prepareBuyerFunding: ({ deal_id }) => post(`${deal(deal_id)}/prepare/funding`),
    prepareBuyerAcceptance: ({ deal_id }) => post(`${deal(deal_id)}/prepare/accept`),
    prepareDispute: ({ deal_id, reason }) => post(`${deal(deal_id)}/prepare/dispute`, { reason }),
    prepareBuyerNftReturn: ({ deal_id }) => post(`${deal(deal_id)}/prepare/nft-return`),
    prepareUnsoldNftWithdrawal: ({ deal_id }) => post(`${deal(deal_id)}/prepare/withdraw-unsold-nft`),
    submitWalletReference: (input) => post(`${root}/wallet-references`, input),
  };
}
