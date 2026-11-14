import { fireEvent, render, screen } from "@testing-library/react";
import { afterEach, describe, expect, it, vi } from "vitest";

import { ListingShareButton } from "../components/ListingShareButton";
import { buildTelegramListingShareUrl } from "../components/telegramShareLink";

const LISTING_ID = "123e4567-e89b-12d3-a456-426614174000";
const DIRECT_LINK = "https://t.me/viltara_shop_bot/shop";

describe("buildTelegramListingShareUrl", () => {
  it("creates a Telegram share URL with a listing deep link", () => {
    const result = buildTelegramListingShareUrl(DIRECT_LINK, LISTING_ID, "Moon Lantern");
    expect(result).not.toBeNull();

    const shareUrl = new URL(result!);
    expect(shareUrl.origin + shareUrl.pathname).toBe("https://t.me/share/url");
    const target = new URL(shareUrl.searchParams.get("url")!);
    expect(target.toString()).toBe(
      "https://t.me/viltara_shop_bot/shop?startapp=listing_123e4567e89b12d3a456426614174000",
    );
    expect(shareUrl.searchParams.get("text")).toBe(
      "Объявление «Moon Lantern» в VILTARA SHOP",
    );
  });

  it.each([
    "",
    "http://t.me/viltara_shop_bot/shop",
    "https://evil.example/viltara_shop_bot/shop",
    "https://t.me/viltara_shop_bot",
    "https://t.me/viltara_shop_bot/shop/extra",
    "https://user:password@t.me/viltara_shop_bot/shop",
  ])("rejects an unsafe or incomplete direct link: %s", (directLink) => {
    expect(buildTelegramListingShareUrl(directLink, LISTING_ID, "Moon Lantern")).toBeNull();
  });

  it("rejects a malformed listing id", () => {
    expect(buildTelegramListingShareUrl(DIRECT_LINK, "not-a-uuid", "Moon Lantern")).toBeNull();
  });
});

describe("ListingShareButton", () => {
  afterEach(() => {
    delete window.Telegram;
    vi.restoreAllMocks();
  });

  it("opens the Telegram share picker outside the Mini App", () => {
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ListingShareButton listingId={LISTING_ID} title="Moon Lantern" directLink={DIRECT_LINK} />);

    fireEvent.click(screen.getByRole("button", { name: "Поделиться объявлением в Telegram" }));

    expect(open).toHaveBeenCalledWith(
      expect.stringContaining("https://t.me/share/url?"),
      "_blank",
      "noopener,noreferrer",
    );
  });

  it("uses Telegram WebApp openTelegramLink inside the Mini App", () => {
    const openTelegramLink = vi.fn();
    window.Telegram = { WebApp: { openTelegramLink } };
    const open = vi.spyOn(window, "open").mockReturnValue(null);
    render(<ListingShareButton listingId={LISTING_ID} title="Moon Lantern" directLink={DIRECT_LINK} />);

    fireEvent.click(screen.getByRole("button", { name: "Поделиться объявлением в Telegram" }));

    expect(openTelegramLink).toHaveBeenCalledWith(expect.stringContaining("https://t.me/share/url?"));
    expect(open).not.toHaveBeenCalled();
  });

  it("stays hidden without a valid configured Mini App direct link", () => {
    render(<ListingShareButton listingId={LISTING_ID} title="Moon Lantern" directLink="" />);
    expect(screen.queryByRole("button", { name: "Поделиться объявлением в Telegram" })).not.toBeInTheDocument();
  });
});
