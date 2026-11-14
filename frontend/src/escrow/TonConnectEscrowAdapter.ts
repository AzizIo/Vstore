import { Address } from "@ton/core";

import {
  isPreparedEscrowTransaction,
  type PreparedEscrowTransaction,
} from "../api/escrow";

export const TON_TESTNET_CHAIN_ID = "-3";

export interface EscrowConnectedWallet {
  address: string;
  chain: string;
}

export interface EscrowTonConnectMessage {
  address: string;
  amount: string;
  payload?: string;
  stateInit?: string;
}

export interface EscrowTonConnectRequest {
  validUntil: number;
  network: typeof TON_TESTNET_CHAIN_ID;
  messages: EscrowTonConnectMessage[];
}

export type EscrowTonConnectSender = (
  request: EscrowTonConnectRequest,
) => Promise<{ boc: string }>;

export interface EscrowWalletAdapter {
  readonly connectedWallet: EscrowConnectedWallet | null;
  readonly signingEnabled: boolean;
  sendPreparedTransaction(
    transaction: PreparedEscrowTransaction,
    expectedVerifiedWalletAddress: string,
  ): Promise<{ boc: string }>;
}

function normalizedAddress(value: string): string {
  try {
    return Address.parse(value).toRawString().toLowerCase();
  } catch {
    throw new Error("Адрес TON в подготовленной операции некорректен.");
  }
}

function allowedDestination(transaction: PreparedEscrowTransaction): string {
  switch (transaction.action) {
    case "create_deal_escrow":
      if (!transaction.factory_address) {
        throw new Error("Для создания DealEscrow Backend не вернул адрес Factory.");
      }
      return transaction.factory_address;
    case "deposit_nft":
    case "return_nft_to_escrow":
      return transaction.nft_item_address;
    case "fund_deal":
    case "accept_deal":
    case "open_dispute":
    case "withdraw_unsold_nft":
      if (!transaction.escrow_address) {
        throw new Error("Для этой операции Backend не вернул адрес DealEscrow.");
      }
      return transaction.escrow_address;
  }
}

export function createTonConnectEscrowAdapter(options: {
  connectedWallet: EscrowConnectedWallet | null;
  sendTransaction?: EscrowTonConnectSender;
  enabled?: boolean;
  now?: () => number;
}): EscrowWalletAdapter {
  const enabled = options.enabled === true && typeof options.sendTransaction === "function";
  const now = options.now ?? Date.now;

  return {
    connectedWallet: options.connectedWallet,
    signingEnabled: enabled,
    async sendPreparedTransaction(transaction, expectedVerifiedWalletAddress) {
      if (!enabled || !options.sendTransaction) {
        throw new Error("Подписание escrow-транзакций отключено до согласования ABI и Backend API.");
      }
      if (!options.connectedWallet) {
        throw new Error("Подключите подтверждённый testnet-кошелёк.");
      }
      if (options.connectedWallet.chain !== TON_TESTNET_CHAIN_ID) {
        throw new Error("Escrow доступен только в TON testnet. Переключите сеть кошелька.");
      }
      if (!isPreparedEscrowTransaction(transaction)) {
        throw new Error("Сервер вернул неподтверждённый формат escrow-транзакции.");
      }
      if (transaction.network !== "testnet") {
        throw new Error("Escrow не поддерживает основную сеть TON.");
      }
      if (
        normalizedAddress(options.connectedWallet.address) !==
        normalizedAddress(expectedVerifiedWalletAddress)
      ) {
        throw new Error("Подключённый кошелёк не совпадает с подтверждённым кошельком участника.");
      }

      const expectedDestination = normalizedAddress(allowedDestination(transaction));
      normalizedAddress(transaction.nft_item_address);
      if (transaction.action === "create_deal_escrow") {
        normalizedAddress(transaction.factory_address!);
      } else {
        normalizedAddress(transaction.escrow_address!);
      }

      const validUntil = Math.floor(Date.parse(transaction.valid_until) / 1000);
      if (!Number.isFinite(validUntil) || validUntil <= Math.floor(now() / 1000)) {
        throw new Error("Срок подготовки escrow-транзакции истёк. Обновите данные перед подписанием.");
      }

      const messages = transaction.messages.map((message) => {
        if (normalizedAddress(message.address) !== expectedDestination) {
          throw new Error("Получатель TON-сообщения не соответствует разрешённому адресу для этого действия.");
        }
        return {
          address: message.address,
          amount: message.amount_nano,
          ...(message.payload_boc ? { payload: message.payload_boc } : {}),
          ...(message.state_init_boc ? { stateInit: message.state_init_boc } : {}),
        };
      });

      // Payloads and values are forwarded exactly as prepared by the reviewed Backend.
      // The adapter never invents opcodes, message bodies or amounts.
      return options.sendTransaction({
        validUntil,
        network: TON_TESTNET_CHAIN_ID,
        messages,
      });
    },
  };
}

export async function walletBocReference(boc: string): Promise<string> {
  if (!boc.trim()) throw new Error("TON Connect не вернул подписанное сообщение.");
  let binary: string;
  try {
    binary = atob(boc);
  } catch {
    throw new Error("TON Connect вернул некорректный BOC.");
  }
  const bytes = Uint8Array.from(binary, (character) => character.charCodeAt(0));
  const digest = await crypto.subtle.digest("SHA-256", bytes);
  return Array.from(new Uint8Array(digest), (byte) => byte.toString(16).padStart(2, "0")).join("");
}
