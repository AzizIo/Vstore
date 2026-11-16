import { getApiErrorMessage } from "./errors";

export type EscrowNetwork = "testnet";

export type EscrowListingState =
  | "intent_only"
  | "active"
  | "reserved"
  | "cancelled"
  | "manual_review";

export type EscrowDealState =
  | "intent_created"
  | "awaiting_nft"
  | "awaiting_buyer_funds"
  | "funded_review"
  | "nft_release_pending"
  | "delivered_dispute_window"
  | "disputed"
  | "nft_return_pending"
  | "seller_payout_pending"
  | "buyer_refund_pending"
  | "settled"
  | "refunded"
  | "expired"
  | "manual_review";

export type EscrowListingAction = "create_deal_intent" | "cancel_listing_intent";

export type EscrowAction =
  | "create_deal_escrow"
  | "activate_deal"
  | "deposit_nft"
  | "fund_deal"
  | "accept_deal"
  | "open_dispute"
  | "return_nft_to_escrow"
  | "withdraw_unsold_nft"
  | "retry_failed_outbound_action";

export type EscrowDisputeStatus =
  | "open"
  | "under_review"
  | "resolved_buyer"
  | "resolved_seller";

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

export interface EscrowListingIntent {
  id: string;
  listing_key: string | null;
  seller_id: string;
  state: EscrowListingState;
  network: EscrowNetwork;
  nft: EscrowNftSnapshot;
  seller_wallet_address: string;
  price_nano: string;
  fee_bps: 0;
  available_actions: EscrowListingAction[];
  created_at: string;
  updated_at: string;
}

export interface EscrowDeal {
  id: string;
  listing_id: string;
  listing_key: string;
  buyer_id: string;
  seller_id: string;
  state: EscrowDealState;
  network: EscrowNetwork;
  nft: EscrowNftSnapshot;
  escrow_address: string | null;
  seller_wallet_address: string;
  buyer_wallet_address: string;
  price_nano: string;
  fee_bps: 0;
  buyer_review_deadline: string | null;
  dispute_deadline: string | null;
  available_actions: EscrowAction[];
  created_at: string;
  updated_at: string;
  dispute: EscrowDispute | null;
}

export type EscrowWithdrawalStatus =
  | "prepared"
  | "submitted"
  | "observing"
  | "confirmed"
  | "failed"
  | "manual_review";

export interface EscrowWithdrawal {
  id: string;
  deal_id: string;
  kind: "unsold_nft";
  status: EscrowWithdrawalStatus;
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
  amount_nano: string;
  payload_boc?: string | null;
  state_init_boc?: string | null;
}

export interface PreparedEscrowTransaction {
  action_id: string;
  action: EscrowAction;
  network: EscrowNetwork;
  factory_address: null;
  escrow_address: string;
  nft_item_address: string;
  price_nano: string | null;
  fee_bps: 0;
  execution_reserve_nano: string | null;
  valid_until: string;
  messages: EscrowWalletMessage[];
  display_purpose: string;
}

export interface EscrowCreateListingIntentInput {
  asset_id: string;
  seller_wallet_id: string;
  price_nano: string;
}

export interface EscrowCreateBuyerDealIntentInput {
  listing_id: string;
  buyer_wallet_id: string;
}

export interface EscrowPrepareDealActionInput {
  deal_id: string;
  wallet_id: string;
}

export interface EscrowRetryFailedOutboundInput {
  deal_id: string;
  query_id: string;
}

export interface EscrowRetryableOutboundAction {
  query_id: string;
  slot: "first" | "second";
  kind: number;
  recipient_address: string;
  amount_nanotons: string;
  retry_window_seconds: number;
  proof_masterchain_seqno: number;
  proof_masterchain_block_hash: string;
  proof_state_data_hash: string;
  proof_provider_id: string;
}

export interface EscrowOpenDisputeInput {
  deal_id: string;
  reason: string;
}

export interface EscrowWalletReferenceInput {
  action_id: string;
  action: EscrowAction;
  reference: string;
}

/** Endpoint paths and payload serializers are injected only after the shared API is approved. */
export interface EscrowHttpOperation {
  url: string;
  method?: "POST";
  headers?: Record<string, string>;
  body?: unknown;
}

export interface EscrowHttpContract {
  marketplaceListings: () => string;
  sellerListings: () => string;
  buyerDeals: () => string;
  sellerDeals: () => string;
  sellerWithdrawals: () => string;
  listingDetails: (listingId: string) => string;
  dealDetails: (dealId: string) => string;
  createListingIntent: (input: EscrowCreateListingIntentInput) => EscrowHttpOperation;
  createBuyerDealIntent: (input: EscrowCreateBuyerDealIntentInput) => EscrowHttpOperation;
  prepareDealEscrow: (input: EscrowPrepareDealActionInput) => EscrowHttpOperation;
  prepareDealActivation: (input: EscrowPrepareDealActionInput) => EscrowHttpOperation;
  prepareNftDeposit: (input: EscrowPrepareDealActionInput) => EscrowHttpOperation;
  prepareBuyerFunding: (input: EscrowPrepareDealActionInput) => EscrowHttpOperation;
  prepareBuyerAcceptance: (input: EscrowPrepareDealActionInput) => EscrowHttpOperation;
  prepareDispute: (input: EscrowOpenDisputeInput) => EscrowHttpOperation;
  prepareBuyerNftReturn: (input: EscrowPrepareDealActionInput) => EscrowHttpOperation;
  prepareUnsoldNftWithdrawal: (input: EscrowPrepareDealActionInput) => EscrowHttpOperation;
  retryableOutboundActions: (dealId: string) => string;
  prepareFailedOutboundRetry: (input: EscrowRetryFailedOutboundInput) => EscrowHttpOperation;
  submitWalletReference: (input: EscrowWalletReferenceInput) => EscrowHttpOperation;
}

export interface EscrowApiClient {
  listMarketplaceListings(signal?: AbortSignal): Promise<EscrowPage<EscrowListingIntent>>;
  listSellerListings(signal?: AbortSignal): Promise<EscrowPage<EscrowListingIntent>>;
  listBuyerDeals(signal?: AbortSignal): Promise<EscrowPage<EscrowDeal>>;
  listSellerDeals(signal?: AbortSignal): Promise<EscrowPage<EscrowDeal>>;
  listSellerWithdrawals(signal?: AbortSignal): Promise<EscrowPage<EscrowWithdrawal>>;
  getListing(listingId: string, signal?: AbortSignal): Promise<EscrowListingIntent>;
  getDeal(dealId: string, signal?: AbortSignal): Promise<EscrowDeal>;
  createListingIntent(input: EscrowCreateListingIntentInput): Promise<EscrowListingIntent>;
  createBuyerDealIntent(input: EscrowCreateBuyerDealIntentInput): Promise<EscrowDeal>;
  prepareDealEscrow(input: EscrowPrepareDealActionInput): Promise<PreparedEscrowTransaction>;
  prepareDealActivation(input: EscrowPrepareDealActionInput): Promise<PreparedEscrowTransaction>;
  prepareNftDeposit(input: EscrowPrepareDealActionInput): Promise<PreparedEscrowTransaction>;
  prepareBuyerFunding(input: EscrowPrepareDealActionInput): Promise<PreparedEscrowTransaction>;
  prepareBuyerAcceptance(input: EscrowPrepareDealActionInput): Promise<PreparedEscrowTransaction>;
  prepareDispute(input: EscrowOpenDisputeInput): Promise<PreparedEscrowTransaction>;
  prepareBuyerNftReturn(input: EscrowPrepareDealActionInput): Promise<PreparedEscrowTransaction>;
  prepareUnsoldNftWithdrawal(input: EscrowPrepareDealActionInput): Promise<PreparedEscrowTransaction>;
  listRetryableOutboundActions(dealId: string, signal?: AbortSignal): Promise<EscrowRetryableOutboundAction[]>;
  prepareFailedOutboundRetry(input: EscrowRetryFailedOutboundInput): Promise<PreparedEscrowTransaction>;
  submitWalletReference(input: EscrowWalletReferenceInput): Promise<void>;
}

function isRecord(value: unknown): value is Record<string, unknown> {
  return !!value && typeof value === "object" && !Array.isArray(value);
}

function isNullableString(value: unknown): value is string | null {
  return value === null || typeof value === "string";
}

export function isNonNegativeNano(value: unknown): value is string {
  if (typeof value !== "string" || !/^\d+$/.test(value)) return false;
  return BigInt(value) >= 0n;
}

export function isPositiveNano(value: unknown): value is string {
  return isNonNegativeNano(value) && BigInt(value) > 0n;
}

function isListingState(value: unknown): value is EscrowListingState {
  return value === "intent_only"
    || value === "active"
    || value === "reserved"
    || value === "cancelled"
    || value === "manual_review";
}

function isDealState(value: unknown): value is EscrowDealState {
  return value === "intent_created"
    || value === "awaiting_nft"
    || value === "awaiting_buyer_funds"
    || value === "funded_review"
    || value === "nft_release_pending"
    || value === "delivered_dispute_window"
    || value === "disputed"
    || value === "nft_return_pending"
    || value === "seller_payout_pending"
    || value === "buyer_refund_pending"
    || value === "settled"
    || value === "refunded"
    || value === "expired"
    || value === "manual_review";
}

function isListingAction(value: unknown): value is EscrowListingAction {
  return value === "create_deal_intent" || value === "cancel_listing_intent";
}

export function isRetryableOutboundAction(value: unknown): value is EscrowRetryableOutboundAction {
  if (!isRecord(value)) return false;
  if (
    typeof value.query_id !== "string"
    || !/^[1-9][0-9]{0,19}$/.test(value.query_id)
    || BigInt(value.query_id) >= (1n << 64n)
    || (value.slot !== "first" && value.slot !== "second")
    || !Number.isInteger(value.kind)
    || Number(value.kind) < 1
    || Number(value.kind) > 7
    || typeof value.recipient_address !== "string"
    || value.recipient_address.length === 0
    || typeof value.amount_nanotons !== "string"
    || !/^(0|[1-9][0-9]*)$/.test(value.amount_nanotons)
    || !Number.isInteger(value.retry_window_seconds)
    || !Number.isSafeInteger(value.proof_masterchain_seqno)
    || Number(value.proof_masterchain_seqno) <= 0
    || typeof value.proof_masterchain_block_hash !== "string"
    || !/^[0-9a-f]{64}$/.test(value.proof_masterchain_block_hash)
    || typeof value.proof_state_data_hash !== "string"
    || !/^[0-9a-f]{64}$/.test(value.proof_state_data_hash)
    || typeof value.proof_provider_id !== "string"
    || value.proof_provider_id.length === 0
    || value.proof_provider_id.length > 128
  ) return false;
  const kind = Number(value.kind);
  const retryWindow = Number(value.retry_window_seconds);
  const amount = BigInt(value.amount_nanotons);
  if (kind === 7) return amount === 0n && retryWindow === 0;
  return amount > 0n && (
    (kind >= 1 && kind <= 5 && retryWindow === 1800)
    || (kind === 6 && retryWindow === 0)
  );
}

function isRetryableOutboundActionList(value: unknown): value is EscrowRetryableOutboundAction[] {
  return Array.isArray(value) && value.every(isRetryableOutboundAction);
}

function isAction(value: unknown): value is EscrowAction {
  return value === "create_deal_escrow"
    || value === "activate_deal"
    || value === "deposit_nft"
    || value === "fund_deal"
    || value === "accept_deal"
    || value === "open_dispute"
    || value === "return_nft_to_escrow"
    || value === "withdraw_unsold_nft"
    || value === "retry_failed_outbound_action";
}

function isNftSnapshot(value: unknown): value is EscrowNftSnapshot {
  if (!isRecord(value)) return false;
  return (value.asset_id === null || typeof value.asset_id === "string")
    && typeof value.title === "string"
    && isNullableString(value.image_url)
    && typeof value.item_address === "string"
    && isNullableString(value.collection_address);
}

function isDispute(value: unknown): value is EscrowDispute | null {
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

export function isEscrowListingIntent(value: unknown): value is EscrowListingIntent {
  if (!isRecord(value)) return false;
  return typeof value.id === "string"
    && isNullableString(value.listing_key)
    && typeof value.seller_id === "string"
    && isListingState(value.state)
    && value.network === "testnet"
    && isNftSnapshot(value.nft)
    && typeof value.seller_wallet_address === "string"
    && isPositiveNano(value.price_nano)
    && value.fee_bps === 0
    && Array.isArray(value.available_actions)
    && value.available_actions.every(isListingAction)
    && typeof value.created_at === "string"
    && typeof value.updated_at === "string";
}

export function isEscrowDeal(value: unknown): value is EscrowDeal {
  if (!isRecord(value)) return false;
  return typeof value.id === "string"
    && typeof value.listing_id === "string"
    && typeof value.listing_key === "string"
    && typeof value.buyer_id === "string"
    && typeof value.seller_id === "string"
    && isDealState(value.state)
    && value.network === "testnet"
    && isNftSnapshot(value.nft)
    && isNullableString(value.escrow_address)
    && typeof value.seller_wallet_address === "string"
    && typeof value.buyer_wallet_address === "string"
    && isPositiveNano(value.price_nano)
    && value.fee_bps === 0
    && isNullableString(value.buyer_review_deadline)
    && isNullableString(value.dispute_deadline)
    && Array.isArray(value.available_actions)
    && value.available_actions.every(isAction)
    && typeof value.created_at === "string"
    && typeof value.updated_at === "string"
    && isDispute(value.dispute);
}

export function isEscrowWithdrawal(value: unknown): value is EscrowWithdrawal {
  if (!isRecord(value)) return false;
  return typeof value.id === "string"
    && typeof value.deal_id === "string"
    && value.kind === "unsold_nft"
    && (value.status === "prepared" || value.status === "submitted" || value.status === "observing"
      || value.status === "confirmed" || value.status === "failed" || value.status === "manual_review")
    && isNullableString(value.destination_address)
    && isNullableString(value.transaction_hash)
    && typeof value.created_at === "string"
    && typeof value.updated_at === "string";
}

export function isPreparedEscrowTransaction(value: unknown): value is PreparedEscrowTransaction {
  if (!isRecord(value) || value.network !== "testnet" || !isAction(value.action)) return false;

  // DealEscrow v1 is deployed directly at its backend-derived per-deal StateInit.
  // A Factory destination is never valid for this protocol version.
  const addressTopologyValid = value.factory_address === null
    && typeof value.escrow_address === "string"
    && value.escrow_address.length > 0;
  const messagesValid = Array.isArray(value.messages)
    && value.messages.length > 0
    && value.messages.every((message) => isRecord(message)
      && typeof message.address === "string"
      && message.address.length > 0
      && isPositiveNano(message.amount_nano)
      && isNullableString(message.payload_boc ?? null)
      && isNullableString(message.state_init_boc ?? null));
  const deploymentMessage = Array.isArray(value.messages) && value.messages.length === 1
    ? value.messages[0]
    : null;
  const directDeploymentValid = value.action !== "create_deal_escrow"
    || (isRecord(deploymentMessage)
      && deploymentMessage.address === value.escrow_address
      && typeof deploymentMessage.state_init_boc === "string"
      && deploymentMessage.state_init_boc.length > 0
      && (deploymentMessage.payload_boc === null || deploymentMessage.payload_boc === undefined));

  return addressTopologyValid
    && messagesValid
    && directDeploymentValid
    && typeof value.action_id === "string"
    && value.action_id.length > 0
    && typeof value.nft_item_address === "string"
    && value.nft_item_address.length > 0
    && (value.price_nano === null || isPositiveNano(value.price_nano))
    && value.fee_bps === 0
    && (value.execution_reserve_nano === null || isNonNegativeNano(value.execution_reserve_nano))
    && typeof value.valid_until === "string"
    && Number.isFinite(Date.parse(value.valid_until))
    && typeof value.display_purpose === "string";
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
  return readJson(
    operation.url,
    accessToken,
    validate,
    {
      method: operation.method ?? "POST",
      headers: { "Content-Type": "application/json", ...(operation.headers ?? {}) },
      ...(operation.body === undefined ? {} : { body: JSON.stringify(operation.body) }),
    },
  );
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
    listMarketplaceListings: (signal) => readPage(contract.marketplaceListings(), accessToken, isEscrowListingIntent, signal),
    listSellerListings: (signal) => readPage(contract.sellerListings(), accessToken, isEscrowListingIntent, signal),
    listBuyerDeals: (signal) => readPage(contract.buyerDeals(), accessToken, isEscrowDeal, signal),
    listSellerDeals: (signal) => readPage(contract.sellerDeals(), accessToken, isEscrowDeal, signal),
    listSellerWithdrawals: (signal) => readPage(contract.sellerWithdrawals(), accessToken, isEscrowWithdrawal, signal),
    getListing: (id, signal) => readJson(contract.listingDetails(id), accessToken, isEscrowListingIntent, { signal }),
    getDeal: (id, signal) => readJson(contract.dealDetails(id), accessToken, isEscrowDeal, { signal }),
    createListingIntent: (input) => writeJson(contract.createListingIntent(input), accessToken, isEscrowListingIntent),
    createBuyerDealIntent: (input) => writeJson(contract.createBuyerDealIntent(input), accessToken, isEscrowDeal),
    prepareDealEscrow: (input) => getPrepared(contract.prepareDealEscrow(input)),
    prepareDealActivation: (input) => getPrepared(contract.prepareDealActivation(input)),
    prepareNftDeposit: (input) => getPrepared(contract.prepareNftDeposit(input)),
    prepareBuyerFunding: (input) => getPrepared(contract.prepareBuyerFunding(input)),
    prepareBuyerAcceptance: (input) => getPrepared(contract.prepareBuyerAcceptance(input)),
    prepareDispute: (input) => getPrepared(contract.prepareDispute(input)),
    prepareBuyerNftReturn: (input) => getPrepared(contract.prepareBuyerNftReturn(input)),
    prepareUnsoldNftWithdrawal: (input) => getPrepared(contract.prepareUnsoldNftWithdrawal(input)),
    listRetryableOutboundActions: (dealId, signal) => readJson(
      contract.retryableOutboundActions(dealId),
      accessToken,
      isRetryableOutboundActionList,
      { signal },
    ),
    prepareFailedOutboundRetry: (input) => getPrepared(contract.prepareFailedOutboundRetry(input)),
    submitWalletReference: async (input) => {
      await writeJson(contract.submitWalletReference(input), accessToken, (value): value is { accepted: boolean } =>
        isRecord(value) && value.accepted === true);
    },
  };
}
