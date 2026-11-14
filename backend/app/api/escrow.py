"""Isolated escrow API. Not mounted until integration scope is approved in main.py."""

from __future__ import annotations

import hashlib
import json
import secrets
from decimal import Decimal
from datetime import datetime
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

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
    NFTAsset,
    NFTCollection,
    PriceCurrency,
    User,
    Wallet,
)
from app.db.session import get_db_session
from app.escrow.contracts import (
    EscrowContractABIUnavailable, EscrowWalletAction, UnconfiguredTONEscrowContractAdapter,
)
from app.escrow.domain import EscrowChainEventType, EscrowDealStatus
from app.escrow.models import (
    EscrowChainEvent,
    EscrowDeal,
    EscrowDispute,
    EscrowIdempotencyRecord,
    EscrowListingIntent,
    EscrowWithdrawal,
)
from app.escrow.schemas import (
    EscrowDealCreate,
    EscrowDealResponse,
    EscrowDisputeCreate,
    EscrowDisputeResponse,
    EscrowListingIntentCreate,
    EscrowListingIntentResponse, EscrowNftProjection, EscrowPageResponse,
    EscrowSellerBalanceResponse,
    EscrowTransactionPreparationResponse,
    EscrowWithdrawalCreate,
    EscrowWithdrawalResponse,
    EscrowWalletReferenceInput,
)
def _listing_key(intent: EscrowListingIntent | None) -> str | None:
    return None


def _ton_nano(value: Decimal) -> str:
    amount = value * _NANOTON
    if amount <= 0 or amount != amount.to_integral_value():
        raise HTTPException(status_code=409, detail="TON principal precision is invalid")
    return str(int(amount))


def _listing_actions(intent: EscrowListingIntent) -> list[str]:
    return ["create_deal_intent"] if intent.status in {"intent_only", "active"} else []


def _deal_actions(deal: EscrowDeal, actor_id: UUID) -> list[str]:
    if actor_id == deal.seller_id:
        if deal.status == "intent_created":
            return ["create_deal_escrow"]
        if deal.status == "awaiting_nft":
            return ["deposit_nft"]
        if deal.status == "expired":
            return ["withdraw_unsold_nft"]
        return []
    if actor_id == deal.buyer_id:
        if deal.status == "awaiting_buyer_funds":
            return ["fund_deal"]
        if deal.status == "funded_review":
            return ["accept_deal", "open_dispute"]
        if deal.status == "delivered_dispute_window":
            return ["open_dispute"]
        if deal.status == "disputed":
            return ["return_nft_to_escrow"]
    return []


async def _listing_projection(session: AsyncSession, intent: EscrowListingIntent) -> EscrowListingIntentResponse:
    asset = await session.get(NFTAsset, intent.asset_id)
    return EscrowListingIntentResponse(
        id=intent.marketplace_listing_id, listing_key=intent.listing_key, seller_id=intent.seller_id,
        state=intent.status, network="testnet",
        nft=EscrowNftProjection(
            asset_id=intent.asset_id,
            title=asset.name if asset and asset.name else "TON NFT",
            image_url=asset.image_url if asset else None, item_address=intent.item_address,
            collection_address=intent.collection_address_snapshot,
        ),
        seller_wallet_address=intent.seller_address_snapshot,
        price_nano=_ton_nano(intent.price_amount), available_actions=_listing_actions(intent),
        created_at=intent.created_at, updated_at=intent.updated_at,
    )


async def _deal_projection(session: AsyncSession, deal: EscrowDeal, actor_id: UUID) -> EscrowDealResponse:
    intent = await session.get(EscrowListingIntent, deal.listing_intent_id)
    asset = await session.get(NFTAsset, intent.asset_id) if intent else None
    dispute = await session.scalar(select(EscrowDispute).where(EscrowDispute.deal_id == deal.id))
    return EscrowDealResponse(
        id=deal.id, listing_id=deal.marketplace_listing_id, listing_key=intent.listing_key if intent else "",
        buyer_id=deal.buyer_id, seller_id=deal.seller_id, state=deal.status, network="testnet",
        nft=EscrowNftProjection(
            asset_id=intent.asset_id if intent else None,
            title=asset.name if asset and asset.name else "TON NFT",
            image_url=asset.image_url if asset else None, item_address=deal.item_address,
            collection_address=deal.collection_address_snapshot,
        ),
        escrow_address=deal.contract_address, seller_wallet_address=deal.seller_address_snapshot,
        buyer_wallet_address=deal.buyer_address_snapshot, price_nano=str(int(deal.principal_nanotons)),
        buyer_review_deadline=None, dispute_deadline=None, available_actions=_deal_actions(deal, actor_id),
        created_at=deal.created_at, updated_at=deal.updated_at,
        dispute=({
            "id": str(dispute.id), "status": dispute.status, "reason_code": dispute.reason_code,
            "summary": dispute.reason, "opened_at": dispute.created_at.isoformat(),
            "resolved_at": dispute.resolved_at.isoformat() if dispute.resolved_at else None,
            "resolution_note": None,
        } if dispute else None),
    )



router = APIRouter(prefix="/escrow", tags=["ton-escrow"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Verifier = Annotated[TONNFTVerifier, Depends(get_ton_nft_verifier)]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]

_NANOTON = Decimal(1_000_000_000)
_contract_adapter = UnconfiguredTONEscrowContractAdapter()


def _request_hash(payload: object) -> str:
    raw = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _payload_dict(model: object) -> dict[str, object]:
    return model.model_dump(mode="json")  # type: ignore[attr-defined,no-any-return]


async def _load_idempotent_resource(
    session: AsyncSession,
    *,
    actor_id: UUID,
    operation: str,
    key: str,
    request_sha256: str,
    model: type[object],
) -> object | None:
    record = await session.scalar(
        select(EscrowIdempotencyRecord).where(
            EscrowIdempotencyRecord.actor_id == actor_id,
            EscrowIdempotencyRecord.operation == operation,
            EscrowIdempotencyRecord.idempotency_key == key,
        )
    )
    if record is None:
        return None
    if record.request_sha256 != request_sha256:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency-Key was already used with a different request",
        )
    if record.resource_id is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="An operation with this Idempotency-Key is still being resolved",
        )
    resource = await session.get(model, record.resource_id)
    if resource is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Idempotency record references a missing resource",
        )
    return resource


def _add_idempotency_record(
    session: AsyncSession,
    *,
    actor_id: UUID,
    operation: str,
    key: str,
    request_sha256: str,
    resource_type: str,
    resource_id: UUID,
) -> None:
    session.add(
        EscrowIdempotencyRecord(
            actor_id=actor_id,
            operation=operation,
            idempotency_key=key,
            request_sha256=request_sha256,
            resource_type=resource_type,
            resource_id=resource_id,
        )
    )


async def _idempotency_race_replay(
    session: AsyncSession,
    *,
    actor_id: UUID,
    operation: str,
    key: str,
    request_sha256: str,
    model: type[object],
) -> object:
    await session.rollback()
    existing = await _load_idempotent_resource(
        session,
        actor_id=actor_id,
        operation=operation,
        key=key,
        request_sha256=request_sha256,
        model=model,
    )
    if existing is not None:
        return existing
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="Concurrent escrow request conflicts with an existing intent",
    )


def _require_testnet() -> None:
    if get_settings().ton_connect_network != "testnet":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "escrow_testnet_only",
                "message": (
                    "Escrow backend is disabled unless TON Connect is configured "
                    "for testnet."
                ),
            },
        )


async def _verified_wallet(
    session: AsyncSession,
    *,
    user_id: UUID,
    wallet_id: UUID,
) -> tuple[Wallet, str]:
    wallet = await session.scalar(
        select(Wallet).where(
            Wallet.id == wallet_id,
            Wallet.user_id == user_id,
            Wallet.is_verified.is_(True),
            Wallet.network == "testnet",
        )
    )
    if wallet is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Verified testnet wallet not found for this account",
        )
    try:
        canonical_address = normalize_address(wallet.address)
    except AddressError as exc:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="Stored wallet address is invalid; re-verify wallet ownership",
        ) from exc
    return wallet, canonical_address


async def _verify_current_nft_owner(
    verifier: TONNFTVerifier,
    *,
    item_address: str,
    seller_address: str,
) -> None:
    if verifier.network != "testnet":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Escrow requires a TON testnet verifier",
        )
    result = await verifier.verify(item_address, seller_address)
    if result.status is VerificationStatus.VERIFIED:
        return
    if result.status is VerificationStatus.PROVIDER_UNAVAILABLE:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TON testnet ownership provider is unavailable; retry later",
        )
    raise HTTPException(
        status_code=status.HTTP_409_CONFLICT,
        detail="NFT ownership or item verification did not match the escrow intent",
    )


@router.post("/listing-intents", response_model=EscrowListingIntentResponse, status_code=201)
async def create_listing_intent(
    payload: EscrowListingIntentCreate, user: CurrentUser, session: DbSession,
    verifier: Verifier, idempotency_key: IdempotencyKey,
) -> EscrowListingIntentResponse:
    """Create a seller intent over a normal draft/active TON marketplace listing."""
    _require_testnet()
    request_hash = _request_hash(_payload_dict(payload))
    try:
        replay = await _load_idempotent_resource(
            session, actor_id=user.id, operation="create_listing_intent", key=idempotency_key,
            request_sha256=request_hash, model=EscrowListingIntent,
        )
        if replay is not None:
            return await _listing_projection(session, replay)

        asset = await session.scalar(select(NFTAsset).where(
            NFTAsset.id == payload.asset_id, NFTAsset.owner_id == user.id,
            NFTAsset.network == "testnet", NFTAsset.asset_type == AssetType.TON_NFT,
            NFTAsset.verification_status == AssetVerificationStatus.VERIFIED,
        ).with_for_update())
        if asset is None or not asset.item_address:
            raise HTTPException(status_code=409, detail="Only verified seller-owned TON testnet NFTs are eligible")
        wallet, seller_address = await _verified_wallet(session, user_id=user.id, wallet_id=payload.seller_wallet_id)
        try:
            item_address = normalize_address(asset.item_address)
        except AddressError as exc:
            raise HTTPException(status_code=409, detail="Stored NFT item address is invalid") from exc
        await _verify_current_nft_owner(verifier, item_address=item_address, seller_address=seller_address)
        collection_address = None
        if asset.collection_id is not None:
            collection = await session.get(NFTCollection, asset.collection_id)
            if collection is not None and collection.network == "testnet":
                try:
                    collection_address = normalize_address(collection.address)
                except AddressError as exc:
                    raise HTTPException(status_code=409, detail="Stored NFT collection address is invalid") from exc

        price_nano = Decimal(payload.price_nano)
        price_amount = price_nano / _NANOTON
        if price_amount <= 0 or price_amount * _NANOTON != price_nano:
            raise HTTPException(status_code=422, detail="price_nano must be a positive integer nanotons")

        listing = await session.scalar(select(Listing).where(
            Listing.asset_id == asset.id, Listing.seller_id == user.id,
            Listing.status.in_((ListingStatus.ACTIVE, ListingStatus.DRAFT)),
        ).order_by(Listing.status.asc()).with_for_update())
        if listing is not None and listing.status is ListingStatus.ACTIVE:
            if listing.price_currency is not PriceCurrency.TON or listing.price_amount != price_amount:
                raise HTTPException(status_code=409, detail="Active listing price/currency must match the escrow intent")
        elif listing is not None:
            listing.price_amount = price_amount
            listing.price_currency = PriceCurrency.TON
            if not listing.title:
                listing.title = asset.name
        else:
            conflict = await session.scalar(select(Listing.id).where(
                Listing.asset_id == asset.id,
                Listing.status.in_((ListingStatus.RESERVED, ListingStatus.PENDING_REVIEW)),
            ))
            if conflict is not None:
                raise HTTPException(status_code=409, detail="NFT already has a reserved or review-pending listing")
            listing = Listing(
                id=uuid4(), asset_id=asset.id, seller_id=user.id, status=ListingStatus.DRAFT,
                price_amount=price_amount, price_currency=PriceCurrency.TON, title=asset.name,
            )
            session.add(listing)
            await session.flush()

        existing_intent = await session.scalar(select(EscrowListingIntent).where(
            EscrowListingIntent.marketplace_listing_id == listing.id,
        ).with_for_update())
        if existing_intent is not None:
            raise HTTPException(status_code=409, detail="An escrow listing intent already exists for this listing")
        intent = EscrowListingIntent(
            id=uuid4(), marketplace_listing_id=listing.id, asset_id=asset.id, seller_id=user.id,
            seller_wallet_id=wallet.id, network="testnet", item_address=item_address,
            listing_key=secrets.token_hex(32), collection_address_snapshot=collection_address,
            seller_address_snapshot=seller_address,
            price_amount=price_amount, price_currency="TON", status="intent_only",
            contract_address=None, contract_abi_version=None, idempotency_key=idempotency_key,
        )
        session.add(intent)
        _add_idempotency_record(session, actor_id=user.id, operation="create_listing_intent",
            key=idempotency_key, request_sha256=request_hash,
            resource_type="listing_intent", resource_id=intent.id)
        await session.commit()
        await session.refresh(intent)
        return await _listing_projection(session, intent)
    except IntegrityError:
        replay = await _idempotency_race_replay(session, actor_id=user.id,
            operation="create_listing_intent", key=idempotency_key,
            request_sha256=request_hash, model=EscrowListingIntent)
        return await _listing_projection(session, replay)
    except HTTPException:
        await session.rollback()
        raise


@router.get("/marketplace/listing-intents", response_model=EscrowPageResponse)
async def discover_listing_intents(user: CurrentUser, session: DbSession, limit: int = 20, offset: int = 0):
    _require_testnet()
    rows = list((await session.scalars(
        select(EscrowListingIntent).join(Listing, Listing.id == EscrowListingIntent.marketplace_listing_id)
        .where(EscrowListingIntent.status.in_(("intent_only", "active")),
               Listing.status == ListingStatus.ACTIVE, EscrowListingIntent.seller_id != user.id)
        .order_by(EscrowListingIntent.created_at.desc(), EscrowListingIntent.id.desc())
        .offset(max(offset, 0)).limit(min(max(limit, 1), 50))
    )).all())
    return EscrowPageResponse(items=[await _listing_projection(session, row) for row in rows], total=len(rows))


@router.get("/listing-intents", response_model=EscrowPageResponse)
async def list_seller_listing_intents(user: CurrentUser, session: DbSession, limit: int = 20, offset: int = 0):
    rows = list((await session.scalars(
        select(EscrowListingIntent).where(EscrowListingIntent.seller_id == user.id)
        .order_by(EscrowListingIntent.created_at.desc(), EscrowListingIntent.id.desc())
        .offset(max(offset, 0)).limit(min(max(limit, 1), 50))
    )).all())
    return EscrowPageResponse(items=[await _listing_projection(session, row) for row in rows], total=len(rows))


@router.get("/listing-intents/{intent_id}", response_model=EscrowListingIntentResponse)
async def get_listing_intent(intent_id: UUID, user: CurrentUser, session: DbSession):
    intent = await session.scalar(select(EscrowListingIntent).where(
        EscrowListingIntent.marketplace_listing_id == intent_id, EscrowListingIntent.seller_id == user.id,
    ))
    if intent is None:
        raise HTTPException(status_code=404, detail="Escrow listing intent not found")
    return await _listing_projection(session, intent)


@router.post("/deals", response_model=EscrowDealResponse, status_code=201)
async def create_deal_intent(payload: EscrowDealCreate, user: CurrentUser, session: DbSession,
    verifier: Verifier, idempotency_key: IdempotencyKey) -> EscrowDealResponse:
    _require_testnet()
    request_hash = _request_hash(_payload_dict(payload))
    try:
        replay = await _load_idempotent_resource(session, actor_id=user.id, operation="create_deal_intent",
            key=idempotency_key, request_sha256=request_hash, model=EscrowDeal)
        if replay is not None:
            if replay.buyer_id != user.id:
                raise HTTPException(status_code=404, detail="Escrow deal not found")
            return await _deal_projection(session, replay, user.id)
        intent = await session.scalar(select(EscrowListingIntent).where(
            EscrowListingIntent.marketplace_listing_id == payload.listing_id).with_for_update())
        if intent is None or intent.status not in {"intent_only", "active"}:
            raise HTTPException(status_code=404, detail="Escrow listing intent not found")
        if intent.seller_id == user.id:
            raise HTTPException(status_code=409, detail="A seller cannot buy their own listing")
        listing = await session.get(Listing, intent.marketplace_listing_id)
        if listing is None or listing.status is not ListingStatus.ACTIVE or listing.asset_id != intent.asset_id:
            raise HTTPException(status_code=409, detail="Underlying listing is no longer active")
        buyer_wallet, buyer_address = await _verified_wallet(session, user_id=user.id, wallet_id=payload.buyer_wallet_id)
        await _verify_current_nft_owner(verifier, item_address=intent.item_address, seller_address=intent.seller_address_snapshot)
        principal = intent.price_amount * _NANOTON
        if principal <= 0 or principal != principal.to_integral_value():
            raise HTTPException(status_code=409, detail="TON principal precision is invalid")
        deal = EscrowDeal(
            id=uuid4(), listing_intent_id=intent.id, marketplace_listing_id=intent.marketplace_listing_id,
            seller_id=intent.seller_id, buyer_id=user.id, buyer_wallet_id=buyer_wallet.id,
            network="testnet", deal_salt=secrets.token_hex(32),
            collection_address_snapshot=intent.collection_address_snapshot, contract_address=None,
            contract_abi_version=None, item_address=intent.item_address,
            seller_address_snapshot=intent.seller_address_snapshot, buyer_address_snapshot=buyer_address,
            price_amount=intent.price_amount, price_currency="TON", principal_nanotons=principal,
            status=EscrowDealStatus.INTENT_CREATED.value, last_chain_seqno=None, idempotency_key=idempotency_key,
        )
        intent.status = "reserved"
        session.add(deal)
        _add_idempotency_record(session, actor_id=user.id, operation="create_deal_intent", key=idempotency_key,
            request_sha256=request_hash, resource_type="deal", resource_id=deal.id)
        await session.commit()
        await session.refresh(deal)
        return await _deal_projection(session, deal, user.id)
    except IntegrityError:
        replay = await _idempotency_race_replay(session, actor_id=user.id, operation="create_deal_intent",
            key=idempotency_key, request_sha256=request_hash, model=EscrowDeal)
        if replay.buyer_id != user.id:
            raise HTTPException(status_code=404, detail="Escrow deal not found") from None
        return await _deal_projection(session, replay, user.id)
    except HTTPException:
        await session.rollback()
        raise


@router.get("/deals/{deal_id}", response_model=EscrowDealResponse)
async def get_deal_status(deal_id: UUID, user: CurrentUser, session: DbSession):
    deal = await session.scalar(select(EscrowDeal).where(deal_id == EscrowDeal.id,
        (EscrowDeal.buyer_id == user.id) | (EscrowDeal.seller_id == user.id)))
    if deal is None:
        raise HTTPException(status_code=404, detail="Escrow deal not found")
    return await _deal_projection(session, deal, user.id)


@router.get("/buyer/deals", response_model=EscrowPageResponse)
async def list_buyer_deals(user: CurrentUser, session: DbSession, limit: int = 20, offset: int = 0):
    rows = list((await session.scalars(select(EscrowDeal).where(EscrowDeal.buyer_id == user.id)
        .order_by(EscrowDeal.created_at.desc(), EscrowDeal.id.desc()).offset(max(offset, 0))
        .limit(min(max(limit, 1), 50)))).all())
    return EscrowPageResponse(items=[await _deal_projection(session, row, user.id) for row in rows], total=len(rows))


@router.get("/seller/deals", response_model=EscrowPageResponse)
async def list_seller_deals(user: CurrentUser, session: DbSession, limit: int = 20, offset: int = 0):
    rows = list((await session.scalars(select(EscrowDeal).where(EscrowDeal.seller_id == user.id)
        .order_by(EscrowDeal.created_at.desc(), EscrowDeal.id.desc()).offset(max(offset, 0))
        .limit(min(max(limit, 1), 50)))).all())
    return EscrowPageResponse(items=[await _deal_projection(session, row, user.id) for row in rows], total=len(rows))


async def _prepare_action(
    deal_id: UUID, action: EscrowWalletAction, user: User,
    session: AsyncSession, verifier: TONNFTVerifier,
):
    _require_testnet()
    deal = await session.scalar(select(EscrowDeal).where(
        deal_id == EscrowDeal.id,
        (EscrowDeal.buyer_id == user.id) | (EscrowDeal.seller_id == user.id),
    ).with_for_update())
    if deal is None:
        raise HTTPException(status_code=404, detail="Escrow deal not found")

    seller_states = {
        EscrowWalletAction.CREATE_DEAL_ESCROW: "intent_created",
        EscrowWalletAction.DEPOSIT_NFT: "awaiting_nft",
        EscrowWalletAction.WITHDRAW_UNSOLD_NFT: "expired",
    }
    buyer_states = {
        EscrowWalletAction.FUND_DEAL: {"awaiting_buyer_funds"},
        EscrowWalletAction.ACCEPT_DEAL: {"funded_review"},
        EscrowWalletAction.OPEN_DISPUTE: {"funded_review", "delivered_dispute_window"},
        EscrowWalletAction.REFUND: {"disputed"},
    }
    if action in seller_states:
        if deal.seller_id != user.id or deal.status != seller_states[action]:
            raise HTTPException(status_code=409, detail="Seller action is not available for this deal state")
        intent = await session.get(EscrowListingIntent, deal.listing_intent_id)
        if intent is None:
            raise HTTPException(status_code=404, detail="Escrow listing intent not found")
        wallet, wallet_address = await _verified_wallet(
            session, user_id=user.id, wallet_id=intent.seller_wallet_id,
        )
        if wallet_address != deal.seller_address_snapshot:
            raise HTTPException(status_code=409, detail="Verified seller wallet snapshot has changed")
        if action in {EscrowWalletAction.CREATE_DEAL_ESCROW, EscrowWalletAction.DEPOSIT_NFT}:
            await _verify_current_nft_owner(
                verifier, item_address=deal.item_address, seller_address=deal.seller_address_snapshot,
            )
        if action is EscrowWalletAction.WITHDRAW_UNSOLD_NFT:
            if not deal.contract_address:
                raise HTTPException(status_code=503, detail={"code": "contract_address_unavailable"})
            await _verify_current_nft_owner(
                verifier, item_address=deal.item_address, seller_address=deal.contract_address,
            )
    elif action in buyer_states:
        if deal.buyer_id != user.id or deal.status not in buyer_states[action]:
            raise HTTPException(status_code=409, detail="Buyer action is not available for this deal state")
        wallet, wallet_address = await _verified_wallet(
            session, user_id=user.id, wallet_id=deal.buyer_wallet_id,
        )
        if wallet_address != deal.buyer_address_snapshot:
            raise HTTPException(status_code=409, detail="Verified buyer wallet snapshot has changed")
    elif action is EscrowWalletAction.RETURN_NFT_TO_ESCROW:
        if deal.buyer_id != user.id or deal.status != "disputed":
            raise HTTPException(status_code=409, detail="Buyer NFT return is not available in this deal state")
        wallet, wallet_address = await _verified_wallet(
            session, user_id=user.id, wallet_id=deal.buyer_wallet_id,
        )
        if wallet_address != deal.buyer_address_snapshot:
            raise HTTPException(status_code=409, detail="Verified buyer wallet snapshot has changed")
        await _verify_current_nft_owner(
            verifier, item_address=deal.item_address, seller_address=deal.buyer_address_snapshot,
        )
    else:
        raise HTTPException(status_code=409, detail="Unsupported escrow action")

    try:
        await _contract_adapter.prepare_transaction(
            action, actor_wallet=wallet, resource_id=str(deal.id),
        )
    except EscrowContractABIUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "contract_abi_pending", "message": str(exc)},
        ) from exc
    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail={"code": "contract_abi_pending", "message": "No reviewed ABI or message layout is available"},
    )


@router.post("/deals/{deal_id}/prepare/create-deal-escrow", response_model=EscrowTransactionPreparationResponse)
async def prepare_deal_escrow(deal_id: UUID, user: CurrentUser, session: DbSession, verifier: Verifier, idempotency_key: IdempotencyKey):
    del idempotency_key
    return await _prepare_action(deal_id, EscrowWalletAction.CREATE_DEAL_ESCROW, user, session, verifier)


@router.post("/deals/{deal_id}/prepare/deposit-nft", response_model=EscrowTransactionPreparationResponse)
async def prepare_nft_deposit(deal_id: UUID, user: CurrentUser, session: DbSession, verifier: Verifier, idempotency_key: IdempotencyKey):
    del idempotency_key
    return await _prepare_action(deal_id, EscrowWalletAction.DEPOSIT_NFT, user, session, verifier)


@router.post("/deals/{deal_id}/prepare/funding", response_model=EscrowTransactionPreparationResponse)
async def prepare_buyer_funding(deal_id: UUID, user: CurrentUser, session: DbSession, verifier: Verifier, idempotency_key: IdempotencyKey):
    del idempotency_key
    return await _prepare_action(deal_id, EscrowWalletAction.FUND_DEAL, user, session, verifier)


@router.post("/deals/{deal_id}/prepare/accept", response_model=EscrowTransactionPreparationResponse)
async def prepare_buyer_acceptance(deal_id: UUID, user: CurrentUser, session: DbSession, verifier: Verifier, idempotency_key: IdempotencyKey):
    del idempotency_key
    return await _prepare_action(deal_id, EscrowWalletAction.ACCEPT_DEAL, user, session, verifier)


@router.post("/deals/{deal_id}/prepare/dispute", response_model=EscrowTransactionPreparationResponse)
async def prepare_dispute(
    deal_id: UUID, payload: EscrowDisputeCreate, user: CurrentUser,
    session: DbSession, verifier: Verifier, idempotency_key: IdempotencyKey,
):
    del payload, idempotency_key
    return await _prepare_action(deal_id, EscrowWalletAction.OPEN_DISPUTE, user, session, verifier)


@router.post("/deals/{deal_id}/prepare/nft-return", response_model=EscrowTransactionPreparationResponse)
async def prepare_buyer_nft_return(
    deal_id: UUID, user: CurrentUser, session: DbSession, verifier: Verifier,
    idempotency_key: IdempotencyKey,
):
    del idempotency_key
    return await _prepare_action(deal_id, EscrowWalletAction.RETURN_NFT_TO_ESCROW, user, session, verifier)


@router.post("/deals/{deal_id}/prepare/withdraw-unsold-nft", response_model=EscrowTransactionPreparationResponse)
async def prepare_unsold_nft_withdrawal(
    deal_id: UUID, user: CurrentUser, session: DbSession, verifier: Verifier,
    idempotency_key: IdempotencyKey,
):
    del idempotency_key
    return await _prepare_action(deal_id, EscrowWalletAction.WITHDRAW_UNSOLD_NFT, user, session, verifier)


@router.post("/wallet-references", status_code=503)
async def submit_wallet_reference(
    payload: EscrowWalletReferenceInput, user: CurrentUser, session: DbSession,
):
    # No prepared action IDs exist until the ABI adapter can create an audited
    # operation record. A client hash/BOC is never accepted as proof or state.
    del payload, user, session
    raise HTTPException(status_code=503, detail={"code": "contract_abi_pending"})


@router.get("/seller/balance", response_model=EscrowSellerBalanceResponse)
async def get_seller_balance(user: CurrentUser) -> EscrowSellerBalanceResponse:
    del user
    # The approved design pays a fixed recipient directly; it does not define a
    # withdrawable contract balance ledger. Never fabricate zero or available funds.
    return EscrowSellerBalanceResponse()


@router.get("/seller/withdrawals", response_model=EscrowPageResponse)
async def list_seller_withdrawals(user: CurrentUser, session: DbSession):
    del user, session
    return EscrowPageResponse(items=[], total=0, next_cursor=None)


@router.post("/withdrawals", status_code=503)
async def blocked_legacy_withdrawal(payload: EscrowWithdrawalCreate, user: CurrentUser, session: DbSession):
    del payload, user, session
    raise HTTPException(status_code=503, detail={"code": "contract_abi_pending"})
