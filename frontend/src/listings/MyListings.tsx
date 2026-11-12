import { useEffect, useMemo, useState } from "react";

import {
  cancelListing,
  fetchMyListings,
  publishListing,
  updateListing,
  type Listing,
} from "../api/listings";
import { useSession } from "../auth/SessionProvider";
import { CreateListing } from "./CreateListing";

const listingStatuses = ["draft", "active", "reserved", "sold", "cancelled", "expired"] as const;
type KnownStatus = (typeof listingStatuses)[number];
type StatusFilter = "all" | KnownStatus | "other";

const statusLabels: Record<KnownStatus, string> = {
  draft: "Draft",
  active: "Active",
  reserved: "Reserved",
  sold: "Sold",
  cancelled: "Cancelled",
  expired: "Expired",
};

function isKnownStatus(status: string): status is KnownStatus {
  return listingStatuses.some((knownStatus) => knownStatus === status);
}

function getTitle(listing: Listing) {
  return listing.title || listing.asset.name || "Untitled asset";
}

function getCreatedDate(value: string) {
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, { dateStyle: "medium" }).format(date);
}

function toLocalDateTimeInput(value: string | null | undefined) {
  if (!value) return "";
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return "";
  return new Date(date.getTime() - date.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

function localDateTimeMinimum() {
  const now = new Date();
  return new Date(now.getTime() - now.getTimezoneOffset() * 60_000)
    .toISOString()
    .slice(0, 16);
}

function getExpirationLabel(value: string | null | undefined) {
  if (!value) return "No expiry";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "Date unavailable"
    : new Intl.DateTimeFormat(undefined, {
        dateStyle: "medium",
        timeStyle: "short",
      }).format(date);
}

function ListingImage({ listing }: { listing: Listing }) {
  const [failed, setFailed] = useState(false);
  const title = getTitle(listing);
  useEffect(() => setFailed(false), [listing.asset.image_url]);

  return (
    <div className="my-listing-image">
      {listing.asset.image_url && !failed ? (
        <img src={listing.asset.image_url} alt={title} loading="lazy" onError={() => setFailed(true)} />
      ) : (
        <span aria-label="Image unavailable">V</span>
      )}
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const known = isKnownStatus(status);
  return (
    <span className={`listing-status ${known ? `listing-status-${status}` : "listing-status-unknown"}`}>
      {known ? statusLabels[status] : "Unknown status"}
    </span>
  );
}

function MyListingDetail({
  listing,
  accessToken,
  onBack,
  onUpdated,
}: {
  listing: Listing;
  accessToken: string;
  onBack: () => void;
  onUpdated: (listing: Listing) => void;
}) {
  const [priceAmount, setPriceAmount] = useState(listing.price_amount);
  const [title, setTitle] = useState(listing.title ?? "");
  const [description, setDescription] = useState(listing.description ?? "");
  const [expiresAt, setExpiresAt] = useState(toLocalDateTimeInput(listing.expires_at));
  const [initialExpiresAt, setInitialExpiresAt] = useState(toLocalDateTimeInput(listing.expires_at));
  const [working, setWorking] = useState<"saving" | "publishing" | "cancelling" | "">("");
  const [error, setError] = useState("");
  const [success, setSuccess] = useState("");
  const [confirmCancel, setConfirmCancel] = useState(false);
  const [confirmPublish, setConfirmPublish] = useState(false);
  const isEditable = listing.status === "draft" || listing.status === "active";
  const canPublish =
    listing.status === "draft" &&
    listing.asset.asset_type === "ton_nft" &&
    listing.asset.verification_status === "verified" &&
    Boolean(listing.asset.item_address);

  async function saveChanges(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!isEditable || working) return;
    setWorking("saving");
    setError("");
    setSuccess("");
    try {
      const payload = {
        price_amount: priceAmount,
        title: title.trim() || null,
        description: description.trim() || null,
        ...(expiresAt !== initialExpiresAt
          ? { expires_at: expiresAt ? new Date(expiresAt).toISOString() : null }
          : {}),
      };
      const updated = await updateListing(listing.id, accessToken, payload);
      const updatedExpiration = toLocalDateTimeInput(updated.expires_at);
      setExpiresAt(updatedExpiration);
      setInitialExpiresAt(updatedExpiration);
      onUpdated(updated);
      setSuccess("Listing details saved.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to save listing details.");
    } finally {
      setWorking("");
    }
  }

  async function publish() {
    if (!canPublish || working) return;
    setWorking("publishing");
    setError("");
    setSuccess("");
    try {
      const updated = await publishListing(listing.id, accessToken);
      onUpdated(updated);
      setConfirmPublish(false);
      setSuccess("Listing published and is now visible in the marketplace.");
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to publish this listing.");
    } finally {
      setWorking("");
    }
  }

  async function confirmAndCancel() {
    if (!isEditable || working) return;
    setWorking("cancelling");
    setError("");
    setSuccess("");
    try {
      const updated = await cancelListing(listing.id, accessToken);
      onUpdated(updated);
      setConfirmCancel(false);
      setSuccess(
        listing.status === "active"
          ? "Listing unpublished. It is no longer visible in the marketplace."
          : "Draft cancelled.",
      );
    } catch (reason) {
      setError(reason instanceof Error ? reason.message : "Unable to cancel this listing.");
    } finally {
      setWorking("");
    }
  }

  return (
    <section className="my-listing-detail" aria-labelledby="my-listing-detail-title">
      <button className="text-button back-button" type="button" onClick={onBack}>
        <span aria-hidden="true">←</span> Back to my listings
      </button>
      <div className="my-listing-detail-layout">
        <ListingImage listing={listing} />
        <div className="my-listing-detail-copy">
          <StatusBadge status={listing.status} />
          <p className="eyebrow">{listing.asset.asset_type === "ton_nft" ? "TON NFT" : "Telegram gift"}</p>
          <h1 id="my-listing-detail-title">{getTitle(listing)}</h1>
          <p className="detail-price">
            {listing.price_amount} {listing.price_currency}
          </p>
          {listing.description && <p className="detail-description">{listing.description}</p>}
          {listing.asset.description && <p className="detail-description">{listing.asset.description}</p>}
          <dl className="detail-facts">
            <div><dt>Created</dt><dd>{getCreatedDate(listing.created_at)}</dd></div>
            <div><dt>Expires</dt><dd>{getExpirationLabel(listing.expires_at)}</dd></div>
            <div><dt>Asset ID</dt><dd>{listing.asset.external_id}</dd></div>
            <div><dt>Verification</dt><dd>{listing.asset.verification_status}</dd></div>
          </dl>
        </div>
      </div>

      {isEditable ? (
        <div className="listing-management">
          <h2>Manage listing</h2>
          <form className="listing-edit-form" onSubmit={saveChanges}>
            <label>
              <span>Price ({listing.price_currency})</span>
              <input
                aria-label="Listing price"
                type="number"
                min="0.000000001"
                step="0.000000001"
                required
                value={priceAmount}
                onChange={(event) => setPriceAmount(event.target.value)}
              />
            </label>
            <label>
              <span>Title <small>Optional</small></span>
              <input
                aria-label="Listing title"
                maxLength={200}
                value={title}
                onChange={(event) => setTitle(event.target.value)}
              />
            </label>
            <label>
              <span>Description <small>Optional</small></span>
              <textarea
                aria-label="Listing description"
                maxLength={4000}
                rows={4}
                value={description}
                onChange={(event) => setDescription(event.target.value)}
              />
            </label>
            <label>
              <span>Expiration <small>Optional</small></span>
              <input
                aria-label="Listing expiration"
                type="datetime-local"
                min={localDateTimeMinimum()}
                value={expiresAt}
                onChange={(event) => setExpiresAt(event.target.value)}
              />
              <small>Clear the field to remove automatic expiry.</small>
            </label>
            <div className="listing-management-actions">
              <button className="load-more-button" type="submit" disabled={Boolean(working)}>
                {working === "saving" ? "Saving..." : "Save changes"}
              </button>
              {canPublish && (
                <button
                  className="primary-button"
                  type="button"
                  disabled={Boolean(working)}
                  onClick={() => {
                    setError("");
                    setSuccess("");
                    setConfirmPublish(true);
                  }}
                >
                  Publish listing
                </button>
              )}
              <button
                className="text-button listing-cancel-action"
                type="button"
                disabled={Boolean(working)}
                onClick={() => {
                  setError("");
                  setSuccess("");
                  setConfirmCancel(true);
                }}
              >
                {listing.status === "active" ? "Unpublish listing" : "Cancel draft"}
              </button>
            </div>
          </form>
          {confirmPublish && (
            <div className="listing-confirmation" role="group" aria-label="Confirm listing publication">
              <p>
                Publish this NFT? The server will re-check its current on-chain owner before making it public.
              </p>
              <button
                className="primary-button"
                type="button"
                disabled={Boolean(working)}
                onClick={() => void publish()}
              >
                {working === "publishing" ? "Verifying NFT ownership..." : "Confirm publish"}
              </button>
              <button
                className="text-button"
                type="button"
                disabled={Boolean(working)}
                onClick={() => setConfirmPublish(false)}
              >
                Not now
              </button>
            </div>
          )}
          {listing.status === "draft" && !canPublish && (
            <p className="listing-management-note" role="status">
              This draft cannot be published because its TON NFT record is not currently eligible for publication.
            </p>
          )}
          {confirmCancel && (
            <div className="listing-confirmation" role="group" aria-label="Confirm listing cancellation">
              <p>
                {listing.status === "active"
                  ? "Unpublish this listing? Buyers will no longer see it in the marketplace."
                  : "Cancel this private draft? This action cannot be undone."}
              </p>
              <button
                className="primary-button"
                type="button"
                disabled={Boolean(working)}
                onClick={() => void confirmAndCancel()}
              >
                {working === "cancelling" ? "Cancelling..." : "Confirm"}
              </button>
              <button
                className="text-button"
                type="button"
                disabled={Boolean(working)}
                onClick={() => setConfirmCancel(false)}
              >
                Keep listing
              </button>
            </div>
          )}
        </div>
      ) : (
        <p className="listing-management-note" role="status">
          {listing.status === "reserved"
            ? "This listing is reserved by a pending order. Editing and unpublishing are disabled until the reservation ends."
            : "This listing is closed and can no longer be edited or published."}
        </p>
      )}
      {error && <p className="listing-management-error" role="alert">{error}</p>}
      {success && <p className="listing-management-success" role="status">{success}</p>}
    </section>
  );
}

function AuthenticatedMyListings({ accessToken }: { accessToken: string }) {
  const [listings, setListings] = useState<Listing[]>([]);
  const [selectedListing, setSelectedListing] = useState<Listing | null>(null);
  const [statusFilter, setStatusFilter] = useState<StatusFilter>("all");
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [creating, setCreating] = useState(false);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    fetchMyListings(accessToken, controller.signal)
      .then(setListings)
      .catch((reason: unknown) => {
        if (!controller.signal.aborted) {
          setError(reason instanceof Error ? reason.message : "Unable to load your listings.");
          setListings([]);
        }
      })
      .finally(() => {
        if (!controller.signal.aborted) setLoading(false);
      });
    return () => controller.abort();
  }, [accessToken, retry]);

  const availableStatuses = useMemo(
    () => listingStatuses.filter((status) => listings.some((listing) => listing.status === status)),
    [listings],
  );
  const hasUnknownStatus = listings.some((listing) => !isKnownStatus(listing.status));
  const filteredListings = listings.filter((listing) => {
    if (statusFilter === "all") return true;
    if (statusFilter === "other") return !isKnownStatus(listing.status);
    return listing.status === statusFilter;
  });

  if (creating) {
    return (
      <CreateListing
        accessToken={accessToken}
        onCancel={() => setCreating(false)}
        onDraftCreated={() => setRetry((value) => value + 1)}
      />
    );
  }

  if (selectedListing) {
    return (
      <MyListingDetail
        listing={selectedListing}
        accessToken={accessToken}
        onBack={() => setSelectedListing(null)}
        onUpdated={(updated) => {
          setListings((current) =>
            current.map((item) => item.id === updated.id ? updated : item),
          );
          setSelectedListing(updated);
        }}
      />
    );
  }

  return (
    <section className="my-listings" aria-labelledby="my-listings-title">
      <div className="my-listings-heading">
        <div>
          <p className="eyebrow">LISTINGS</p>
          <h1 id="my-listings-title">My Listings</h1>
        </div>
        {!loading && !error && <span className="my-listings-count">{listings.length} total</span>}
        <button className="load-more-button create-listing-action" type="button" onClick={() => setCreating(true)}>
          Create listing
        </button>
      </div>

      {!loading && !error && listings.length > 0 && (
        <div className="my-listings-toolbar">
          <label className="select-control">
            <span className="sr-only">Filter my listings by status</span>
            <select value={statusFilter} onChange={(event) => setStatusFilter(event.target.value as StatusFilter)}>
              <option value="all">All statuses ({listings.length})</option>
              {availableStatuses.map((status) => (
                <option key={status} value={status}>
                  {statusLabels[status]} ({listings.filter((listing) => listing.status === status).length})
                </option>
              ))}
              {hasUnknownStatus && (
                <option value="other">
                  Other status ({listings.filter((listing) => !isKnownStatus(listing.status)).length})
                </option>
              )}
            </select>
          </label>
          <span className="my-listings-filter-count">Showing {filteredListings.length}</span>
        </div>
      )}

      {loading ? (
        <div className="my-listings-message" role="status">Loading listings...</div>
      ) : error ? (
        <div className="my-listings-message" role="alert">
          <h2>Listings unavailable</h2>
          <p>{error}</p>
          <button className="text-button" type="button" onClick={() => setRetry((value) => value + 1)}>Try again</button>
        </div>
      ) : listings.length === 0 ? (
        <div className="my-listings-message" role="status">
          <h2>No listings yet</h2>
          <p>Listings you create will appear here.</p>
        </div>
      ) : filteredListings.length === 0 ? (
        <div className="my-listings-message" role="status">
          <h2>No listings with this status</h2>
          <p>Choose another status to see more listings.</p>
        </div>
      ) : (
        <div className="my-listings-grid">
          {filteredListings.map((listing) => (
            <button
              className="my-listing-card"
              type="button"
              key={listing.id}
              onClick={() => setSelectedListing(listing)}
            >
              <ListingImage listing={listing} />
              <span className="my-listing-card-copy">
                <span className="my-listing-card-topline">
                  <span className="listing-type-label">
                    {listing.asset.asset_type === "ton_nft" ? "TON NFT" : "Telegram gift"}
                  </span>
                  <StatusBadge status={listing.status} />
                </span>
                <span className="my-listing-card-title">{getTitle(listing)}</span>
                <span className="my-listing-card-price">
                  {listing.price_amount} {listing.price_currency}
                </span>
                <time className="my-listing-card-date" dateTime={listing.created_at}>
                  {getCreatedDate(listing.created_at)}
                </time>
              </span>
            </button>
          ))}
        </div>
      )}
    </section>
  );
}

export function MyListings() {
  const session = useSession();
  if (session.status === "loading") {
    return <section className="my-listings-message" role="status">Checking Telegram session...</section>;
  }
  if (session.status === "unauthenticated") {
    return (
      <section className="my-listings-gate" aria-labelledby="my-listings-title">
        <p className="eyebrow">LISTINGS</p>
        <h1 id="my-listings-title">My Listings</h1>
        <div className="my-listings-message" role="status">
          <h2>Open VILTARA in Telegram</h2>
          <p>Sign in through the Telegram Mini App to view your listings.</p>
        </div>
      </section>
    );
  }
  if (session.status === "error") {
    return (
      <section className="my-listings-gate" aria-labelledby="my-listings-title">
        <p className="eyebrow">LISTINGS</p>
        <h1 id="my-listings-title">My Listings</h1>
        <div className="my-listings-message" role="alert">
          <h2>Could not verify your session</h2>
          <p>{session.message}</p>
        </div>
      </section>
    );
  }
  return <AuthenticatedMyListings accessToken={session.accessToken} />;
}
