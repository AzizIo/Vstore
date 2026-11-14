import type { EscrowDisputeStatus, EscrowState, EscrowWithdrawalStatus } from "../api/escrow";

export interface EscrowStateMeta {
  label: string;
  guidance: string;
  tone: "pending" | "active" | "success" | "warning" | "danger" | "neutral";
}

export const ESCROW_STATE_META: Record<EscrowState, EscrowStateMeta> = {
  awaiting_nft_deposit: {
    label: "Ожидает депозита NFT",
    guidance: "Продавец ещё не передал NFT в escrow. Лот нельзя купить до подтверждения депозита.",
    tone: "pending",
  },
  listed: {
    label: "Доступен для покупки",
    guidance: "Backend observer подтвердил депозит NFT в контракте. Лот доступен покупателям.",
    tone: "active",
  },
  payment_received: {
    label: "Оплата получена",
    guidance: "Контракт принял TON покупателя. Средства остаются заблокированными до завершения условий сделки.",
    tone: "pending",
  },
  delivery_pending: {
    label: "Передача NFT",
    guidance: "Контракт инициировал передачу NFT. Ожидается независимое подтверждение observer.",
    tone: "pending",
  },
  buyer_confirmation_window: {
    label: "Проверка покупателем",
    guidance: "Покупатель может подтвердить получение или открыть спор в пределах срока, установленного контрактом.",
    tone: "warning",
  },
  disputed: {
    label: "Открыт спор",
    guidance: "Выплата продавцу заморожена до разрешения спора по правилам контракта.",
    tone: "danger",
  },
  refund_pending_nft_return: {
    label: "Ожидается возврат NFT",
    guidance: "Возврат TON возможен только после подтверждения, что NFT находится в escrow или вернулся в него.",
    tone: "warning",
  },
  settled: {
    label: "Сделка завершена",
    guidance: "Условия расчёта выполнены. Доступность выплаты определяется подтверждёнными данными backend.",
    tone: "success",
  },
  refunded: {
    label: "Средства возвращены",
    guidance: "Backend подтвердил завершённый возврат покупателю.",
    tone: "neutral",
  },
  seller_withdrawn: {
    label: "NFT выведен продавцом",
    guidance: "Непроданный NFT возвращён продавцу и подтверждён observer.",
    tone: "neutral",
  },
  refundable_failure: {
    label: "Ошибка с возвратом",
    guidance: "Контракт зафиксировал отказ, допускающий возврат. Дождитесь подтверждения возврата в блокчейне.",
    tone: "danger",
  },
};

export const ESCROW_DISPUTE_LABELS: Record<EscrowDisputeStatus, string> = {
  open: "Открыт",
  under_review: "На рассмотрении",
  resolved_buyer: "Решён в пользу покупателя",
  resolved_seller: "Решён в пользу продавца",
};

export const ESCROW_WITHDRAWAL_LABELS: Record<EscrowWithdrawalStatus, string> = {
  prepared: "Подготовлен",
  submitted: "Отправлен в кошелёк",
  observing: "Проверяется observer",
  confirmed: "Подтверждён",
  failed: "Не выполнен",
  manual_review: "Требуется проверка",
};

export function formatTonAmount(value: string | null | undefined): string {
  if (value === null || value === undefined || value.trim() === "") return "Не сообщено";
  const normalized = value.trim();
  if (!/^\d+(?:\.\d+)?$/.test(normalized)) return normalized;
  const [whole, fraction = ""] = normalized.split(".");
  const compactFraction = fraction.replace(/0+$/, "");
  return compactFraction ? `${whole}.${compactFraction}` : whole;
}

export function isPositiveTonAmount(value: string | null | undefined): boolean {
  if (!value) return false;
  const normalized = value.trim();
  if (!/^\d+(?:\.\d+)?$/.test(normalized)) return false;
  const [whole, fraction = ""] = normalized.split(".");
  return BigInt(whole) > 0n || /[1-9]/.test(fraction);
}

export function formatEscrowDate(value: string | null | undefined): string {
  if (!value) return "Срок не указан";
  const date = new Date(value);
  if (!Number.isFinite(date.getTime())) return "Дата недоступна";
  return new Intl.DateTimeFormat("ru-RU", {
    dateStyle: "medium",
    timeStyle: "short",
  }).format(date);
}
