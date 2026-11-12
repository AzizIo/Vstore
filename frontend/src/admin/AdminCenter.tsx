import { useCallback, useEffect, useState, type FormEvent } from "react";
import { fetchAuditHistory, fetchModerationQueue, submitModerationDecision, type AuditEntry, type ModerationAction, type ModerationItem, type ModerationReasonCode } from "./api";
import "./admin.css";

const reasonLabels: Record<string, string> = {
  draft_pending_review: "Draft awaiting review", moderator_suspended: "Previously suspended",
  active_listing_review: "Active listing available for moderation", asset_not_verified: "Asset is not currently verified",
  asset_owner_mismatch: "Asset owner differs from seller", listing_expired: "Listing has expired",
};
const actionLabels: Record<ModerationAction, string> = { approve: "Approve", reject: "Reject", suspend: "Suspend", restore: "Restore" };
const reasonCodeLabels: Record<ModerationReasonCode, string> = {
  policy_violation: "Policy violation", ownership_unverified: "Ownership could not be verified",
  misleading_metadata: "Misleading metadata", duplicate_listing: "Duplicate listing", other: "Other",
};
interface Props { accessToken: string; active: boolean; }

export function AdminCenter({ accessToken, active }: Props) {
  const [items, setItems] = useState<ModerationItem[]>([]);
  const [total, setTotal] = useState(0);
  const [offset, setOffset] = useState(0);
  const [statusFilter, setStatusFilter] = useState("");
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);
  const [selected, setSelected] = useState<ModerationItem | null>(null);
  const [action, setAction] = useState<ModerationAction>("suspend");
  const [reasonCode, setReasonCode] = useState<ModerationReasonCode>("other");
  const [reason, setReason] = useState("");
  const [submitting, setSubmitting] = useState(false);
  const [success, setSuccess] = useState("");
  const [auditFor, setAuditFor] = useState<string | null>(null);
  const [audit, setAudit] = useState<AuditEntry[]>([]);
  const [auditError, setAuditError] = useState("");
  const pageSize = 25;

  const loadQueue = useCallback(async (signal?: AbortSignal) => {
    setLoading(true); setError("");
    try {
      const page = await fetchModerationQueue(accessToken, { limit: pageSize, offset, ...(statusFilter ? { status: statusFilter } : {}) }, signal);
      setItems(page.items); setTotal(page.total);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) setError(caught instanceof Error ? caught.message : "Unable to load the moderation queue.");
    } finally { setLoading(false); }
  }, [accessToken, offset, statusFilter, retry]);

  useEffect(() => {
    if (!active) return;
    const controller = new AbortController();
    void loadQueue(controller.signal);
    return () => controller.abort();
  }, [active, loadQueue]);

  async function openAudit(item: ModerationItem) {
    setAuditFor(item.id); setAudit([]); setAuditError("");
    try { setAudit((await fetchAuditHistory(accessToken, item.id)).items); }
    catch (caught) { setAuditError(caught instanceof Error ? caught.message : "Unable to load audit history."); }
  }
  function startAction(item: ModerationItem, nextAction: ModerationAction) {
    setSelected(item); setAction(nextAction); setReasonCode("other"); setReason(""); setSuccess("");
  }
  async function submitDecision(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!selected || reason.trim().length < 5 || submitting) return;
    setSubmitting(true); setError(""); setSuccess("");
    try {
      const result = await submitModerationDecision(accessToken, selected.id, { action, reason_code: reasonCode, reason: reason.trim() });
      setSuccess(actionLabels[action] + " decision saved · " + result.id);
      setSelected(null); setOffset(0);
      const page = await fetchModerationQueue(accessToken, { limit: pageSize, offset: 0, ...(statusFilter ? { status: statusFilter } : {}) });
      setItems(page.items); setTotal(page.total);
      if (auditFor === selected.id) await openAudit(selected);
    } catch (caught) { setError(caught instanceof Error ? caught.message : "Decision failed. Retry when ready."); }
    finally { setSubmitting(false); }
  }
  if (!active) return null;

  return (
    <section className="admin-center" aria-labelledby="admin-center-title">
      <header className="admin-center-header">
        <div><p className="admin-eyebrow">CONTROL PLANE</p><h1 id="admin-center-title">Moderation &amp; Audit</h1><p>Every decision requires a reason and is preserved in the audit trail.</p></div>
        <button type="button" className="admin-secondary" onClick={() => setRetry((value) => value + 1)} disabled={loading}>{loading ? "Refreshing…" : "Refresh queue"}</button>
      </header>
      {success && <p className="admin-success" role="status">{success}</p>}
      {error && <div className="admin-error" role="alert"><span>{error}</span><button type="button" onClick={() => setRetry((value) => value + 1)}>Retry</button></div>}
      <div className="admin-toolbar">
        <label>Listing status<select value={statusFilter} onChange={(event) => { setOffset(0); setStatusFilter(event.target.value); }}>
          <option value="">All actionable statuses</option><option value="draft">Draft</option><option value="active">Active</option><option value="suspended">Suspended</option>
        </select></label><span className="admin-count">{total} listing{total === 1 ? "" : "s"}</span>
      </div>
      {loading && <p className="admin-state" role="status">Loading moderation queue…</p>}
      {!loading && !error && items.length === 0 && <p className="admin-state" role="status">No listings require attention for this filter.</p>}
      <div className="admin-queue">
        {items.map((item) => <article className="admin-listing" key={item.id}>
          <div className="admin-listing-art">{item.asset.image_url ? <img src={item.asset.image_url} alt="" loading="lazy" /> : <span aria-hidden="true">V</span>}</div>
          <div className="admin-listing-main">
            <div className="admin-listing-title-row"><h2>{item.title || item.asset.name || "Untitled listing"}</h2><span className={"admin-status admin-status-" + item.status}>{item.status}</span></div>
            <p className="admin-meta">{item.price_amount} {item.price_currency} · {item.seller.first_name}{item.seller.username ? " · @" + item.seller.username : ""}</p>
            <p className="admin-reasons">{item.queue_reasons.map((code) => reasonLabels[code] ?? code).join(" · ")}</p>
            <div className="admin-actions">
              {item.status === "draft" && <><button type="button" className="admin-primary" onClick={() => startAction(item, "approve")}>Approve</button><button type="button" className="admin-danger" onClick={() => startAction(item, "reject")}>Reject</button></>}
              {item.status === "active" && <button type="button" className="admin-danger" onClick={() => startAction(item, "suspend")}>Suspend</button>}
              {item.status === "suspended" && <button type="button" className="admin-primary" onClick={() => startAction(item, "restore")}>Restore</button>}
              <button type="button" className="admin-secondary" onClick={() => void openAudit(item)}>Audit history</button>
            </div>
            {auditFor === item.id && <div className="admin-audit" aria-label={"Audit history for " + (item.title || "listing")}>
              <h3>Audit history</h3>{auditError && <p role="alert">{auditError}</p>}
              {!auditError && audit.length === 0 && <p>No moderation decisions recorded.</p>}
              {audit.map((entry) => <div className="admin-audit-entry" key={entry.id}>
                <strong>{entry.action}</strong><time dateTime={entry.occurred_at}>{new Date(entry.occurred_at).toLocaleString()}</time>
                <p>{entry.reason_code.replaceAll("_", " ")} — {entry.reason}</p><span>{String(entry.before_snapshot.status)} → {String(entry.after_snapshot.status)}</span>
              </div>)}
            </div>}
          </div>
        </article>)}
      </div>
      <nav className="admin-pagination" aria-label="Moderation pagination">
        <button type="button" className="admin-secondary" onClick={() => setOffset(Math.max(0, offset - pageSize))} disabled={offset === 0 || loading}>Previous</button>
        <span>{total === 0 ? 0 : offset + 1}–{Math.min(offset + pageSize, total)} of {total}</span>
        <button type="button" className="admin-secondary" onClick={() => setOffset(offset + pageSize)} disabled={offset + pageSize >= total || loading}>Next</button>
      </nav>
      {selected && <div className="admin-dialog-backdrop"><section className="admin-dialog" role="dialog" aria-modal="true" aria-labelledby="admin-dialog-title">
        <h2 id="admin-dialog-title">{actionLabels[action]} listing</h2><p>{selected.title || selected.asset.name || "Untitled listing"} · current status: {selected.status}</p>
        {(action === "approve" || action === "restore") && <p className="admin-warning">This action requires a fresh backend ownership verification.</p>}
        <form onSubmit={(event) => void submitDecision(event)}>
          <label>Reason code<select value={reasonCode} onChange={(event) => setReasonCode(event.target.value as ModerationReasonCode)}>
            {Object.entries(reasonCodeLabels).map(([value, label]) => <option value={value} key={value}>{label}</option>)}
          </select></label>
          <label>Explanation (5–500 characters)<textarea value={reason} minLength={5} maxLength={500} required onChange={(event) => setReason(event.target.value)} placeholder="Explain the moderation decision…" rows={4} /></label>
          <div className="admin-dialog-actions">
            <button type="button" className="admin-secondary" onClick={() => setSelected(null)} disabled={submitting}>Cancel</button>
            <button type="submit" className={action === "reject" || action === "suspend" ? "admin-danger" : "admin-primary"} disabled={submitting || reason.trim().length < 5}>{submitting ? "Saving…" : "Confirm " + actionLabels[action].toLowerCase()}</button>
          </div>
        </form>
      </section></div>}
    </section>
  );
}
