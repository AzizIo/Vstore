import { describe, expect, it } from "vitest";

import {
  ESCROW_DISPUTE_LABELS,
  ESCROW_STATE_META,
  ESCROW_WITHDRAWAL_LABELS,
  formatEscrowDate,
  formatTonAmount,
  isPositiveTonAmount,
} from "../../escrow/escrowState";
import type { EscrowState } from "../../api/escrow";

const states: EscrowState[] = [
  "awaiting_nft_deposit",
  "listed",
  "payment_received",
  "delivery_pending",
  "buyer_confirmation_window",
  "disputed",
  "refund_pending_nft_return",
  "settled",
  "refunded",
  "seller_withdrawn",
  "refundable_failure",
];

describe("escrow state presentation", () => {
  it("has a label and guidance for every backend escrow state", () => {
    expect(Object.keys(ESCROW_STATE_META).sort()).toEqual([...states].sort());

    for (const state of states) {
      expect(ESCROW_STATE_META[state].label.trim()).not.toBe("");
      expect(ESCROW_STATE_META[state].guidance.trim()).not.toBe("");
      expect(ESCROW_STATE_META[state].tone).toMatch(
        /^(pending|active|success|warning|danger|neutral)$/,
      );
    }
  });

  it("labels dispute and withdrawal lifecycle states", () => {
    expect(ESCROW_DISPUTE_LABELS.open).toBe("Открыт");
    expect(ESCROW_DISPUTE_LABELS.resolved_buyer).toContain("покупателя");
    expect(ESCROW_WITHDRAWAL_LABELS.confirmed).toBe("Подтверждён");
    expect(ESCROW_WITHDRAWAL_LABELS.manual_review).toContain("проверка");
  });

  it("formats decimal TON strings without floating point rounding", () => {
    expect(formatTonAmount("0.000000001")).toBe("0.000000001");
    expect(formatTonAmount("12.500000000")).toBe("12.5");
    expect(formatTonAmount("900719925474099312345.100000")).toBe("900719925474099312345.1");
    expect(formatTonAmount("0")).toBe("0");
    expect(formatTonAmount(null)).toBe("Не сообщено");
    expect(formatTonAmount("unknown")).toBe("unknown");
  });

  it("recognizes positive TON amounts without Number coercion", () => {
    expect(isPositiveTonAmount("0.000000001")).toBe(true);
    expect(isPositiveTonAmount("10")).toBe(true);
    expect(isPositiveTonAmount("0.0000")).toBe(false);
    expect(isPositiveTonAmount("0")).toBe(false);
    expect(isPositiveTonAmount("1e8")).toBe(false);
    expect(isPositiveTonAmount(null)).toBe(false);
  });

  it("formats valid dates and fails safely for missing or malformed dates", () => {
    expect(formatEscrowDate("not-a-date")).toBe("Дата недоступна");
    expect(formatEscrowDate(null)).toBe("Срок не указан");
    expect(formatEscrowDate("2026-01-01T00:00:00.000Z")).toContain("2026");
  });
});
