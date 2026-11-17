import type { EscrowHttpContract, EscrowHttpOperation } from "../api/escrow";
import { API_BASE_URL } from "../api/config";

function post(url: string, body?: unknown, keys?: Map<string, string>): EscrowHttpOperation {
  const fingerprint = `${url}:${JSON.stringify(body ?? null)}`;
  let key = keys?.get(fingerprint);
  if (!key) {
    key = crypto.randomUUID();
    keys?.set(fingerprint, key);
  }
  return {
    url,
    method: "POST",
    headers: { "Idempotency-Key": key },
    ...(body === undefined ? {} : { body }),
  };
}

/** Concrete testnet-only HTTP mapping for the backend escrow router. */
export function createEscrowHttpContract(baseUrl = API_BASE_URL): EscrowHttpContract {
  const root = `${baseUrl}/api/escrow`;
  const idempotencyKeys = new Map<string, string>();
  const write = (url: string, body?: unknown) => post(url, body, idempotencyKeys);
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
    createListingIntent: (input) => write(`${root}/listing-intents`, input),
    createBuyerDealIntent: (input) => write(`${root}/deals`, input),
    prepareDealEscrow: ({ deal_id }) => write(`${deal(deal_id)}/prepare/create-deal-escrow`),
    prepareDealActivation: ({ deal_id }) => write(`${deal(deal_id)}/prepare/activate-deal`),
    prepareNftDeposit: ({ deal_id }) => write(`${deal(deal_id)}/prepare/deposit-nft`),
    prepareBuyerFunding: ({ deal_id }) => write(`${deal(deal_id)}/prepare/funding`),
    prepareBuyerAcceptance: ({ deal_id }) => write(`${deal(deal_id)}/prepare/accept`),
    prepareDispute: ({ deal_id, reason }) => write(`${deal(deal_id)}/prepare/dispute`, { reason }),
    prepareBuyerNftReturn: ({ deal_id }) => write(`${deal(deal_id)}/prepare/nft-return`),
    prepareUnsoldNftWithdrawal: ({ deal_id }) => write(`${deal(deal_id)}/prepare/withdraw-unsold-nft`),
    retryableOutboundActions: (dealId) => `${deal(dealId)}/retryable-outbound-actions`,
    prepareFailedOutboundRetry: ({ deal_id, query_id }) =>
      write(`${deal(deal_id)}/prepare/retry-failed-outbound-action`, { query_id }),
    submitWalletReference: (input) => write(`${root}/wallet-references`, input),
  };
}
