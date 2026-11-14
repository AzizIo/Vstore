const LISTING_ID_PATTERN =
  /^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$/i;
const TELEGRAM_USERNAME_PATTERN = /^[A-Za-z0-9_]{5,32}$/;
const MINI_APP_SHORT_NAME_PATTERN = /^[A-Za-z0-9_-]{1,64}$/;

/**
 * Builds Telegram's share picker URL only from the configured Mini App direct
 * link. The listing ID is a navigation hint, never an authentication token.
 */
export function buildTelegramListingShareUrl(
  configuredDirectLink: string,
  listingId: string,
  title: string,
): string | null {
  if (!LISTING_ID_PATTERN.test(listingId)) return null;

  let directLink: URL;
  try {
    directLink = new URL(configuredDirectLink);
  } catch {
    return null;
  }

  const pathSegments = directLink.pathname.split("/").filter(Boolean);
  if (
    directLink.protocol !== "https:" ||
    directLink.hostname !== "t.me" ||
    directLink.port !== "" ||
    directLink.username !== "" ||
    directLink.password !== "" ||
    directLink.hash !== "" ||
    pathSegments.length !== 2 ||
    !TELEGRAM_USERNAME_PATTERN.test(pathSegments[0]) ||
    !MINI_APP_SHORT_NAME_PATTERN.test(pathSegments[1])
  ) {
    return null;
  }

  const normalizedId = listingId.replace(/-/g, "").toLowerCase();
  directLink.searchParams.set("startapp", `listing_${normalizedId}`);

  const shareUrl = new URL("https://t.me/share/url");
  shareUrl.searchParams.set("url", directLink.toString());
  shareUrl.searchParams.set(
    "text",
    `Объявление «${title.trim().slice(0, 120)}» в VILTARA SHOP`,
  );
  return shareUrl.toString();
}
