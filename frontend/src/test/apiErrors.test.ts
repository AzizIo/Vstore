import { describe, expect, it } from "vitest";
import { getApiErrorMessage } from "../api/errors";

describe("API error message localization", () => {
  it("returns a localized string detail", () => {
    expect(getApiErrorMessage({ detail: "Действие недоступно." }, "fallback"))
      .toBe("Действие недоступно.");
  });

  it("renders FastAPI validation detail messages instead of a generic HTTP error", () => {
    expect(getApiErrorMessage({
      detail: [
        { loc: ["body", "price_amount"], msg: "Введите корректную цену.", type: "value_error" },
        { loc: ["body", "expires_at"], msg: "Укажите часовой пояс.", type: "value_error" },
      ],
    }, "Запрос завершился ошибкой (422)."))
      .toBe("Введите корректную цену. Укажите часовой пояс.");
  });

  it("ignores malformed validation entries and deduplicates repeated messages", () => {
    expect(getApiErrorMessage({
      detail: [
        null,
        { loc: ["body", "name"], msg: "Укажите название." },
        { loc: ["body", "name"], msg: "Укажите название." },
        { loc: ["body", "description"] },
      ],
    }, "fallback")).toBe("Укажите название.");
  });

  it("uses the HTTP fallback when the response has no usable detail", () => {
    expect(getApiErrorMessage({ detail: [{ type: "missing" }] }, "Ошибка (422)."))
      .toBe("Ошибка (422).");
    expect(getApiErrorMessage({ message: "internal" }, "Ошибка (503)."))
      .toBe("Ошибка (503).");
  });
});
