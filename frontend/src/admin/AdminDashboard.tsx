import { useCallback, useEffect, useMemo, useState } from "react";
import { AdminCenter } from "./AdminCenter";
import {
  fetchAdminOverview,
  fetchAdminUsers,
  fetchAdminUserAudit,
  fetchAdminUserDetail,
  fetchAdminUserListings,
  fetchAdminUserOrders,
  fetchAdminOrders,
  fetchCombinedAdminAuditLog,
  submitUserAccessDecision,
  type AdminAuditLogEntry,
  type AdminOrder,
  type AdminOverview,
  type AdminUser,
  type AdminUserDetail,
  type AdminUserListing,
  type AdminUserOrder,
} from "./api";
import "./admin-dashboard.css";

type DashboardSection = "overview" | "users" | "listings" | "orders" | "audit";
type BlockFilter = "all" | "blocked" | "unblocked";
const PAGE_SIZE = 25;

const sectionLabels: Record<DashboardSection, string> = {
  overview: "Overview",
  users: "Users",
  listings: "Listings",
  orders: "Orders",
  audit: "Audit Log",
};
const listingStatuses: Record<string, string> = {
  draft: "Черновик",
  pending_review: "На модерации",
  active: "Активно",
  reserved: "Зарезервировано",
  sold: "Продано",
  cancelled: "Отменено",
  expired: "Истекло",
  suspended: "Приостановлено",
};
const orderStatuses: Record<string, string> = {
  reserved: "Зарезервирована",
  awaiting_transfer: "Ожидает перевода",
  observing_transfer: "Проверка перевода",
  completed: "Завершена",
  cancelled: "Отменена",
  expired: "Истекла",
};
const deliveryStatuses: Record<string, string> = {
  prepared: "Подготовлена",
  observing: "Проверяется",
  verified: "Подтверждена",
  failed: "Ошибка",
  manual_review: "Ручная проверка",
  cancelled: "Отменена",
};

function formatDate(value: string | null | undefined) {
  if (!value) return "—";
  const date = new Date(value);
  return Number.isNaN(date.getTime())
    ? "—"
    : new Intl.DateTimeFormat("ru-RU", { dateStyle: "medium", timeStyle: "short" }).format(date);
}
function displayName(user: { first_name: string; last_name?: string | null; username?: string | null }) {
  return [user.first_name, user.last_name].filter(Boolean).join(" ") || user.username || "Без имени";
}
function statusLabel(value: string, labels: Record<string, string>) {
  return labels[value] ?? "Неизвестно";
}
function Status({ value, labels }: { value: string; labels: Record<string, string> }) {
  return <span className={"ad-status ad-status-" + value}>{statusLabel(value, labels)}</span>;
}
function LoadingState({ message = "Загружаем данные…" }: { message?: string }) {
  return <p className="ad-state" role="status">{message}</p>;
}
function ErrorState({ message, onRetry }: { message: string; onRetry: () => void }) {
  return (
    <div className="ad-error" role="alert">
      <span>{message}</span>
      <button className="ad-button ad-button-secondary" type="button" onClick={onRetry}>Повторить</button>
    </div>
  );
}
function EmptyState({ message }: { message: string }) {
  return <p className="ad-state">{message}</p>;
}
function UserName({ user, onOpen }: { user: Pick<AdminUser, "id" | "first_name" | "last_name" | "username">; onOpen: (id: string) => void }) {
  return (
    <button className="ad-link-button" type="button" onClick={() => onOpen(user.id)}>
      <span className="ad-avatar" aria-hidden="true">{(user.first_name || "?").slice(0, 1).toLocaleUpperCase("ru-RU")}</span>
      <span className="ad-user-name">
        <strong>{displayName(user)}</strong>
        {user.username && <small>@{user.username}</small>}
      </span>
    </button>
  );
}
function Pager({ total, offset, limit, disabled, onChange }: {
  total: number; offset: number; limit: number; disabled: boolean; onChange: (next: number) => void;
}) {
  return (
    <nav className="ad-pager" aria-label="Навигация по страницам">
      <span>{total === 0 ? "0 записей" : `${offset + 1}–${Math.min(offset + limit, total)} из ${total}`}</span>
      <div>
        <button className="ad-button ad-button-secondary" type="button" disabled={disabled || offset === 0} onClick={() => onChange(Math.max(0, offset - limit))}>Назад</button>
        <button className="ad-button ad-button-secondary" type="button" disabled={disabled || offset + limit >= total} onClick={() => onChange(offset + limit)}>Далее</button>
      </div>
    </nav>
  );
}

export function AdminDashboard({ accessToken }: { accessToken: string }) {
  const [section, setSection] = useState<DashboardSection>("overview");
  const [overview, setOverview] = useState<AdminOverview | null>(null);
  const [overviewLoading, setOverviewLoading] = useState(true);
  const [overviewError, setOverviewError] = useState("");
  const [overviewRetry, setOverviewRetry] = useState(0);
  const [selectedUserId, setSelectedUserId] = useState<string | null>(null);

  const loadOverview = useCallback(async (signal?: AbortSignal) => {
    setOverviewLoading(true);
    setOverviewError("");
    try {
      setOverview(await fetchAdminOverview(accessToken, signal));
    } catch (error) {
      if (!(error instanceof DOMException && error.name === "AbortError")) {
        setOverviewError(error instanceof Error ? error.message : "Не удалось загрузить статистику.");
      }
    } finally {
      if (!signal?.aborted) setOverviewLoading(false);
    }
  }, [accessToken, overviewRetry]);

  useEffect(() => {
    const controller = new AbortController();
    void loadOverview(controller.signal);
    return () => controller.abort();
  }, [loadOverview]);

  return (
    <main className="admin-dashboard" aria-labelledby="admin-dashboard-title">
      <header className="ad-heading">
        <div>
          <p className="ad-eyebrow">VILTARA SHOP · BETA OPERATIONS</p>
          <h1 id="admin-dashboard-title">Admin Dashboard</h1>
          <p>Управление пользователями и обзор платформы. Все действия доступны по серверным правам.</p>
        </div>
        <button className="ad-button ad-button-secondary" type="button" onClick={() => {
          if (section === "overview") setOverviewRetry((value) => value + 1);
          else setSelectedUserId((value) => value);
        }}>{section === "overview" ? "Обновить данные" : "Панель Beta"}</button>
      </header>

      <nav className="ad-tabs" aria-label="Разделы административной панели">
        {(Object.keys(sectionLabels) as DashboardSection[]).map((item) => (
          <button
            type="button"
            key={item}
            aria-current={section === item ? "page" : undefined}
            className={section === item ? "ad-tab ad-tab-active" : "ad-tab"}
            onClick={() => setSection(item)}
          >
            {sectionLabels[item]}
          </button>
        ))}
      </nav>

      <section className="ad-section" aria-label={sectionLabels[section]}>
        {section === "overview" && (
          <OverviewSection
            overview={overview}
            loading={overviewLoading}
            error={overviewError}
            onRetry={() => setOverviewRetry((value) => value + 1)}
            onOpenUser={(id) => setSelectedUserId(id)}
          />
        )}
        {section === "users" && (
          <UsersSection accessToken={accessToken} onOpenUser={setSelectedUserId} />
        )}
        {section === "listings" && <AdminCenter accessToken={accessToken} active showGlobalAuditButton={false} />}
        {section === "orders" && <OrdersSection accessToken={accessToken} />}
        {section === "audit" && <AuditSection accessToken={accessToken} />}
      </section>

      {selectedUserId && (
        <UserDetailPanel
          accessToken={accessToken}
          userId={selectedUserId}
          onClose={() => setSelectedUserId(null)}
          onAccessChanged={() => {
            setOverviewRetry((value) => value + 1);
          }}
        />
      )}
    </main>
  );
}

function OverviewSection({ overview, loading, error, onRetry, onOpenUser }: {
  overview: AdminOverview | null;
  loading: boolean;
  error: string;
  onRetry: () => void;
  onOpenUser: (id: string) => void;
}) {
  if (loading) return <LoadingState message="Считаем статистику платформы…" />;
  if (error || !overview) return <ErrorState message={error || "Статистика недоступна."} onRetry={onRetry} />;
  const { counts } = overview;
  const metrics = [
    { label: "Всего пользователей", value: counts.total_users, note: "Зарегистрированные аккаунты" },
    { label: "Новые за 24 часа", value: counts.new_users_24h, note: "По дате регистрации" },
    { label: "Новые за 7 дней", value: counts.new_users_7d, note: "По дате регистрации" },
    { label: "Заблокированы", value: counts.blocked_users, note: "Ограничены администратором" },
    { label: "Не заблокированы", value: counts.unblocked_users, note: "Это не показатель online" },
    { label: "Всего объявлений", value: counts.total_listings, note: "Все статусы" },
    { label: "Активные объявления", value: counts.active_listings, note: "Доступны в каталоге" },
    { label: "На модерации", value: counts.listings_on_moderation, note: "Ожидают решения" },
    { label: "Зарезервированы", value: counts.reserved_listings, note: "Не означает оплату" },
    { label: "Завершённые сделки", value: counts.completed_deals, note: "Delivery status completed" },
    { label: "Сделки в процессе", value: counts.deals_in_progress, note: "Резерв / перевод / проверка" },
  ];
  return (
    <div className="ad-overview">
      <div className="ad-metric-grid">
        {metrics.map((metric) => (
          <article className="ad-metric" key={metric.label}>
            <span>{metric.label}</span>
            <strong>{metric.value.toLocaleString("ru-RU")}</strong>
            <small>{metric.note}</small>
          </article>
        ))}
      </div>
      <div className="ad-overview-columns">
        <section className="ad-content-section">
          <div className="ad-section-title"><h2>Последние регистрации</h2><span>{overview.recent_registrations.length} показано</span></div>
          {overview.recent_registrations.length === 0 && <EmptyState message="Регистраций пока нет." />}
          <div className="ad-registration-list">
            {overview.recent_registrations.map((user) => (
              <div className="ad-registration-row" key={user.id}>
                <UserName user={user} onOpen={onOpenUser} />
                <time dateTime={user.registered_at}>{formatDate(user.registered_at)}</time>
              </div>
            ))}
          </div>
        </section>
        <section className="ad-content-section">
          <div className="ad-section-title"><h2>Последние события</h2><span>{overview.recent_platform_events.length} показано</span></div>
          {overview.recent_platform_events.length === 0 && <EmptyState message="Событий пока нет." />}
          <div className="ad-event-list">
            {overview.recent_platform_events.map((event) => (
              <article className="ad-event-row" key={event.id}>
                <span className={"ad-event-dot ad-event-" + event.entity_type} aria-hidden="true" />
                <div><strong>{event.summary}</strong><small>{event.entity_type === "order" ? "Сделка" : event.entity_type === "user_access" ? "Доступ пользователя" : "Модерация"}</small></div>
                <time dateTime={event.occurred_at}>{formatDate(event.occurred_at)}</time>
              </article>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
}

function UsersSection({ accessToken, onOpenUser }: {
  accessToken: string;
  onOpenUser: (id: string) => void;
}) {
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [blockedFilter, setBlockedFilter] = useState<BlockFilter>("all");
  const [sortBy, setSortBy] = useState<"registered_at" | "listings" | "deals">("registered_at");
  const [sortOrder, setSortOrder] = useState<"asc" | "desc">("desc");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{ items: AdminUser[]; total: number; limit: number; offset: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true);
    setError("");
    void fetchAdminUsers(accessToken, {
      limit: PAGE_SIZE,
      offset,
      q: query || undefined,
      blocked: blockedFilter === "all" ? null : blockedFilter === "blocked",
      sort_by: sortBy,
      sort_order: sortOrder,
    }, controller.signal)
      .then(setPage)
      .catch((caught: unknown) => {
        if (!(caught instanceof DOMException && caught.name === "AbortError")) {
          setError(caught instanceof Error ? caught.message : "Не удалось загрузить пользователей.");
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [accessToken, offset, query, blockedFilter, sortBy, sortOrder, retry]);

  function applySearch(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    setOffset(0);
    setQuery(queryDraft.trim());
  }
  const total = page?.total ?? 0;

  return (
    <div className="ad-content-section">
      <div className="ad-section-title"><div><h2>Пользователи</h2><p>Поиск, статус аккаунта и метрики профиля</p></div><span>{total.toLocaleString("ru-RU")} всего</span></div>
      <form className="ad-filter-bar" onSubmit={applySearch}>
        <label className="ad-search-label">
          <span>Поиск по username или Telegram ID</span>
          <input value={queryDraft} onChange={(event) => setQueryDraft(event.target.value)} placeholder="@username или 123456789" maxLength={65} />
        </label>
        <label><span>Статус</span><select value={blockedFilter} onChange={(event) => { setOffset(0); setBlockedFilter(event.target.value as BlockFilter); }}>
          <option value="all">Все аккаунты</option><option value="unblocked">Не заблокированы</option><option value="blocked">Заблокированы</option>
        </select></label>
        <label><span>Сортировка</span><select value={sortBy} onChange={(event) => { setOffset(0); setSortBy(event.target.value as typeof sortBy); }}>
          <option value="registered_at">Дата регистрации</option><option value="listings">Количество объявлений</option><option value="deals">Количество сделок</option>
        </select></label>
        <label><span>Порядок</span><select value={sortOrder} onChange={(event) => { setOffset(0); setSortOrder(event.target.value as typeof sortOrder); }}>
          <option value="desc">По убыванию</option><option value="asc">По возрастанию</option>
        </select></label>
        <button className="ad-button ad-button-primary" type="submit">Найти</button>
      </form>
      {loading && <LoadingState message="Загружаем страницу пользователей…" />}
      {error && <ErrorState message={error} onRetry={() => setRetry((value) => value + 1)} />}
      {!loading && !error && page?.items.length === 0 && <EmptyState message="Пользователи по заданным параметрам не найдены." />}
      {!loading && !error && page && page.items.length > 0 && (
        <>
          <div className="ad-table-wrap">
            <table className="ad-table">
              <thead><tr><th>Пользователь</th><th>Telegram ID</th><th>Регистрация</th><th>Статус</th><th>Объявления</th><th>Сделки</th><th>Кошельки</th></tr></thead>
              <tbody>{page.items.map((user) => (
                <tr key={user.id} onClick={() => onOpenUser(user.id)} className="ad-clickable-row">
                  <td><UserName user={user} onOpen={onOpenUser} /></td>
                  <td className="ad-numeric">{user.telegram_id}</td>
                  <td>{formatDate(user.registered_at)}</td>
                  <td><span className={user.is_blocked ? "ad-status ad-status-blocked" : "ad-status ad-status-active"}>{user.is_blocked ? "Заблокирован" : "Активен"}</span></td>
                  <td className="ad-numeric">{user.listing_count}</td><td className="ad-numeric">{user.deal_count}</td><td className="ad-numeric">{user.confirmed_wallet_count}</td>
                </tr>
              ))}</tbody>
            </table>
          </div>
          <div className="ad-user-cards">{page.items.map((user) => (
            <button className="ad-user-card" type="button" key={user.id} onClick={() => onOpenUser(user.id)}>
              <div className="ad-user-card-heading"><span className="ad-avatar" aria-hidden="true">{user.first_name.slice(0, 1).toLocaleUpperCase("ru-RU")}</span><span><strong>{displayName(user)}</strong><small>{user.username ? "@" + user.username : "Без username"} · ID {user.telegram_id}</small></span><span className={user.is_blocked ? "ad-status ad-status-blocked" : "ad-status ad-status-active"}>{user.is_blocked ? "Блок" : "Активен"}</span></div>
              <div className="ad-user-card-stats"><span>Регистрация <strong>{formatDate(user.registered_at)}</strong></span><span>Объявления <strong>{user.listing_count}</strong></span><span>Сделки <strong>{user.deal_count}</strong></span><span>Кошельки <strong>{user.confirmed_wallet_count}</strong></span></div>
            </button>
          ))}</div>
          <Pager total={page.total} offset={offset} limit={PAGE_SIZE} disabled={loading} onChange={setOffset} />
        </>
      )}
    </div>
  );
}

function UserDetailPanel({ accessToken, userId, onClose, onAccessChanged }: {
  accessToken: string;
  userId: string;
  onClose: () => void;
  onAccessChanged: () => void;
}) {
  const [detail, setDetail] = useState<AdminUserDetail | null>(null);
  const [listings, setListings] = useState<AdminUserListing[]>([]);
  const [orders, setOrders] = useState<AdminUserOrder[]>([]);
  const [audit, setAudit] = useState<AdminAuditLogEntry[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [reason, setReason] = useState("");
  const [decisionOpen, setDecisionOpen] = useState(false);
  const [decisionAction, setDecisionAction] = useState<"block" | "unblock">("block");
  const [submitting, setSubmitting] = useState(false);
  const [decisionError, setDecisionError] = useState("");
  const [success, setSuccess] = useState("");
  const [reload, setReload] = useState(0);

  const load = useCallback(async (signal?: AbortSignal) => {
    setLoading(true);
    setError("");
    try {
      const [user, listingPage, orderPage, auditPage] = await Promise.all([
        fetchAdminUserDetail(accessToken, userId, signal),
        fetchAdminUserListings(accessToken, userId, { limit: 10, offset: 0 }, signal),
        fetchAdminUserOrders(accessToken, userId, { limit: 10, offset: 0 }, signal),
        fetchAdminUserAudit(accessToken, userId, { limit: 10, offset: 0 }, signal),
      ]);
      setDetail(user);
      setListings(listingPage.items);
      setOrders(orderPage.items);
      setAudit(auditPage.items);
    } catch (caught) {
      if (!(caught instanceof DOMException && caught.name === "AbortError")) {
        setError(caught instanceof Error ? caught.message : "Не удалось загрузить карточку пользователя.");
      }
    } finally {
      if (!signal?.aborted) setLoading(false);
    }
  }, [accessToken, userId, reload]);

  useEffect(() => {
    const controller = new AbortController();
    void load(controller.signal);
    return () => controller.abort();
  }, [load]);

  useEffect(() => {
    function onKeyDown(event: KeyboardEvent) {
      if (event.key === "Escape" && !decisionOpen) onClose();
    }
    window.addEventListener("keydown", onKeyDown);
    return () => window.removeEventListener("keydown", onKeyDown);
  }, [decisionOpen, onClose]);

  async function submitAccessDecision(event: React.FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!detail || reason.trim().length < 5 || submitting) return;
    setSubmitting(true);
    setDecisionError("");
    setSuccess("");
    try {
      const result = await submitUserAccessDecision(accessToken, detail.id, decisionAction, reason.trim());
      setDetail((previous) => previous ? { ...previous, is_blocked: result.is_blocked } : previous);
      setSuccess(decisionAction === "block" ? "Аккаунт заблокирован, решение записано в журнал." : "Ограничение снято, решение записано в журнал.");
      setDecisionOpen(false);
      setReason("");
      setReload((value) => value + 1);
      onAccessChanged();
    } catch (caught) {
      setDecisionError(caught instanceof Error ? caught.message : "Не удалось сохранить решение.");
    } finally {
      setSubmitting(false);
    }
  }

  return (
    <div className="ad-panel-backdrop" onMouseDown={(event) => { if (event.target === event.currentTarget && !decisionOpen) onClose(); }}>
      <aside className="ad-user-panel" role="dialog" aria-modal="true" aria-labelledby="ad-user-panel-title">
        <header className="ad-panel-header">
          <div><p className="ad-eyebrow">USER RECORD</p><h2 id="ad-user-panel-title">Карточка пользователя</h2></div>
          <button className="ad-icon-button" type="button" aria-label="Закрыть карточку" onClick={onClose}>×</button>
        </header>
        {loading && <LoadingState message="Загружаем данные пользователя…" />}
        {error && <ErrorState message={error} onRetry={() => setReload((value) => value + 1)} />}
        {!loading && !error && detail && (
          <>
            <section className="ad-user-profile">
              <div className="ad-profile-top"><span className="ad-avatar ad-avatar-large" aria-hidden="true">{detail.first_name.slice(0, 1).toLocaleUpperCase("ru-RU")}</span><div><h3>{displayName(detail)}</h3><p>{detail.username ? "@" + detail.username : "Username не задан"} · Telegram ID {detail.telegram_id}</p></div></div>
              <div className="ad-profile-status"><span className={detail.is_blocked ? "ad-status ad-status-blocked" : "ad-status ad-status-active"}>{detail.is_blocked ? "Аккаунт заблокирован" : "Аккаунт доступен"}</span><span>Регистрация: {formatDate(detail.registered_at)}</span></div>
              <div className="ad-detail-stats"><span>Объявления <strong>{detail.listing_count}</strong></span><span>Сделки <strong>{detail.deal_count}</strong></span><span>Кошельки <strong>{detail.confirmed_wallet_count}</strong></span></div>
              <button className={detail.is_blocked ? "ad-button ad-button-primary" : "ad-button ad-button-danger"} type="button" onClick={() => {
                setDecisionAction(detail.is_blocked ? "unblock" : "block");
                setReason("");
                setDecisionError("");
                setDecisionOpen(true);
              }}>{detail.is_blocked ? "Разблокировать пользователя" : "Заблокировать пользователя"}</button>
              {success && <p className="ad-success" role="status">{success}</p>}
            </section>
            <section className="ad-detail-section">
              <div className="ad-section-title"><h3>Подтверждённые кошельки</h3><span>{detail.verified_wallets.length}</span></div>
              {detail.verified_wallets.length === 0 && <EmptyState message="Подтверждённых кошельков нет." />}
              {detail.verified_wallets.map((wallet) => <div className="ad-wallet-row" key={wallet.address_short + wallet.network}><code>{wallet.address_short}</code><span>{wallet.network}</span>{wallet.is_primary && <small>Основной</small>}</div>)}
            </section>
            <section className="ad-detail-section">
              <div className="ad-section-title"><h3>Объявления</h3><span>{listings.length} последних</span></div>
              {listings.length === 0 && <EmptyState message="Объявлений нет." />}
              {listings.map((listing) => <article className="ad-mini-record" key={listing.id}><div><strong>{listing.title || listing.asset_name || "Без названия"}</strong><small>{formatDate(listing.created_at)} · {listing.price_amount} {listing.price_currency}</small></div><Status value={listing.status} labels={listingStatuses} /></article>)}
            </section>
            <section className="ad-detail-section">
              <div className="ad-section-title"><h3>Сделки</h3><span>{orders.length} последних</span></div>
              {orders.length === 0 && <EmptyState message="Сделок нет." />}
              {orders.map((order) => <article className="ad-mini-record" key={order.id}><div><strong>{order.listing_title || order.asset_name || "Без названия"}</strong><small>{order.role === "buyer" ? "Покупатель" : "Продавец"} · {order.price_amount} {order.price_currency} · {displayName({ first_name: order.counterparty_name, username: order.counterparty_username })}</small><small>Доставка: {order.delivery_status ? statusLabel(order.delivery_status, deliveryStatuses) : "Нет данных"}</small></div><Status value={order.status} labels={orderStatuses} /></article>)}
            </section>
            <section className="ad-detail-section">
              <div className="ad-section-title"><h3>История действий</h3><span>{audit.length} последних</span></div>
              {audit.length === 0 && <EmptyState message="Административных действий над пользователем пока нет." />}
              {audit.map((entry) => <article className="ad-audit-row" key={entry.id}><div><strong>{entry.target_type === "listing" ? "Модерация объявления" : entry.action === "blocked" ? "Блокировка пользователя" : entry.action === "unblocked" ? "Разблокировка пользователя" : entry.action}</strong><small>{entry.reason}</small></div><time dateTime={entry.occurred_at}>{formatDate(entry.occurred_at)}</time></article>)}
            </section>
          </>
        )}
        {decisionOpen && detail && (
          <div className="ad-decision-backdrop">
            <section className="ad-decision-dialog" role="dialog" aria-modal="true" aria-labelledby="ad-decision-title">
              <h3 id="ad-decision-title">{decisionAction === "block" ? "Заблокировать пользователя?" : "Разблокировать пользователя?"}</h3>
              <p>{displayName(detail)} · Telegram ID {detail.telegram_id}</p>
              <p>{decisionAction === "block" ? "Пользователь не сможет создавать объявления и новые сделки. Существующие сделки и доступ к необходимой истории сохраняются." : "Пользователь снова сможет создавать объявления и новые сделки."}</p>
              <form onSubmit={(event) => void submitAccessDecision(event)}>
                <label>Причина решения (5–500 символов)<textarea value={reason} minLength={5} maxLength={500} required rows={4} onChange={(event) => setReason(event.target.value)} placeholder="Укажите причину для административного журнала…" /></label>
                {decisionError && <p className="ad-error-message" role="alert">{decisionError}</p>}
                <div className="ad-dialog-actions">
                  <button className="ad-button ad-button-secondary" type="button" disabled={submitting} onClick={() => setDecisionOpen(false)}>Отмена</button>
                  <button className={decisionAction === "block" ? "ad-button ad-button-danger" : "ad-button ad-button-primary"} type="submit" disabled={submitting || reason.trim().length < 5}>{submitting ? "Сохраняем…" : decisionAction === "block" ? "Подтвердить блокировку" : "Подтвердить разблокировку"}</button>
                </div>
              </form>
            </section>
          </div>
        )}
      </aside>
    </div>
  );
}

function OrdersSection({ accessToken }: { accessToken: string }) {
  const [queryDraft, setQueryDraft] = useState("");
  const [query, setQuery] = useState("");
  const [status, setStatus] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{ items: AdminOrder[]; total: number; limit: number; offset: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    void fetchAdminOrders(accessToken, { limit: PAGE_SIZE, offset, q: query || undefined, status: status || undefined }, controller.signal)
      .then(setPage)
      .catch((caught: unknown) => {
        if (!(caught instanceof DOMException && caught.name === "AbortError")) {
          setError(caught instanceof Error ? caught.message : "Не удалось загрузить сделки.");
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [accessToken, offset, query, status, retry]);

  return (
    <section className="ad-content-section">
      <div className="ad-section-title"><div><h2>Сделки</h2><p>Только чтение · резервирование не является оплатой</p></div><span>{page?.total ?? 0} всего</span></div>
      <form className="ad-filter-bar ad-order-filter" onSubmit={(event) => { event.preventDefault(); setOffset(0); setQuery(queryDraft.trim()); }}>
        <label className="ad-search-label"><span>Поиск по UUID сделки</span><input value={queryDraft} onChange={(event) => setQueryDraft(event.target.value)} placeholder="ID сделки" maxLength={36} /></label>
        <label><span>Статус сделки</span><select value={status} onChange={(event) => { setOffset(0); setStatus(event.target.value); }}>
          <option value="">Все статусы</option>{Object.entries(orderStatuses).map(([value, label]) => <option key={value} value={value}>{label}</option>)}
        </select></label>
        <button className="ad-button ad-button-primary" type="submit">Найти</button>
      </form>
      {loading && <LoadingState message="Загружаем сделки…" />}
      {error && <ErrorState message={error} onRetry={() => setRetry((value) => value + 1)} />}
      {!loading && !error && page?.items.length === 0 && <EmptyState message="Сделки не найдены." />}
      {!loading && !error && page && page.items.length > 0 && <>
        <div className="ad-table-wrap"><table className="ad-table"><thead><tr><th>ID</th><th>Объявление</th><th>Покупатель</th><th>Продавец</th><th>Цена</th><th>Статус</th><th>Доставка</th><th>Создана</th></tr></thead>
          <tbody>{page.items.map((order) => <tr key={order.id}><td><code>{order.id.slice(0, 8)}…</code></td><td><strong>{order.listing_title || order.asset_name || "Без названия"}</strong><small>{order.listing_id.slice(0, 8)}…</small></td><td>{order.buyer_name}{order.buyer_username && <small>@{order.buyer_username}</small>}</td><td>{order.seller_name}{order.seller_username && <small>@{order.seller_username}</small>}</td><td>{order.price_amount} {order.price_currency}</td><td><Status value={order.status} labels={orderStatuses} /></td><td><span>{order.delivery_status ? statusLabel(order.delivery_status, deliveryStatuses) : "Нет данных"}</span>{order.delivery_verified_at && <small>{formatDate(order.delivery_verified_at)}</small>}</td><td>{formatDate(order.created_at)}</td></tr>)}</tbody>
        </table></div>
        <div className="ad-user-cards">{page.items.map((order) => <article className="ad-user-card ad-order-card" key={order.id}>
          <div className="ad-order-card-top"><strong>{order.listing_title || order.asset_name || "Без названия"}</strong><Status value={order.status} labels={orderStatuses} /></div>
          <small>ID {order.id}</small><p>{order.buyer_name} → {order.seller_name}</p><p>{order.price_amount} {order.price_currency}</p>
          <p>Доставка: {order.delivery_status ? statusLabel(order.delivery_status, deliveryStatuses) : "Нет данных"}</p><time dateTime={order.created_at}>{formatDate(order.created_at)}</time>
        </article>)}</div>
        <Pager total={page.total} offset={offset} limit={PAGE_SIZE} disabled={loading} onChange={setOffset} />
      </>}
    </section>
  );
}

function AuditSection({ accessToken }: { accessToken: string }) {
  const [targetType, setTargetType] = useState<"" | "listing" | "user">("");
  const [action, setAction] = useState("");
  const [offset, setOffset] = useState(0);
  const [page, setPage] = useState<{ items: AdminAuditLogEntry[]; total: number; limit: number; offset: number } | null>(null);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [retry, setRetry] = useState(0);

  useEffect(() => {
    const controller = new AbortController();
    setLoading(true); setError("");
    void fetchCombinedAdminAuditLog(accessToken, {
      limit: PAGE_SIZE, offset, target_type: targetType || undefined, action: action || undefined,
    }, controller.signal)
      .then(setPage)
      .catch((caught: unknown) => {
        if (!(caught instanceof DOMException && caught.name === "AbortError")) {
          setError(caught instanceof Error ? caught.message : "Не удалось загрузить журнал аудита.");
        }
      })
      .finally(() => { if (!controller.signal.aborted) setLoading(false); });
    return () => controller.abort();
  }, [accessToken, targetType, action, offset, retry]);

  return (
    <section className="ad-content-section">
      <div className="ad-section-title"><div><h2>Журнал аудита</h2><p>Неизменяемая история решений администраторов</p></div><span>{page?.total ?? 0} записей</span></div>
      <div className="ad-filter-bar">
        <label><span>Объект</span><select value={targetType} onChange={(event) => { setOffset(0); setTargetType(event.target.value as typeof targetType); }}><option value="">Все объекты</option><option value="listing">Объявления</option><option value="user">Пользователи</option></select></label>
        <label><span>Действие</span><select value={action} onChange={(event) => { setOffset(0); setAction(event.target.value); }}>
          <option value="">Все действия</option><option value="approved">Одобрено</option><option value="rejected">Отклонено</option><option value="suspended">Приостановлено</option><option value="restored">Восстановлено</option><option value="blocked">Пользователь заблокирован</option><option value="unblocked">Пользователь разблокирован</option>
        </select></label>
      </div>
      {loading && <LoadingState message="Загружаем журнал…" />}
      {error && <ErrorState message={error} onRetry={() => setRetry((value) => value + 1)} />}
      {!loading && !error && page?.items.length === 0 && <EmptyState message="Записей по заданным фильтрам нет." />}
      {!loading && !error && page && page.items.length > 0 && <>
        <div className="ad-table-wrap"><table className="ad-table"><thead><tr><th>Время</th><th>Действие</th><th>Объект</th><th>Причина</th><th>Администратор</th></tr></thead>
          <tbody>{page.items.map((entry) => <tr key={entry.id}><td>{formatDate(entry.occurred_at)}</td><td><Status value={entry.action} labels={{ approved: "Одобрено", rejected: "Отклонено", suspended: "Приостановлено", restored: "Восстановлено", blocked: "Блокировка", unblocked: "Разблокировка" }} /></td><td>{entry.target_type === "listing" ? "Объявление" : "Пользователь"} <small>{entry.target_id}</small></td><td>{entry.reason}</td><td><code>{entry.actor_id.slice(0, 8)}…</code></td></tr>)}</tbody>
        </table></div>
        <div className="ad-user-cards">{page.items.map((entry) => <article className="ad-user-card" key={entry.id}><div className="ad-order-card-top"><strong>{entry.action === "blocked" ? "Блокировка" : entry.action === "unblocked" ? "Разблокировка" : entry.action === "approved" ? "Одобрение объявления" : entry.action === "rejected" ? "Отклонение объявления" : entry.action === "suspended" ? "Приостановка объявления" : "Восстановление объявления"}</strong><time dateTime={entry.occurred_at}>{formatDate(entry.occurred_at)}</time></div><p>{entry.reason}</p><small>{entry.target_type === "listing" ? "Объявление" : "Пользователь"} · {entry.target_id}</small><small>Администратор · {entry.actor_id}</small></article>)}</div>
        <Pager total={page.total} offset={offset} limit={PAGE_SIZE} disabled={loading} onChange={setOffset} />
      </>}
    </section>
  );
}
