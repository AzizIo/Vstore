from __future__ import annotations

from datetime import UTC, datetime, timedelta
import re
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request, status
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import String, case, cast, func, or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import aliased

from app.admin.moderation import require_admin
from app.core.config import get_settings
from app.db.models import (
    AdminUserAuditLog,
    Listing,
    ListingStatus,
    ModerationAuditLog,
    NFTAsset,
    Order,
    OrderDeliveryAttempt,
    OrderEvent,
    OrderStatus,
    User,
    Wallet,
)
from app.db.session import get_db_session

router = APIRouter(prefix="/admin", tags=["admin user management"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
AdminUser = Annotated[User, Depends(require_admin)]

AdminUserSort = Literal["registered_at", "listings", "deals"]
SortOrder = Literal["asc", "desc"]
PageLimit = Annotated[int, Query(ge=1, le=100)]
PageOffset = Annotated[int, Query(ge=0, le=10000)]
SearchQuery = Annotated[
    str | None,
    Query(min_length=1, max_length=65, pattern=r"^@?[A-Za-z0-9_]+$"),
]
OrderSearchQuery = Annotated[
    str | None,
    Query(min_length=1, max_length=36, pattern=r"^[0-9a-fA-F-]{1,36}$"),
]
IdempotencyKey = Annotated[
    str, Header(alias="Idempotency-Key", min_length=8, max_length=128)
]


class AdminUserSummaryDTO(BaseModel):
    id: UUID
    first_name: str
    last_name: str | None
    username: str | None
    telegram_id: int
    registered_at: datetime
    is_blocked: bool
    listing_count: int
    deal_count: int
    confirmed_wallet_count: int


class AdminUserPageDTO(BaseModel):
    items: list[AdminUserSummaryDTO]
    total: int
    limit: int
    offset: int


class VerifiedWalletDTO(BaseModel):
    address_short: str
    network: str
    is_primary: bool


class AdminUserDetailDTO(AdminUserSummaryDTO):
    verified_wallets: list[VerifiedWalletDTO]


class AdminUserListingDTO(BaseModel):
    id: UUID
    status: str
    title: str | None
    asset_name: str | None
    price_amount: str
    price_currency: str
    created_at: datetime
    updated_at: datetime
    expires_at: datetime | None


class AdminUserListingsPageDTO(BaseModel):
    items: list[AdminUserListingDTO]
    total: int
    limit: int
    offset: int


class AdminUserOrderDTO(BaseModel):
    id: UUID
    role: Literal["buyer", "seller"]
    status: str
    listing_id: UUID
    listing_title: str | None
    asset_name: str | None
    counterparty_name: str
    counterparty_username: str | None
    price_amount: str
    price_currency: str
    created_at: datetime
    updated_at: datetime
    delivery_status: str | None
    delivery_verified_at: datetime | None


class AdminUserOrdersPageDTO(BaseModel):
    items: list[AdminUserOrderDTO]
    total: int
    limit: int
    offset: int


class AdminOrderDTO(BaseModel):
    id: UUID
    listing_id: UUID
    listing_title: str | None
    asset_name: str | None
    buyer_id: UUID
    buyer_name: str
    buyer_username: str | None
    seller_id: UUID
    seller_name: str
    seller_username: str | None
    price_amount: str
    price_currency: str
    status: str
    created_at: datetime
    updated_at: datetime
    delivery_status: str | None
    delivery_verified_at: datetime | None


class AdminOrderPageDTO(BaseModel):
    items: list[AdminOrderDTO]
    total: int
    limit: int
    offset: int


class AdminUserAuditDTO(BaseModel):
    id: UUID
    actor_id: UUID
    target_user_id: UUID
    action: Literal["blocked", "unblocked"]
    reason: str
    before_snapshot: dict[str, object]
    after_snapshot: dict[str, object]
    request_id: str | None
    idempotency_key: str
    occurred_at: datetime


class AdminUserAuditPageDTO(BaseModel):
    items: list[AdminUserAuditDTO]
    total: int
    limit: int
    offset: int


class AdminUserAccessDecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 5:
            raise ValueError("Reason must contain at least five non-whitespace characters")
        return normalized


class AdminUserAccessDecisionResponse(BaseModel):
    user_id: UUID
    is_blocked: bool
    audit: AdminUserAuditDTO


class AdminOverviewCountsDTO(BaseModel):
    total_users: int
    new_users_24h: int
    new_users_7d: int
    blocked_users: int
    unblocked_users: int
    total_listings: int
    active_listings: int
    listings_on_moderation: int
    reserved_listings: int
    completed_deals: int
    deals_in_progress: int


class AdminPlatformEventDTO(BaseModel):
    id: UUID
    entity_type: Literal["order", "listing_moderation", "user_access"]
    entity_id: UUID
    summary: str
    occurred_at: datetime


class AdminOverviewDTO(BaseModel):
    counts: AdminOverviewCountsDTO
    recent_registrations: list[AdminUserSummaryDTO]
    recent_platform_events: list[AdminPlatformEventDTO]


def _listing_count_expr():
    return (
        select(func.count(Listing.id))
        .where(Listing.seller_id == User.id)
        .correlate(User)
        .scalar_subquery()
    )


def _deal_count_expr():
    return (
        select(func.count(Order.id))
        .where(or_(Order.buyer_id == User.id, Order.seller_id == User.id))
        .correlate(User)
        .scalar_subquery()
    )


def _confirmed_wallet_count_expr():
    return (
        select(func.count(Wallet.id))
        .where(Wallet.user_id == User.id, Wallet.is_verified.is_(True))
        .correlate(User)
        .scalar_subquery()
    )


def _summary_select():
    return select(
        User,
        _listing_count_expr().label("listing_count"),
        _deal_count_expr().label("deal_count"),
        _confirmed_wallet_count_expr().label("confirmed_wallet_count"),
    )


def _summary_from_row(row) -> AdminUserSummaryDTO:
    user = row[0]
    return AdminUserSummaryDTO(
        id=user.id,
        first_name=user.first_name,
        last_name=user.last_name,
        username=user.username,
        telegram_id=user.telegram_id,
        registered_at=user.created_at,
        is_blocked=user.is_blocked,
        listing_count=int(row[1] or 0),
        deal_count=int(row[2] or 0),
        confirmed_wallet_count=int(row[3] or 0),
    )


def _shorten_address(address: str) -> str:
    value = address.strip()
    if len(value) <= 16:
        return value[:5] + "…" + value[-3:] if len(value) > 8 else value[:3] + "…"
    return value[:8] + "…" + value[-6:]


def _status_value(value: object | None) -> str | None:
    if value is None:
        return None
    return str(value.value if hasattr(value, "value") else value)


def _display_name(first_name: str, last_name: str | None) -> str:
    return " ".join(part for part in (first_name, last_name) if part).strip()


async def _find_user_summary(
    session: AsyncSession, user_id: UUID
) -> AdminUserSummaryDTO | None:
    row = (
        await session.execute(_summary_select().where(User.id == user_id).limit(1))
    ).first()
    return _summary_from_row(row) if row is not None else None


def _base_orders_select():
    buyer = aliased(User, name="buyer_user")
    seller = aliased(User, name="seller_user")
    delivery_status = (
        select(OrderDeliveryAttempt.status)
        .where(OrderDeliveryAttempt.order_id == Order.id)
        .order_by(OrderDeliveryAttempt.attempt_number.desc())
        .limit(1)
        .correlate(Order)
        .scalar_subquery()
    )
    delivery_verified_at = (
        select(OrderDeliveryAttempt.verified_at)
        .where(OrderDeliveryAttempt.order_id == Order.id)
        .order_by(OrderDeliveryAttempt.attempt_number.desc())
        .limit(1)
        .correlate(Order)
        .scalar_subquery()
    )
    statement = (
        select(
            Order,
            Listing.title,
            NFTAsset.name,
            buyer.first_name,
            buyer.last_name,
            buyer.username,
            seller.first_name,
            seller.last_name,
            seller.username,
            delivery_status.label("delivery_status"),
            delivery_verified_at.label("delivery_verified_at"),
        )
        .join(Listing, Listing.id == Order.listing_id)
        .join(NFTAsset, NFTAsset.id == Listing.asset_id)
        .join(buyer, buyer.id == Order.buyer_id)
        .join(seller, seller.id == Order.seller_id)
    )
    return statement


def _user_order_dto(row, user_id: UUID) -> AdminUserOrderDTO:
    order = row[0]
    is_buyer = order.buyer_id == user_id
    counterparty_first = row[6] if is_buyer else row[3]
    counterparty_last = row[7] if is_buyer else row[4]
    counterparty_username = row[8] if is_buyer else row[5]
    return AdminUserOrderDTO(
        id=order.id,
        role="buyer" if is_buyer else "seller",
        status=order.status.value,
        listing_id=order.listing_id,
        listing_title=row[1],
        asset_name=row[2],
        counterparty_name=_display_name(counterparty_first, counterparty_last),
        counterparty_username=counterparty_username,
        price_amount=str(order.price_amount),
        price_currency=order.price_currency.value,
        created_at=order.created_at,
        updated_at=order.updated_at,
        delivery_status=_status_value(row[9]),
        delivery_verified_at=row[10],
    )


@router.get("/overview", response_model=AdminOverviewDTO)
async def get_admin_overview(
    admin: AdminUser,
    session: DbSession,
) -> AdminOverviewDTO:
    del admin
    now = datetime.now(UTC)
    since_24h = now - timedelta(hours=24)
    since_7d = now - timedelta(days=7)

    user_counts = (
        await session.execute(
            select(
                func.count(User.id),
                func.count(case((User.is_blocked.is_(True), 1))),
                func.count(case((User.created_at >= since_24h, 1))),
                func.count(case((User.created_at >= since_7d, 1))),
            )
        )
    ).one()
    listing_rows = (
        await session.execute(
            select(Listing.status, func.count(Listing.id)).group_by(Listing.status)
        )
    ).all()
    listing_counts = {
        _status_value(listing_status): int(count)
        for listing_status, count in listing_rows
    }
    order_rows = (
        await session.execute(
            select(Order.status, func.count(Order.id)).group_by(Order.status)
        )
    ).all()
    order_counts = {
        _status_value(order_status): int(count) for order_status, count in order_rows
    }

    recent_user_rows = await session.execute(
        _summary_select()
        .order_by(User.created_at.desc(), User.id.asc())
        .limit(8)
    )
    registrations = [_summary_from_row(row) for row in recent_user_rows.all()]

    events: list[AdminPlatformEventDTO] = []
    recent_order_events = await session.execute(
        select(
            OrderEvent.id,
            OrderEvent.order_id,
            OrderEvent.from_status,
            OrderEvent.to_status,
            OrderEvent.created_at,
        )
        .order_by(OrderEvent.created_at.desc(), OrderEvent.id.desc())
        .limit(8)
    )
    for event_id, order_id, from_status, to_status, occurred_at in recent_order_events.all():
        previous = _status_value(from_status) or "—"
        current = _status_value(to_status) or "unknown"
        events.append(
            AdminPlatformEventDTO(
                id=event_id,
                entity_type="order",
                entity_id=order_id,
                summary=f"Статус сделки: {previous} → {current}",
                occurred_at=occurred_at,
            )
        )

    recent_listing_audit = await session.execute(
        select(
            ModerationAuditLog.id,
            ModerationAuditLog.target_id,
            ModerationAuditLog.action,
            ModerationAuditLog.occurred_at,
        )
        .order_by(ModerationAuditLog.occurred_at.desc(), ModerationAuditLog.id.desc())
        .limit(8)
    )
    for event_id, listing_id, action, occurred_at in recent_listing_audit.all():
        events.append(
            AdminPlatformEventDTO(
                id=event_id,
                entity_type="listing_moderation",
                entity_id=listing_id,
                summary=f"Модерация объявления: {action}",
                occurred_at=occurred_at,
            )
        )

    recent_user_audit = await session.execute(
        select(
            AdminUserAuditLog.id,
            AdminUserAuditLog.target_user_id,
            AdminUserAuditLog.action,
            AdminUserAuditLog.occurred_at,
        )
        .order_by(AdminUserAuditLog.occurred_at.desc(), AdminUserAuditLog.id.desc())
        .limit(8)
    )
    for event_id, user_id, action, occurred_at in recent_user_audit.all():
        label = "пользователь заблокирован" if action == "blocked" else "пользователь разблокирован"
        events.append(
            AdminPlatformEventDTO(
                id=event_id,
                entity_type="user_access",
                entity_id=user_id,
                summary=label,
                occurred_at=occurred_at,
            )
        )

    events.sort(key=lambda item: (item.occurred_at, str(item.id)), reverse=True)
    total_users, blocked_users, new_24h, new_7d = (int(value or 0) for value in user_counts)
    total_listings = sum(listing_counts.values())
    total_orders = sum(order_counts.values())
    completed = order_counts.get(OrderStatus.COMPLETED.value, 0)
    in_progress = sum(
        order_counts.get(state.value, 0)
        for state in (
            OrderStatus.RESERVED,
            OrderStatus.AWAITING_TRANSFER,
            OrderStatus.OBSERVING_TRANSFER,
        )
    )
    return AdminOverviewDTO(
        counts=AdminOverviewCountsDTO(
            total_users=total_users,
            new_users_24h=new_24h,
            new_users_7d=new_7d,
            blocked_users=blocked_users,
            unblocked_users=max(0, total_users - blocked_users),
            total_listings=total_listings,
            active_listings=listing_counts.get(ListingStatus.ACTIVE.value, 0),
            listings_on_moderation=listing_counts.get(ListingStatus.PENDING_REVIEW.value, 0),
            reserved_listings=listing_counts.get(ListingStatus.RESERVED.value, 0),
            completed_deals=completed,
            deals_in_progress=in_progress,
        ),
        recent_registrations=registrations,
        recent_platform_events=sorted(
            events,
            key=lambda item: (item.occurred_at, str(item.id)),
            reverse=True,
        )[:10],
    )


@router.get("/users", response_model=AdminUserPageDTO)
async def list_admin_users(
    admin: AdminUser,
    session: DbSession,
    q: SearchQuery = None,
    blocked: bool | None = None,
    sort_by: AdminUserSort = "registered_at",
    sort_order: SortOrder = "desc",
    limit: PageLimit = 25,
    offset: PageOffset = 0,
) -> AdminUserPageDTO:
    del admin
    statement = _summary_select()
    count_statement = select(func.count(User.id))
    if blocked is not None:
        criterion = User.is_blocked.is_(blocked)
        statement = statement.where(criterion)
        count_statement = count_statement.where(criterion)

    if q is not None:
        query = q.strip()
        username_query = query[1:] if query.startswith("@") else query
        criterion = or_(
            User.username.ilike(f"%{username_query}%", autoescape=True),
            cast(User.telegram_id, String).like(f"%{username_query}%", autoescape=True),
        )
        statement = statement.where(criterion)
        count_statement = count_statement.where(criterion)

    sort_expressions = {
        "registered_at": User.created_at,
        "listings": _listing_count_expr(),
        "deals": _deal_count_expr(),
    }
    primary_sort = sort_expressions[sort_by]
    order_by = primary_sort.desc() if sort_order == "desc" else primary_sort.asc()
    rows = await session.execute(
        statement.order_by(order_by, User.id.asc()).limit(limit).offset(offset)
    )
    total = int(await session.scalar(count_statement) or 0)
    return AdminUserPageDTO(
        items=[_summary_from_row(row) for row in rows.all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}", response_model=AdminUserDetailDTO)
async def get_admin_user(
    user_id: UUID,
    admin: AdminUser,
    session: DbSession,
) -> AdminUserDetailDTO:
    del admin
    summary = await _find_user_summary(session, user_id)
    if summary is None:
        raise HTTPException(status_code=404, detail="User not found")

    wallets = await session.execute(
        select(Wallet.address, Wallet.network, Wallet.is_primary, Wallet.created_at)
        .where(Wallet.user_id == user_id, Wallet.is_verified.is_(True))
        .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
        .limit(100)
    )
    return AdminUserDetailDTO(
        **summary.model_dump(),
        verified_wallets=[
            VerifiedWalletDTO(
                address_short=_shorten_address(address),
                network=network,
                is_primary=is_primary,
            )
            for address, network, is_primary, _created_at in wallets.all()
        ],
    )


@router.get("/users/{user_id}/listings", response_model=AdminUserListingsPageDTO)
async def get_admin_user_listings(
    user_id: UUID,
    admin: AdminUser,
    session: DbSession,
    limit: PageLimit = 25,
    offset: PageOffset = 0,
) -> AdminUserListingsPageDTO:
    del admin
    if await session.scalar(select(User.id).where(User.id == user_id)) is None:
        raise HTTPException(status_code=404, detail="User not found")
    statement = (
        select(Listing, NFTAsset.name)
        .join(NFTAsset, NFTAsset.id == Listing.asset_id)
        .where(Listing.seller_id == user_id)
        .order_by(Listing.created_at.desc(), Listing.id.asc())
    )
    rows = await session.execute(statement.limit(limit).offset(offset))
    total = int(
        await session.scalar(select(func.count(Listing.id)).where(Listing.seller_id == user_id))
        or 0
    )
    return AdminUserListingsPageDTO(
        items=[
            AdminUserListingDTO(
                id=listing.id,
                status=listing.status.value,
                title=listing.title,
                asset_name=asset_name,
                price_amount=str(listing.price_amount),
                price_currency=listing.price_currency.value,
                created_at=listing.created_at,
                updated_at=listing.updated_at,
                expires_at=listing.expires_at,
            )
            for listing, asset_name in rows.all()
        ],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}/orders", response_model=AdminUserOrdersPageDTO)
async def get_admin_user_orders(
    user_id: UUID,
    admin: AdminUser,
    session: DbSession,
    limit: PageLimit = 25,
    offset: PageOffset = 0,
) -> AdminUserOrdersPageDTO:
    del admin
    if await session.scalar(select(User.id).where(User.id == user_id)) is None:
        raise HTTPException(status_code=404, detail="User not found")
    statement = _base_orders_select().where(
        or_(Order.buyer_id == user_id, Order.seller_id == user_id)
    )
    rows = await session.execute(
        statement.order_by(Order.created_at.desc(), Order.id.asc()).limit(limit).offset(offset)
    )
    total = int(
        await session.scalar(
            select(func.count(Order.id)).where(
                or_(Order.buyer_id == user_id, Order.seller_id == user_id)
            )
        )
        or 0
    )
    return AdminUserOrdersPageDTO(
        items=[_user_order_dto(row, user_id) for row in rows.all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/users/{user_id}/audit", response_model=AdminUserAuditPageDTO)
async def get_admin_user_audit(
    user_id: UUID,
    admin: AdminUser,
    session: DbSession,
    limit: PageLimit = 25,
    offset: PageOffset = 0,
) -> AdminUserAuditPageDTO:
    del admin
    if await session.scalar(select(User.id).where(User.id == user_id)) is None:
        raise HTTPException(status_code=404, detail="User not found")
    rows = await session.scalars(
        select(AdminUserAuditLog)
        .where(AdminUserAuditLog.target_user_id == user_id)
        .order_by(AdminUserAuditLog.occurred_at.desc(), AdminUserAuditLog.id.desc())
        .limit(limit)
        .offset(offset)
    )
    total = int(
        await session.scalar(
            select(func.count(AdminUserAuditLog.id)).where(
                AdminUserAuditLog.target_user_id == user_id
            )
        )
        or 0
    )
    return AdminUserAuditPageDTO(
        items=[AdminUserAuditDTO.model_validate(row) for row in rows.all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/orders", response_model=AdminOrderPageDTO)
async def list_admin_orders(
    admin: AdminUser,
    session: DbSession,
    status_filter: Annotated[OrderStatus | None, Query(alias="status")] = None,
    q: OrderSearchQuery = None,
    limit: PageLimit = 25,
    offset: PageOffset = 0,
) -> AdminOrderPageDTO:
    del admin
    statement = _base_orders_select()
    count_statement = select(func.count(Order.id))
    if status_filter is not None:
        statement = statement.where(Order.status == status_filter)
        count_statement = count_statement.where(Order.status == status_filter)
    if q is not None:
        try:
            order_id = UUID(q)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail="Search must be a valid order UUID") from exc
        statement = statement.where(Order.id == order_id)
        count_statement = count_statement.where(Order.id == order_id)

    rows = await session.execute(
        statement.order_by(Order.created_at.desc(), Order.id.asc()).limit(limit).offset(offset)
    )
    total = int(await session.scalar(count_statement) or 0)
    items: list[AdminOrderDTO] = []
    for row in rows.all():
        order = row[0]
        items.append(
            AdminOrderDTO(
                id=order.id,
                listing_id=order.listing_id,
                listing_title=row[1],
                asset_name=row[2],
                buyer_id=order.buyer_id,
                buyer_name=_display_name(row[3], row[4]),
                buyer_username=row[5],
                seller_id=order.seller_id,
                seller_name=_display_name(row[6], row[7]),
                seller_username=row[8],
                price_amount=str(order.price_amount),
                price_currency=order.price_currency.value,
                status=order.status.value,
                created_at=order.created_at,
                updated_at=order.updated_at,
                delivery_status=_status_value(row[9]),
                delivery_verified_at=row[10],
            )
        )
    return AdminOrderPageDTO(items=items, total=total, limit=limit, offset=offset)


def _user_audit_dto(row: AdminUserAuditLog) -> AdminUserAuditDTO:
    return AdminUserAuditDTO.model_validate(row)


def _check_user_idempotency(
    row: AdminUserAuditLog,
    *,
    target_user_id: UUID,
    action: Literal["blocked", "unblocked"],
    reason: str,
) -> AdminUserAccessDecisionResponse:
    if (
        row.target_user_id != target_user_id
        or row.action != action
        or row.reason != reason
    ):
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used for a different user access decision",
        )
    blocked_after = bool(row.after_snapshot.get("is_blocked", False))
    return AdminUserAccessDecisionResponse(
        user_id=target_user_id,
        is_blocked=blocked_after,
        audit=_user_audit_dto(row),
    )


async def _change_user_access(
    user_id: UUID,
    payload: AdminUserAccessDecisionRequest,
    request: Request,
    admin: User,
    session: AsyncSession,
    idempotency_key: str,
    *,
    should_block: bool,
) -> AdminUserAccessDecisionResponse:
    action: Literal["blocked", "unblocked"] = "blocked" if should_block else "unblocked"
    existing = await session.scalar(
        select(AdminUserAuditLog).where(
            AdminUserAuditLog.actor_id == admin.id,
            AdminUserAuditLog.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return _check_user_idempotency(
            existing, target_user_id=user_id, action=action, reason=payload.reason
        )
    await session.rollback()

    request_id = request.headers.get("X-Request-ID")
    if request_id and (
        len(request_id) > 100 or any(ord(char) < 33 or ord(char) > 126 for char in request_id)
    ):
        request_id = None

    settings = get_settings()
    try:
        async with session.begin():
            target = await session.scalar(
                select(User).where(User.id == user_id).with_for_update()
            )
            if target is None:
                raise HTTPException(status_code=404, detail="User not found")
            if target.id == admin.id:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Administrators cannot change their own account access",
                )
            if target.telegram_id in settings.admin_telegram_ids:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Administrator accounts cannot be blocked or modified here",
                )
            if target.is_blocked is should_block:
                current = "blocked" if should_block else "unblocked"
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail=f"User is already {current}",
                )
            before = {"is_blocked": bool(target.is_blocked)}
            target.is_blocked = should_block
            after = {"is_blocked": should_block}
            audit = AdminUserAuditLog(
                actor_id=admin.id,
                target_user_id=target.id,
                action=action,
                reason=payload.reason,
                before_snapshot=before,
                after_snapshot=after,
                request_id=request_id,
                idempotency_key=idempotency_key,
            )
            session.add(audit)
        await session.refresh(audit)
        return AdminUserAccessDecisionResponse(
            user_id=user_id,
            is_blocked=should_block,
            audit=_user_audit_dto(audit),
        )
    except IntegrityError as exc:
        await session.rollback()
        replay = await session.scalar(
            select(AdminUserAuditLog).where(
                AdminUserAuditLog.actor_id == admin.id,
                AdminUserAuditLog.idempotency_key == idempotency_key,
            )
        )
        if replay is not None:
            return _check_user_idempotency(
                replay, target_user_id=user_id, action=action, reason=payload.reason
            )
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Concurrent user access change; refresh and retry with a new Idempotency-Key",
        ) from exc


@router.post("/users/{user_id}/block", response_model=AdminUserAccessDecisionResponse)
async def block_admin_user(
    user_id: UUID,
    payload: AdminUserAccessDecisionRequest,
    request: Request,
    admin: AdminUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> AdminUserAccessDecisionResponse:
    return await _change_user_access(
        user_id,
        payload,
        request,
        admin,
        session,
        idempotency_key,
        should_block=True,
    )


@router.post("/users/{user_id}/unblock", response_model=AdminUserAccessDecisionResponse)
async def unblock_admin_user(
    user_id: UUID,
    payload: AdminUserAccessDecisionRequest,
    request: Request,
    admin: AdminUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> AdminUserAccessDecisionResponse:
    return await _change_user_access(
        user_id,
        payload,
        request,
        admin,
        session,
        idempotency_key,
        should_block=False,
    )
