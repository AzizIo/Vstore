import { buildTelegramListingShareUrl } from "./telegramShareLink";

interface Props {
  listingId: string;
  title: string;
  directLink?: string;
}

export function ListingShareButton({ listingId, title, directLink }: Props) {
  const configuredDirectLink =
    directLink ?? import.meta.env.VITE_TELEGRAM_MINI_APP_DIRECT_LINK ?? "";
  const shareUrl = buildTelegramListingShareUrl(configuredDirectLink, listingId, title);

  if (!shareUrl) return null;
  const safeShareUrl = shareUrl;

  function handleShare() {
    const openTelegramLink = window.Telegram?.WebApp?.openTelegramLink;
    if (typeof openTelegramLink === "function") {
      openTelegramLink(safeShareUrl);
      return;
    }
    window.open(safeShareUrl, "_blank", "noopener,noreferrer");
  }

  return (
    <button
      className="seller-contact-link listing-share-button"
      type="button"
      onClick={handleShare}
      aria-label="Поделиться объявлением в Telegram"
    >
      Поделиться в Telegram <span aria-hidden="true">↗</span>
    </button>
  );
}
