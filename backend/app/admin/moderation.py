from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, Request
from pydantic import BaseModel, ConfigDict, Field, field_validator
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.dependencies import get_ton_nft_verifier
from app.assets.ton_nft.models import VerificationStatus
from app.assets.ton_nft.verifier import TONNFTVerifier
from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    ModerationAuditLog,
    NFTAsset,
    User,
    Wallet,
)
from app.db.session import get_db_session

router = APIRouter(prefix="/admin", tags=["admin moderation"])

ReasonCode = Literal[
    "policy_violation",
    "ownership_unverified",
    "misleading_metadata",
    "duplicate_listing",
    "other",
]
Action = Literal["approve", "reject", "suspend", "restore"]


def _is_admin(user: User) -> bool:
    # The user comes from a verified bearer session and a DB lookup. The
    # configured allowlist assigns the role server-side; clients cannot supply it.
    return bool(get_settings().admin_telegram_ids) and (
        user.telegram_id in get_settings().admin_telegram_ids
    )


async def require_admin(
    user: Annotated[User, Depends(get_current_user)],
) -> User:
    if not _is_admin(user):
        raise HTTPException(status_code=403, detail="Administrator access required")
    return user


class DecisionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Action
    reason_code: ReasonCode
    reason: str = Field(min_length=5, max_length=500)

    @field_validator("reason")
    @classmethod
    def normalize_reason(cls, value: str) -> str:
        normalized = value.strip()
        if len(normalized) < 5:
            raise ValueError("Reason must contain at least five non-whitespace characters")
        return normalized


class ListingSellerDTO(BaseModel):
    id: UUID
    username: str | None
    first_name: str


class ListingAssetDTO(BaseModel):
    name: str | None
    image_url: str | None
    verification_status: AssetVerificationStatus


class ModerationItemDTO(BaseModel):
    id: UUID
    status: ListingStatus
    title: str | None
    price_amount: str
    price_currency: str
    created_at: datetime
    expires_at: datetime | None
    seller: ListingSellerDTO
    asset: ListingAssetDTO
    queue_reasons: list[str]


class ModerationPageDTO(BaseModel):
    items: list[ModerationItemDTO]
    total: int
    limit: int
    offset: int


class AuditDTO(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    actor_id: UUID
    target_type: str
    target_id: UUID
    action: str
    reason_code: str
    reason: str
    before_snapshot: dict[str, object]
    after_snapshot: dict[str, object]
    request_id: str | None
    idempotency_key: str
    occurred_at: datetime


class AuditPageDTO(BaseModel):
    items: list[AuditDTO]
    total: int
    limit: int
    offset: int


def _queue_reasons(listing: Listing, now: datetime) -> list[str]:
    reasons: list[str] = []
    if listing.status is ListingStatus.DRAFT:
        reasons.append("draft_pending_review")
    if listing.status is ListingStatus.SUSPENDED:
        reasons.append("moderator_suspended")
    if listing.status is ListingStatus.ACTIVE:
        reasons.append("active_listing_review")
    if listing.asset.verification_status is not AssetVerificationStatus.VERIFIED:
        reasons.append("asset_not_verified")
    if listing.asset.owner_id != listing.seller_id:
        reasons.append("asset_owner_mismatch")
    if listing.expires_at is not None and listing.expires_at <= now:
        reasons.append("listing_expired")
    return reasons


def _snapshot(listing: Listing) -> dict[str, object]:
    # Deliberately exclude Telegram IDs, wallet/item addresses, secrets,
    # provider payloads, private metadata and seller profile details.
    return {
        "listing_id": str(listing.id),
        "status": listing.status.value,
        "title": listing.title,
        "price_amount": str(listing.price_amount),
        "price_currency": listing.price_currency.value,
        "seller_id": str(listing.seller_id),
        "asset_verification_status": listing.asset.verification_status.value,
        "asset_owner_matches_seller": listing.asset.owner_id == listing.seller_id,
    }


def _audit_dto(row: ModerationAuditLog) -> AuditDTO:
    return AuditDTO.model_validate(row)


def _check_idempotent(
    row: ModerationAuditLog,
    *,
    target_id: UUID,
    action: Action,
    reason_code: str,
    reason: str,
) -> AuditDTO:
    if (
        row.target_id != target_id
        or row.action != {"approve": "approved", "reject": "rejected",
                          "suspend": "suspended", "restore": "restored"}[action]
        or row.reason_code != reason_code
        or row.reason != reason
    ):
        raise HTTPException(
            status_code=409,
            detail="Idempotency-Key was already used for a different moderation decision",
        )
    return _audit_dto(row)


async def _verify_ownership(
    session: AsyncSession,
    listing_id: UUID,
    expected_status: ListingStatus,
    verifier: TONNFTVerifier,
) -> dict[str, object]:
    listing = await session.scalar(
        select(Listing).options(selectinload(Listing.asset)).where(Listing.id == listing_id)
    )
    if listing is None:
        raise HTTPException(status_code=404, detail="Listing not found")
    if listing.status is not expected_status:
        raise HTTPException(status_code=409, detail="Listing status changed; refresh the queue")
    if listing.expires_at is not None and listing.expires_at <= datetime.now(UTC):
        raise HTTPException(
            status_code=409,
            detail="Expired listings cannot be approved or restored",
        )
    asset = listing.asset
    if (
        asset.asset_type is not AssetType.TON_NFT
        or asset.owner_id != listing.seller_id
        or asset.verification_status is not AssetVerificationStatus.VERIFIED
        or asset.network != get_settings().ton_connect_network
        or not asset.item_address
    ):
        raise HTTPException(status_code=409, detail="Current verified NFT ownership is required")
    wallet_rows = await session.scalars(
        select(Wallet)
        .where(
            Wallet.user_id == listing.seller_id,
            Wallet.is_verified.is_(True),
            Wallet.network == asset.network,
        )
        .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
    )
    wallets = [(w.id, w.address, w.network) for w in wallet_rows.all()]
    snapshot: dict[str, object] = {
        "listing_id": listing.id,
        "seller_id": listing.seller_id,
        "asset_id": asset.id,
        "item_address": asset.item_address,
        "asset_external_id": asset.external_id,
        "asset_network": asset.network,
        "expected_status": expected_status,
    }
    await session.rollback()
    if not wallets:
        raise HTTPException(status_code=409, detail="A verified seller wallet is required")
    for wallet_id, wallet_address, wallet_network in wallets:
        if wallet_network != snapshot["asset_network"]:
            continue
        result = await verifier.verify(str(snapshot["item_address"]), wallet_address)
        if result.status is VerificationStatus.PROVIDER_UNAVAILABLE:
            raise HTTPException(status_code=503, detail="Ownership provider is unavailable")
        if not result.is_verified:
            continue
        try:
            item = normalize_address(result.item_address)
            owner = normalize_address(result.owner_address or "")
            expected_owner = normalize_address(result.expected_owner_address or "")
            expected_item = normalize_address(str(snapshot["item_address"]))
            expected_wallet = normalize_address(wallet_address)
        except AddressError:
            continue
        if item == expected_item and owner == expected_wallet and expected_owner == expected_wallet:
            snapshot["verified_wallet_id"] = wallet_id
            snapshot["verified_wallet_address"] = wallet_address
            return snapshot
    raise HTTPException(status_code=409, detail="Fresh NFT ownership could not be verified")


@router.get("/access")
async def get_admin_access(
    user: Annotated[User, Depends(get_current_user)],
) -> dict[str, bool]:
    return {"is_admin": _is_admin(user)}


@router.get("/moderation", response_model=ModerationPageDTO)
async def get_moderation_queue(
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    status_filter: Annotated[ListingStatus | None, Query(alias="status")] = None,
) -> ModerationPageDTO:
    now = datetime.now(UTC)
    statement = (
        select(Listing)
        .options(selectinload(Listing.asset), selectinload(Listing.seller))
        .where(
            Listing.status.in_(
                [ListingStatus.DRAFT, ListingStatus.ACTIVE, ListingStatus.SUSPENDED]
            )
        )
    )
    if status_filter is not None:
        statement = statement.where(Listing.status == status_filter)
    rows = await session.scalars(
        statement.order_by(Listing.updated_at.desc(), Listing.id.asc()).limit(limit).offset(offset)
    )
    all_rows = list(rows.unique().all())
    # The queue is deliberately limited to operationally actionable statuses.
    items = [
        ModerationItemDTO(
            id=row.id,
            status=row.status,
            title=row.title,
            price_amount=str(row.price_amount),
            price_currency=row.price_currency.value,
            created_at=row.created_at,
            expires_at=row.expires_at,
            seller=ListingSellerDTO(
                id=row.seller.id, username=row.seller.username, first_name=row.seller.first_name
            ),
            asset=ListingAssetDTO(
                name=row.asset.name,
                image_url=row.asset.image_url,
                verification_status=row.asset.verification_status,
            ),
            queue_reasons=_queue_reasons(row, now),
        )
        for row in all_rows
    ]
    # Count respects the same status filter and actionability scope.
    count_statement = select(func.count(Listing.id)).where(
        Listing.status.in_([ListingStatus.DRAFT, ListingStatus.ACTIVE, ListingStatus.SUSPENDED]),
        *([Listing.status == status_filter] if status_filter is not None else []),
    )
    total = await session.scalar(count_statement) or 0
    return ModerationPageDTO(items=items, total=total, limit=limit, offset=offset)


async def _read_audit_page(
    session: AsyncSession,
    *,
    limit: int,
    offset: int,
    target_id: UUID | None,
    action: str | None,
) -> AuditPageDTO:
    statement = select(ModerationAuditLog)
    count_statement = select(ModerationAuditLog.id)
    if target_id is not None:
        statement = statement.where(ModerationAuditLog.target_id == target_id)
        count_statement = count_statement.where(ModerationAuditLog.target_id == target_id)
    if action is not None:
        statement = statement.where(ModerationAuditLog.action == action)
        count_statement = count_statement.where(ModerationAuditLog.action == action)
    rows = await session.scalars(
        statement.order_by(ModerationAuditLog.occurred_at.desc(), ModerationAuditLog.id.desc())
        .limit(limit).offset(offset)
    )
    total = await session.scalar(select(func.count()).select_from(count_statement.subquery())) or 0
    return AuditPageDTO(
        items=[_audit_dto(row) for row in rows.all()],
        total=total,
        limit=limit,
        offset=offset,
    )


@router.get("/audit", response_model=AuditPageDTO)
async def get_audit_log(
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
    target_id: UUID | None = None,
    action: Annotated[str | None, Query(pattern="^(approved|rejected|suspended|restored)$")] = None,
) -> AuditPageDTO:
    return await _read_audit_page(
        session, limit=limit, offset=offset, target_id=target_id, action=action
    )


@router.get("/listings/{listing_id}/audit", response_model=AuditPageDTO)
async def get_listing_audit(
    listing_id: UUID,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    limit: Annotated[int, Query(ge=1, le=100)] = 25,
    offset: Annotated[int, Query(ge=0, le=10000)] = 0,
) -> AuditPageDTO:
    return await _read_audit_page(
        session, limit=limit, offset=offset, target_id=listing_id, action=None
    )


@router.post("/listings/{listing_id}/decision", response_model=AuditDTO)
async def decide_listing(
    listing_id: UUID,
    payload: DecisionRequest,
    request: Request,
    admin: Annotated[User, Depends(require_admin)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)],
    verifier: Annotated[TONNFTVerifier, Depends(get_ton_nft_verifier)],
) -> AuditDTO:
    action_map = {
        "approve": ("approved", ListingStatus.DRAFT, ListingStatus.ACTIVE),
        "reject": ("rejected", ListingStatus.DRAFT, ListingStatus.CANCELLED),
        "suspend": ("suspended", ListingStatus.ACTIVE, ListingStatus.SUSPENDED),
        "restore": ("restored", ListingStatus.SUSPENDED, ListingStatus.ACTIVE),
    }
    audit_action, expected_status, target_status = action_map[payload.action]
    existing = await session.scalar(
        select(ModerationAuditLog).where(
            ModerationAuditLog.actor_id == admin.id,
            ModerationAuditLog.idempotency_key == idempotency_key,
        )
    )
    if existing is not None:
        return _check_idempotent(
            existing, target_id=listing_id, action=payload.action,
            reason_code=payload.reason_code, reason=payload.reason,
        )

    await session.rollback()
    verified: dict[str, object] | None = None
    if payload.action in {"approve", "restore"}:
        verified = await _verify_ownership(session, listing_id, expected_status, verifier)

    request_id = request.headers.get("X-Request-ID")
    if request_id and (
        len(request_id) > 100 or any(ord(char) < 33 or ord(char) > 126 for char in request_id)
    ):
        request_id = None

    try:
        async with session.begin():
            listing = await session.scalar(
                select(Listing)
                .options(selectinload(Listing.asset))
                .where(Listing.id == listing_id)
                .with_for_update()
            )
            if listing is None:
                raise HTTPException(status_code=404, detail="Listing not found")
            # Serialize duplicate/replayed requests on the listing row, then
            # re-check idempotency after any concurrent decision has committed.
            existing = await session.scalar(
                select(ModerationAuditLog).where(
                    ModerationAuditLog.actor_id == admin.id,
                    ModerationAuditLog.idempotency_key == idempotency_key,
                )
            )
            if existing is not None:
                return _check_idempotent(
                    existing, target_id=listing_id, action=payload.action,
                    reason_code=payload.reason_code, reason=payload.reason,
                )
            if listing.status is not expected_status:
                raise HTTPException(
                    status_code=409,
                    detail=f"Action requires listing status '{expected_status.value}'",
                )
            before = _snapshot(listing)
            if verified is not None:
                asset = await session.scalar(
                    select(NFTAsset).where(NFTAsset.id == listing.asset_id).with_for_update()
                )
                wallet = await session.scalar(
                    select(Wallet)
                    .where(Wallet.id == verified["verified_wallet_id"])
                    .with_for_update()
                )
                if (
                    asset is None or wallet is None
                    or listing.id != verified["listing_id"]
                    or listing.seller_id != verified["seller_id"]
                    or asset.id != verified["asset_id"]
                    or asset.item_address != verified["item_address"]
                    or asset.external_id != verified["asset_external_id"]
                    or asset.network != verified["asset_network"]
                    or asset.owner_id != listing.seller_id
                    or asset.verification_status is not AssetVerificationStatus.VERIFIED
                    or wallet.user_id != listing.seller_id
                    or wallet.address != verified["verified_wallet_address"]
                    or not wallet.is_verified
                    or wallet.network != asset.network
                    or (listing.expires_at is not None and listing.expires_at <= datetime.now(UTC))
                ):
                    raise HTTPException(
                        status_code=409,
                        detail="Listing ownership changed during verification",
                    )
                conflicting = await session.scalar(
                    select(Listing.id).where(
                        Listing.asset_id == listing.asset_id,
                        Listing.id != listing.id,
                        Listing.status.in_([ListingStatus.ACTIVE, ListingStatus.RESERVED]),
                    ).limit(1)
                )
                if conflicting is not None:
                    raise HTTPException(
                        status_code=409,
                        detail="Another active or reserved listing exists for this NFT",
                    )
                asset.verified_at = datetime.now(UTC)
            listing.status = target_status
            after = _snapshot(listing)
            row = ModerationAuditLog(
                actor_id=admin.id,
                target_type="listing",
                target_id=listing.id,
                action=audit_action,
                reason_code=payload.reason_code,
                reason=payload.reason.strip(),
                before_snapshot=before,
                after_snapshot=after,
                request_id=request_id,
                idempotency_key=idempotency_key,
            )
            session.add(row)
            await session.flush()
            await session.refresh(row)
            return _audit_dto(row)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail="Duplicate moderation request") from exc
