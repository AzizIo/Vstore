import type {
  EscrowDealState,
  EscrowDisputeStatus,
  EscrowListingState,
  EscrowWithdrawalStatus,
} from "../api/escrow";

export interface EscrowStateMeta {
  label: string;
  guidance: string;
  tone: "pending" | "active" | "success" | "warning" | "danger" | "neutral";
}

export const ESCROW_LISTING_STATE_META: Record<EscrowListingState, EscrowStateMeta> = {
  intent_only: {
    label: "Предложение продавца",
    guidance: "Это off-chain listing intent. NFT ещё не подтверждён в escrow; после создания сделки продавец подготовит отдельный DealEscrow и внесёт NFT.",
    tone: "pending",
  },
  active: {
    label: "Доступен для сделки",
    guidance: "Backend подтвердил состояние listing intent и разрешает создание новой сделки.",
    tone: "active",
  },
  reserved: {
    label: "Сделка уже создаётся",
    guidance: "Лот привязан к сделке покупателя и не должен предлагаться второму покупателю.",
    tone: "warning",
  },
  cancelled: {
    label: "Лот отменён",
    guidance: "Listing intent закрыт. Статус возврата NFT отображается отдельно в истории сделки.",
    tone: "neutral",
  },
  manual_review: {
    label: "Ручная проверка",
    guidance: "Действия временно недоступны до сверки цепочки доказательств.",
    tone: "danger",
  },
};

export const ESCROW_DEAL_STATE_META: Record<EscrowDealState, EscrowStateMeta> = {
  intent_created: {
    label: "Сделка подготовлена",
    guidance: "Buyer wallet привязан. Продавец должен создать отдельный DealEscrow.",
    tone: "pending",
  },
  awaiting_nft: {
    label: "Ожидается депозит NFT",
    guidance: "Контракт сделки создан. Продавец должен внести именно этот NFT.",
    tone: "pending",
  },
  awaiting_buyer_funds: {
    label: "Ожидается TON покупателя",
    guidance: "Контракт подтвердил блокировку NFT. Покупатель может внести точную сумму TON и execution reserve.",
    tone: "active",
  },
  funded_review: {
    label: "Проверка покупателем",
    guidance: "NFT и TON заблокированы в escrow. Покупатель может принять сделку или открыть спор до указанного срока.",
    tone: "warning",
  },
  nft_release_pending: {
    label: "Передача NFT",
    guidance: "Escrow запросил передачу NFT. Сообщение отправлено, но финальность доставки ещё не подтверждена.",
    tone: "pending",
  },
  delivered_dispute_window: {
    label: "Окно оспаривания",
    guidance: "Oracle подтвердил доставку NFT на финальности. Покупатель ещё может открыть спор до deadline.",
    tone: "warning",
  },
  disputed: {
    label: "Открыт спор",
    guidance: "Settlement заморожен. Ожидайте ограниченного решения resolver и, если требуется, возврата NFT в escrow.",
    tone: "danger",
  },
  nft_return_pending: {
    label: "Возврат NFT",
    guidance: "NFT возвращается или повторно передаётся. Возврат TON пока не считается завершённым.",
    tone: "warning",
  },
  seller_payout_pending: {
    label: "Выплата продавцу",
    guidance: "Контракт инициировал выплату. Ожидается финальное подтверждение; кнопки ручного вывода нет.",
    tone: "pending",
  },
  buyer_refund_pending: {
    label: "Возврат покупателю",
    guidance: "Контракт инициировал refund. Ожидается финальное подтверждение транзакции.",
    tone: "pending",
  },
  settled: {
    label: "Сделка завершена",
    guidance: "Выплата продавцу подтверждена на финальности. Сделка доступна только для просмотра.",
    tone: "success",
  },
  refunded: {
    label: "Средства возвращены",
    guidance: "Refund подтверждён на финальности, условия возврата NFT также выполнены.",
    tone: "neutral",
  },
  expired: {
    label: "Сделка истекла",
    guidance: "Сделка завершилась до принятия buyer funds. Backend должен подтвердить, что NFT не остаётся в escrow.",
    tone: "neutral",
  },
  manual_review: {
    label: "Ручная проверка",
    guidance: "Доказательства конфликтуют или неполны. Автоматические release/refund действия приостановлены.",
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

export function tonToNano(value: string): string | null {
  const normalized = value.trim();
  if (!/^\d+(?:\.\d{1,9})?$/.test(normalized)) return null;
  const [whole, fraction = ""] = normalized.split(".");
  const nano = BigInt(whole) * 1_000_000_000n
    + BigInt((fraction + "000000000").slice(0, 9));
  return nano > 0n ? nano.toString() : null;
}

export function nanoToTon(value: string | null | undefined): string {
  if (value === null || value === undefined || !/^\d+$/.test(value)) return "Не сообщено";
  const nano = BigInt(value);
  const whole = nano / 1_000_000_000n;
  const fraction = (nano % 1_000_000_000n).toString().padStart(9, "0").replace(/0+$/, "");
  return fraction ? `${whole}.${fraction}` : whole.toString();
}

export function isPositiveTonDecimal(value: string | null | undefined): boolean {
  return value !== null && value !== undefined && tonToNano(value) !== null;
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
