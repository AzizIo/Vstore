import { describe, expect, it } from "vitest";

import {
  ESCROW_DEAL_STATE_META,
  ESCROW_DISPUTE_LABELS,
  ESCROW_LISTING_STATE_META,
  ESCROW_WITHDRAWAL_LABELS,
  formatEscrowDate,
  isPositiveTonDecimal,
  nanoToTon,
  tonToNano,
} from "../../escrow/escrowState";
import type { EscrowDealState, EscrowListingState } from "../../api/escrow";

const listingStates: EscrowListingState[] = [
  "intent_only",
  "active",
  "reserved",
  "cancelled",
  "manual_review",
];

const dealStates: EscrowDealState[] = [
  "intent_created",
  "awaiting_nft",
  "awaiting_buyer_funds",
  "funded_review",
  "nft_release_pending",
  "delivered_dispute_window",
  "disputed",
  "nft_return_pending",
  "seller_payout_pending",
  "buyer_refund_pending",
  "settled",
  "refunded",
  "expired",
  "manual_review",
];

describe("escrow state presentation", () => {
  it("has safe guidance and labels for all canonical listing and deal states", () => {
    expect(Object.keys(ESCROW_LISTING_STATE_META).sort()).toEqual([...listingStates].sort());
    expect(Object.keys(ESCROW_DEAL_STATE_META).sort()).toEqual([...dealStates].sort());

    for (const state of listingStates) {
      expect(ESCROW_LISTING_STATE_META[state].label.trim()).not.toBe("");
      expect(ESCROW_LISTING_STATE_META[state].guidance.trim()).not.toBe("");
    }
    for (const state of dealStates) {
      expect(ESCROW_DEAL_STATE_META[state].label.trim()).not.toBe("");
      expect(ESCROW_DEAL_STATE_META[state].guidance.trim()).not.toBe("");
      expect(ESCROW_DEAL_STATE_META[state].tone).toMatch(
        /^(pending|active|success|warning|danger|neutral)$/,
      );
    }
  });

  it("labels dispute and unsold NFT withdrawal states", () => {
    expect(ESCROW_DISPUTE_LABELS.open).toBe("Открыт");
    expect(ESCROW_DISPUTE_LABELS.resolved_buyer).toContain("покупателя");
    expect(ESCROW_WITHDRAWAL_LABELS.confirmed).toBe("Подтверждён");
    expect(ESCROW_WITHDRAWAL_LABELS.manual_review).toContain("проверка");
  });

  it("converts TON decimals to integer nanotons without floating point", () => {
    expect(tonToNano("2.5")).toBe("2500000000");
    expect(tonToNano("0.000000001")).toBe("1");
    expect(tonToNano("12345678901234567890.123456789")).toBe("12345678901234567890123456789");
    expect(tonToNano("0")).toBeNull();
    expect(tonToNano("2,5")).toBeNull();
    expect(tonToNano("1.0000000001")).toBeNull();
    expect(tonToNano("-1")).toBeNull();
  });

  it("formats integer nanotons precisely for display", () => {
    expect(nanoToTon("2500000000")).toBe("2.5");
    expect(nanoToTon("1")).toBe("0.000000001");
    expect(nanoToTon("1000000000")).toBe("1");
    expect(nanoToTon("12345678901234567890123456789")).toBe("12345678901234567890.123456789");
    expect(nanoToTon(null)).toBe("Не сообщено");
    expect(nanoToTon("not-nano")).toBe("Не сообщено");
  });

  it("recognizes only positive decimal TON strings up to nine fractional digits", () => {
    expect(isPositiveTonDecimal("0.000000001")).toBe(true);
    expect(isPositiveTonDecimal("10")).toBe(true);
    expect(isPositiveTonDecimal("0")).toBe(false);
    expect(isPositiveTonDecimal("2,5")).toBe(false);
    expect(isPositiveTonDecimal("1e8")).toBe(false);
    expect(isPositiveTonDecimal(null)).toBe(false);
  });

  it("formats valid dates and fails safely for missing or malformed dates", () => {
    expect(formatEscrowDate("not-a-date")).toBe("Дата недоступна");
    expect(formatEscrowDate(null)).toBe("Срок не указан");
    expect(formatEscrowDate("2026-01-01T00:00:00.000Z")).toContain("2026");
  });
});
