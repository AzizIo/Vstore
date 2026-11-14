import { getApiErrorMessage } from "./errors";

export type EscrowNetwork = "testnet";

export type EscrowState =
  | "awaiting_nft_deposit"
  | "listed"
  | "payment_received"
  | "delivery_pending"
  | "buyer_confirmation_window"
  | "disputed"
  | "refund_pending_nft_return"
  | "settled"
  | "refunded"
  | "seller_withdrawn"
  | "refundable_failure";

export type EscrowAction =
  | "nft_deposit"
  | "purchase"
  | "buyer_confirmation"
  | "dispute"
  | "unsold_nft_withdrawal"
  | "seller_proceeds_withdrawal";

export type EscrowDisputeStatus = "open" | "under_review" | "resolved_buyer" | "resolved_seller";

export interface EscrowNftSnapshot {
  asset_id: string | null;
  title: string;
  image_url: string | null;
  item_address: string;
  collection_address: string | null;
}

export interface EscrowDispute {
  id: string;
  status: EscrowDisputeStatus;
  reason_code: string;
  summary: string | null;
  opened_at: string;
  resolved_at: string | null;
  resolution_note: string | null;
}

export interface EscrowListing {
  id: string;
  seller_id: string;
  state: EscrowState;
  network: EscrowNetwork;
  nft: EscrowNftSnapshot;
  contract_address: string | null;
  seller_wallet_address: string;
  price_ton: string;
  platform_fee_ton: string | null;
  created_at: string;
  updated_at: string;
}

export interface EscrowDeal {
  id: string;
  listing_id: string;
  buyer_id: string;
  seller_id: string;
  state: EscrowState;
  network: EscrowNetwork;
  nft: EscrowNftSnapshot;
  contract_address: string;
  seller_wallet_address: string;
  buyer_wallet_address: string;
  price_ton: string;
  platform_fee_ton: string | null;
  seller_claimable_ton: string | null;
  buyer_confirmation_deadline: string | null;
  dispute_deadline: string | null;
  created_at: string;
  updated_at: string;
  dispute: EscrowDispute | null;
}

export type EscrowWithdrawalKind = "seller_proceeds" | "unsold_nft";
export type EscrowWithdrawalStatus =
  | "prepared"
  | "submitted"
  | "observing"
  | "confirmed"
  | "failed"
  | "manual_review";

export interface EscrowWithdrawal {
  id: string;
  listing_id: string | null;
  deal_id: string | null;
  kind: EscrowWithdrawalKind;
  status: EscrowWithdrawalStatus;
  amount_ton: string | null;
  destination_address: string | null;
  transaction_hash: string | null;
  created_at: string;
  updated_at: string;
}

export interface EscrowPage<T> {
  items: T[];
  total: number;
  next_cursor: string | null;
}

export interface EscrowWalletMessage {
  address: string;
  amount_nanotons: string;
  payload_boc?: string | null;
  state_init_boc?: string | null;
}

export interface PreparedEscrowTransaction {
  id: string;
  action: EscrowAction;
  network: EscrowNetwork;
  contract_address: string;
  nft_item_address: string | null;
  amount_ton: string | null;
  fee_ton: string | null;
  valid_until: string;
  messages: EscrowWalletMessage[];
  display_summary: string;
}

/**
 * These request DTOs are frontend intent types, not approved backend schemas.
 * The adapter configuration below must serialize them to the final API contract.
 */
export interface EscrowPrepareNftDepositInput {
  asset_id: string;
  seller_wallet_id: string;
}

export interface EscrowPreparePurchaseInput {
  listing_id: string;
  buyer_wallet_id: string;
}

export interface EscrowPrepareWalletActionInput {
  deal_id: string;
}

export interface EscrowOpenDisputeInput {
  deal_id: string;
  reason_code: string;
  details?: string;
}

export interface EscrowPrepareUnsoldNftWithdrawalInput {
  listing_id: string;
  seller_wallet_id: string;
}

export interface EscrowPrepareSellerWithdrawalInput {
  deal_id: string;
  seller_wallet_id: string;
}

export interface EscrowWalletReferenceInput {
  target_id: string;
  action: EscrowAction;
  reference: string;
}

/** A serializer returns the actual path and body only after the backend contract is agreed. */
export interface EscrowHttpOperation {
  url: string;
  method?: "POST";
  body?: unknown;
}

/**
 * Route and payload mapping is injected by the host after the escrow API is approved.
 * No /api/escrow endpoint, request body or response path is guessed in this module.
 */
export interface EscrowHttpContract {
  marketplaceListings: () => string;
  sellerListings: () => string;
  buyerDeals: () => string;
  sellerWithdrawals: () => string;
  listingDetails: (listingId: string) => string;
  dealDetails: (dealId: string) => string;
  prepareNftDeposit: (input: EscrowPrepareNftDepositInput) => EscrowHttpOperation;
  preparePurchase: (input: EscrowPreparePurchaseInput) => EscrowHttpOperation;
  prepareBuyerConfirmation: (input: EscrowPrepareWalletActionInput) => EscrowHttpOperation;
  prepareDispute: (input: EscrowOpenDisputeInput) => EscrowHttpOperation;
  prepareUnsoldNftWithdrawal: (input: EscrowPrepareUnsoldNftWithdrawalInput) => EscrowHttpOperation;
  prepareSellerProceedsWithdrawal: (input: EscrowPrepareSellerWithdrawalInput) => EscrowHttpOperation;
  submitWalletReference: (input: EscrowWalletReferenceInput) => EscrowHttpOperation;
}

export interface EscrowApiClient {
  listMarketplaceListings(signal?: AbortSignal): Promise<EscrowPage<EscrowListing>>;
  listSellerListings(signal?: AbortSignal): Promise<EscrowPage<EscrowListing>>;
  listBuyerDeals(signal?: AbortSignal): Promise<EscrowPage<EscrowDeal>>;
  listSellerWithdrawals(signal?: AbortSignal): Promise<EscrowPage<EscrowWithdrawal>>;
  getListing(listingId: string, signal?: AbortSignal): Promise<EscrowListing>;
  getDeal(dealId: string, signal?: AbortSignal): Promise<EscrowDeal>;
  prepareNftDeposit(input: EscrowPrepareNftDepositInput): Promise<PreparedEscrowTransaction>;
  preparePurchase(input: EscrowPreparePurchaseInput): Promise<PreparedEscrowTransaction>;
  prepareBuyerConfirmation(input: EscrowPrepareWalletActionInput): Promise<PreparedEscrowTransaction>;
  prepareDispute(input: EscrowOpenDisputeInput): Promise<PreparedEscrowTransaction>;
  prepareUnsoldNftWithdrawal(input: EscrowPrepareUnsoldNftWithdrawalInput): Promise<PreparedEscrowTransaction>;
  prepareSellerProceedsWithdrawal(input: EscrowPrepareSellerWithdrawalInput): Promise<PreparedEscrowTransaction>;
  submitWalletReference(input: EscrowWalletReferenceInput): Promise<void>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

function isEscrowState(value: unknown): value is EscrowState {
  return value === "awaiting_nft_deposit"
    || value === "listed"
    || value === "payment_received"
    || value === "delivery_pending"
    || value === "buyer_confirmation_window"
    || value === "disputed"
    || value === "refund_pending_nft_return"
    || value === "settled"
    || value === "refunded"
    || value === "seller_withdrawn"
    || value === "refundable_failure";
}

function isNftSnapshot(value: unknown): value is EscrowNftSnapshot {
  if (!isRecord(value)) return false;
  return (value.asset_id === null || typeof value.asset_id === "string")
    && typeof value.title === "string"
    && isNullableString(value.image_url)
    && typeof value.item_address === "string"
    && isNullableString(value.collection_address);
}

function isEscrowDispute(value: unknown): value is EscrowDispute | null {
  if (value === null) return true;
  if (!isRecord(value)) return false;
  return typeof value.id === "string"
    && (value.status === "open" || value.status === "under_review"
      || value.status === "resolved_buyer" || value.status === "resolved_seller")
    && typeof value.reason_code === "string"
    && isNullableString(value.summary)
    && typeof value.opened_at === "string"
    && isNullableString(value.resolved_at)
    && isNullableString(value.resolution_note);
}

export function isEscrowListing(value: unknown): value is EscrowListing {
  if (!isRecord(value)) return false;
  return typeof value.id === "string"
    && typeof value.seller_id === "string"
    && isEscrowState(value.state)
    && value.network === "testnet"
    && isNftSnapshot(value.nft)
    && isNullableString(value.contract_address)
    && typeof value.seller_wallet_address === "string"
    && typeof value.price_ton === "string"
    && isNullableString(value.platform_fee_ton)
    && typeof value.created_at === "string"
    && typeof value.updated_at === "string";
}

export function isEscrowDeal(value: unknown): value is EscrowDeal {
  if (!isRecord(value)) return false;
  return typeof value.id === "string"
    && typeof value.listing_id === "string"
    && typeof value.buyer_id === "string"
    && typeof value.seller_id === "string"
    && isEscrowState(value.state)
    && value.network === "testnet"
    && isNftSnapshot(value.nft)
    && typeof value.contract_address === "string"
    && typeof value.seller_wallet_address === "string"
    && typeof value.buyer_wallet_address === "string"
    && typeof value.price_ton === "string"
    && isNullableString(value.platform_fee_ton)
    && isNullableString(value.seller_claimable_ton)
    && isNullableString(value.buyer_confirmation_deadline)
    && isNullableString(value.dispute_deadline)
    && typeof value.created_at === "string"
    && typeof value.updated_at === "string"
    && isEscrowDispute(value.dispute);
}

export function isEscrowWithdrawal(value: unknown): value is EscrowWithdrawal {
  if (!isRecord(value)) return false;
  return typeof value.id === "string"
    && isNullableString(value.listing_id)
    && isNullableString(value.deal_id)
    && (value.kind === "seller_proceeds" || value.kind === "unsold_nft")
    && (value.status === "prepared" || value.status === "submitted" || value.status === "observing"
      || value.status === "confirmed" || value.status === "failed" || value.status === "manual_review")
    && isNullableString(value.amount_ton)
    && isNullableString(value.destination_address)
    && isNullableString(value.transaction_hash)
    && typeof value.created_at === "string"
    && typeof value.updated_at === "string";
}

export function isPreparedEscrowTransaction(value: unknown): value is PreparedEscrowTransaction {
  if (!isRecord(value) || value.network !== "testnet") return false;
  if (!["nft_deposit", "purchase", "buyer_confirmation", "dispute", "unsold_nft_withdrawal", "seller_proceeds_withdrawal"].includes(String(value.action))) return false;
  return typeof value.id === "string"
    && typeof value.contract_address === "string"
    && isNullableString(value.nft_item_address)
    && isNullableString(value.amount_ton)
    && isNullableString(value.fee_ton)
    && typeof value.valid_until === "string"
    && Number.isFinite(Date.parse(value.valid_until))
    && typeof value.display_summary === "string"
    && Array.isArray(value.messages)
    && value.messages.length > 0
    && value.messages.every((message) => isRecord(message)
      && typeof message.address === "string"
      && typeof message.amount_nanotons === "string"
      && /^\d+$/.test(message.amount_nanotons)
      && isNullableString(message.payload_boc ?? null)
      && isNullableString(message.state_init_boc ?? null));
}

export function isEscrowPage<T>(
  value: unknown,
  isItem: (item: unknown) => item is T,
): value is EscrowPage<T> {
  if (!isRecord(value)) return false;
  return Array.isArray(value.items)
    && value.items.every(isItem)
    && Number.isInteger(value.total)
    && Number(value.total) >= 0
    && isNullableString(value.next_cursor);
}

async function readJson<T>(
  url: string,
  accessToken: string,
  validate: (value: unknown) => value is T,
  init?: RequestInit,
): Promise<T> {
  let response: Response;
  try {
    response = await fetch(url, {
      ...init,
      headers: {
        Authorization: `Bearer ${accessToken}`,
        ...(init?.headers ?? {}),
      },
    });
  } catch (error) {
    if (error instanceof DOMException && error.name === "AbortError") throw error;
    throw new Error("Не удалось связаться с сервисом TON Escrow. Попробуйте ещё раз.");
  }

  if (!response.ok) {
    let message = `Запрос TON Escrow завершился ошибкой (${response.status}).`;
    try {
      message = getApiErrorMessage(await response.json(), message);
    } catch {
      // Keep the HTTP status when the API did not return JSON.
    }
    throw new Error(message);
  }

  let body: unknown;
  try {
    body = await response.json();
  } catch {
    throw new Error("Сервис TON Escrow вернул некорректный JSON.");
  }
  if (!validate(body)) {
    throw new Error("Ответ TON Escrow не соответствует ожидаемому контракту.");
  }
  return body;
}

async function readPage<T>(
  url: string,
  accessToken: string,
  isItem: (value: unknown) => value is T,
  signal?: AbortSignal,
): Promise<EscrowPage<T>> {
  return readJson(url, accessToken, (value): value is EscrowPage<T> => isEscrowPage(value, isItem), { signal });
}

async function writeJson<T>(
  operation: EscrowHttpOperation,
  accessToken: string,
  validate: (value: unknown) => value is T,
): Promise<T> {
  const response = await readJson(
    operation.url,
    accessToken,
    validate,
    {
      method: operation.method ?? "POST",
      headers: { "Content-Type": "application/json" },
      ...(operation.body === undefined ? {} : { body: JSON.stringify(operation.body) }),
    },
  );
  return response;
}

export function createEscrowApiClient(
  accessToken: string,
  contract: EscrowHttpContract,
): EscrowApiClient {
  if (!accessToken.trim()) throw new Error("Для TON Escrow требуется авторизованная сессия.");
  const getPrepared = (operation: EscrowHttpOperation) => writeJson(
    operation,
    accessToken,
    isPreparedEscrowTransaction,
  );

  return {
    listMarketplaceListings: (signal) => readPage(contract.marketplaceListings(), accessToken, isEscrowListing, signal),
    listSellerListings: (signal) => readPage(contract.sellerListings(), accessToken, isEscrowListing, signal),
    listBuyerDeals: (signal) => readPage(contract.buyerDeals(), accessToken, isEscrowDeal, signal),
    listSellerWithdrawals: (signal) => readPage(contract.sellerWithdrawals(), accessToken, isEscrowWithdrawal, signal),
    getListing: (id, signal) => readJson(contract.listingDetails(id), accessToken, isEscrowListing, { signal }),
    getDeal: (id, signal) => readJson(contract.dealDetails(id), accessToken, isEscrowDeal, { signal }),
    prepareNftDeposit: (input) => getPrepared(contract.prepareNftDeposit(input)),
    preparePurchase: (input) => getPrepared(contract.preparePurchase(input)),
    prepareBuyerConfirmation: (input) => getPrepared(contract.prepareBuyerConfirmation(input)),
    prepareDispute: (input) => getPrepared(contract.prepareDispute(input)),
    prepareUnsoldNftWithdrawal: (input) => getPrepared(contract.prepareUnsoldNftWithdrawal(input)),
    prepareSellerProceedsWithdrawal: (input) => getPrepared(contract.prepareSellerProceedsWithdrawal(input)),
    submitWalletReference: async (input) => {
      await writeJson(contract.submitWalletReference(input), accessToken, (value): value is { accepted: boolean } =>
        isRecord(value) && value.accepted === true);
    },
  };
}
