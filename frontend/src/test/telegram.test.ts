import { beforeEach, describe, expect, it } from "vitest";

import {
  getTelegramStartOrderId,
  getTelegramStartParam,
} from "../auth/telegram";

describe("Telegram start parameters", () => {
  beforeEach(() => {
    Reflect.deleteProperty(window, "Telegram");
  });

  function setStartParam(startParam: string) {
    window.Telegram = {
      WebApp: {
        initDataUnsafe: { start_param: startParam },
      },
    };
  }

  it("parses a valid order start parameter and normalizes its UUID", () => {
    setStartParam("order_123e4567e89b12d3a456426614174000");

    expect(getTelegramStartParam()).toEqual({
      type: "order",
      id: "123e4567-e89b-12d3-a456-426614174000",
    });
    expect(getTelegramStartOrderId()).toBe("123e4567-e89b-12d3-a456-426614174000");
  });

  it("parses a valid listing start parameter and normalizes its UUID", () => {
    setStartParam("listing_123e4567e89b12d3a456426614174000");

    expect(getTelegramStartParam()).toEqual({
      type: "listing",
      id: "123e4567-e89b-12d3-a456-426614174000",
    });
    expect(getTelegramStartOrderId()).toBeNull();
  });

  it("accepts uppercase hexadecimal characters and normalizes them to lowercase", () => {
    setStartParam("LISTING_ABCDEF0123456789ABCDEF0123456789");

    expect(getTelegramStartParam()).toEqual({
      type: "listing",
      id: "abcdef01-2345-6789-abcd-ef0123456789",
    });
  });

  it("returns null when start_param is absent", () => {
    window.Telegram = { WebApp: { initDataUnsafe: {} } };

    expect(getTelegramStartParam()).toBeNull();
  });

  it.each([
    "order_123e4567e89b12d3a45642661417400",
    "listing_123e4567e89b12d3a4564266141740000",
  ])("ignores an ID with an invalid length: %s", (startParam) => {
    setStartParam(startParam);

    expect(getTelegramStartParam()).toBeNull();
  });

  it("ignores IDs containing non-hexadecimal characters", () => {
    setStartParam("listing_123e4567e89b12d3a45642661417400g");

    expect(getTelegramStartParam()).toBeNull();
  });

  it("ignores unknown start-parameter prefixes", () => {
    setStartParam("product_123e4567e89b12d3a456426614174000");

    expect(getTelegramStartParam()).toBeNull();
  });
});
