"""Isolated escrow API. Not mounted until integration scope is approved in main.py."""

from __future__ import annotations

import hashlib
import json
from decimal import Decimal
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
    PriceCurrency,
    User,
    Wallet,
)
from app.db.session import get_db_session
from app.escrow.contracts import (
    EscrowContractABIUnavailable,
    EscrowWalletAction,
    UnconfiguredTONEscrowContractAdapter,
)
from app.escrow.domain import EscrowDealStatus
from app.escrow.models import (
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
    EscrowListingIntentResponse,
    EscrowSellerBalanceResponse,
    EscrowTransactionPreparationResponse,
    EscrowWithdrawalCreate,
    EscrowWithdrawalResponse,
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
    payload: EscrowListingIntentCreate,
    user: CurrentUser,
    session: DbSession,
    verifier: Verifier,
    idempotency_key: IdempotencyKey,
) -> EscrowListingIntent:
    """Create an off-chain intent only; does not activate or reserve any on-chain asset."""
    _require_testnet()
    request_hash = _request_hash(_payload_dict(payload))
    try:
        replay = await _load_idempotent_resource(
            session,
            actor_id=user.id,
            operation="create_listing_intent",
            key=idempotency_key,
            request_sha256=request_hash,
            model=EscrowListingIntent,
        )
        if replay is not None:
            return replay  # type: ignore[return-value]

        rows = await session.execute(
            select(Listing, NFTAsset)
            .join(NFTAsset, Listing.asset_id == NFTAsset.id)
            .where(Listing.id == payload.listing_id)
            .with_for_update(of=Listing)
        )
        row = rows.first()
        if row is None:
            raise HTTPException(status_code=404, detail="Listing not found")
        listing, asset = row
        if listing.seller_id != user.id:
            raise HTTPException(status_code=404, detail="Listing not found")
        if listing.status is not ListingStatus.ACTIVE:
            raise HTTPException(status_code=409, detail="Listing is not active")
        if listing.price_currency is not PriceCurrency.TON:
            raise HTTPException(
                status_code=409,
                detail=(
                    "Escrow testnet intents require a TON-priced listing; "
                    "XTR is a separate domain"
                ),
            )
        if (
            asset.asset_type is not AssetType.TON_NFT
            or asset.network != "testnet"
            or asset.verification_status is not AssetVerificationStatus.VERIFIED
            or asset.owner_id != user.id
            or not asset.item_address
        ):
            raise HTTPException(
                status_code=409,
                detail="Listing asset is not a verified, seller-owned TON testnet NFT",
            )
        seller_wallet, seller_address = await _verified_wallet(
            session, user_id=user.id, wallet_id=payload.seller_wallet_id
        )
        try:
            item_address = normalize_address(asset.item_address)
        except AddressError as exc:
            raise HTTPException(status_code=409, detail="Stored NFT address is invalid") from exc
        await _verify_current_nft_owner(
            verifier, item_address=item_address, seller_address=seller_address
        )

        active_intent = await session.scalar(
            select(EscrowListingIntent).where(
                EscrowListingIntent.marketplace_listing_id == listing.id,
                EscrowListingIntent.status.in_(
                    ("intent_only", "active", "reserved", "manual_review")
                ),
            )
        )
        if active_intent is not None:
            raise HTTPException(
                status_code=409,
                detail="An escrow intent already exists for this listing",
            )

        intent = EscrowListingIntent(
            id=uuid4(),
            marketplace_listing_id=listing.id,
            asset_id=asset.id,
            seller_id=user.id,
            seller_wallet_id=seller_wallet.id,
            network="testnet",
            item_address=item_address,
            seller_address_snapshot=seller_address,
            price_amount=listing.price_amount,
            price_currency="TON",
            status="intent_only",
            contract_address=None,
            contract_abi_version=None,
            idempotency_key=idempotency_key,
        )
        session.add(intent)
        _add_idempotency_record(
            session,
            actor_id=user.id,
            operation="create_listing_intent",
            key=idempotency_key,
            request_sha256=request_hash,
            resource_type="listing_intent",
            resource_id=intent.id,
        )
        await session.commit()
        await session.refresh(intent)
        return intent
    except IntegrityError:
        replay = await _idempotency_race_replay(
            session,
            actor_id=user.id,
            operation="create_listing_intent",
            key=idempotency_key,
            request_sha256=request_hash,
            model=EscrowListingIntent,
        )
        return replay  # type: ignore[return-value]
    except HTTPException:
        await session.rollback()
        raise


@router.get("/listing-intents/{intent_id}", response_model=EscrowListingIntentResponse)
async def get_listing_intent(
    intent_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> EscrowListingIntent:
    intent = await session.scalar(
        select(EscrowListingIntent).where(
            EscrowListingIntent.id == intent_id,
            EscrowListingIntent.seller_id == user.id,
        )
    )
    if intent is None:
        raise HTTPException(status_code=404, detail="Escrow listing intent not found")
    return intent


@router.post("/deals", response_model=EscrowDealResponse, status_code=201)
async def create_deal_intent(
    payload: EscrowDealCreate,
    user: CurrentUser,
    session: DbSession,
    verifier: Verifier,
    idempotency_key: IdempotencyKey,
) -> EscrowDeal:
    """Create a deal intent only; no contract is deployed and no funds are collected."""
    _require_testnet()
    request_hash = _request_hash(_payload_dict(payload))
    try:
        replay = await _load_idempotent_resource(
            session,
            actor_id=user.id,
            operation="create_deal_intent",
            key=idempotency_key,
            request_sha256=request_hash,
            model=EscrowDeal,
        )
        if replay is not None:
            deal = replay
            if deal.buyer_id != user.id:  # type: ignore[attr-defined]
                raise HTTPException(status_code=404, detail="Escrow deal not found")
            return deal  # type: ignore[return-value]

        intent = await session.scalar(
            select(EscrowListingIntent)
            .where(EscrowListingIntent.id == payload.listing_intent_id)
            .with_for_update()
        )
        if intent is None or intent.status not in {"intent_only", "active"}:
            raise HTTPException(status_code=404, detail="Escrow listing intent not found")
        if intent.seller_id == user.id:
            raise HTTPException(status_code=409, detail="A seller cannot buy their own listing")
        listing = await session.get(Listing, intent.marketplace_listing_id)
        if (
            listing is None
            or listing.status is not ListingStatus.ACTIVE
            or listing.asset_id != intent.asset_id
        ):
            raise HTTPException(status_code=409, detail="Underlying listing is no longer active")
        buyer_wallet, buyer_address = await _verified_wallet(
            session, user_id=user.id, wallet_id=payload.buyer_wallet_id
        )
        await _verify_current_nft_owner(
            verifier,
            item_address=intent.item_address,
            seller_address=intent.seller_address_snapshot,
        )
        principal = intent.price_amount * _NANOTON
        integral_principal = principal.to_integral_value()
        if principal != integral_principal or integral_principal <= 0:
            raise HTTPException(status_code=409, detail="TON principal precision is invalid")

        deal = EscrowDeal(
            id=uuid4(),
            listing_intent_id=intent.id,
            marketplace_listing_id=intent.marketplace_listing_id,
            seller_id=intent.seller_id,
            buyer_id=user.id,
            buyer_wallet_id=buyer_wallet.id,
            network="testnet",
            contract_address=None,
            contract_abi_version=None,
            item_address=intent.item_address,
            seller_address_snapshot=intent.seller_address_snapshot,
            buyer_address_snapshot=buyer_address,
            price_amount=intent.price_amount,
            price_currency="TON",
            principal_nanotons=integral_principal,
            status=EscrowDealStatus.INTENT_CREATED.value,
            last_chain_seqno=None,
            idempotency_key=idempotency_key,
        )
        session.add(deal)
        _add_idempotency_record(
            session,
            actor_id=user.id,
            operation="create_deal_intent",
            key=idempotency_key,
            request_sha256=request_hash,
            resource_type="deal",
            resource_id=deal.id,
        )
        await session.commit()
        await session.refresh(deal)
        return deal
    except IntegrityError:
        replay = await _idempotency_race_replay(
            session,
            actor_id=user.id,
            operation="create_deal_intent",
            key=idempotency_key,
            request_sha256=request_hash,
            model=EscrowDeal,
        )
        if replay.buyer_id != user.id:  # type: ignore[attr-defined]
            raise HTTPException(
                status_code=404, detail="Escrow deal not found"
            ) from None
        return replay  # type: ignore[return-value]
    except HTTPException:
        await session.rollback()
        raise


@router.get("/deals/{deal_id}", response_model=EscrowDealResponse)
async def get_deal_status(
    deal_id: UUID,
    user: CurrentUser,
    session: DbSession,
) -> EscrowDeal:
    deal = await session.scalar(
        select(EscrowDeal).where(
            EscrowDeal.id == deal_id,
            (EscrowDeal.buyer_id == user.id) | (EscrowDeal.seller_id == user.id),
        )
    )
    if deal is None:
        raise HTTPException(status_code=404, detail="Escrow deal not found")
    return deal


@router.post(
    "/listing-intents/{intent_id}/transaction",
    response_model=EscrowTransactionPreparationResponse,
)
async def prepare_listing_transaction(
    intent_id: UUID,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> EscrowTransactionPreparationResponse:
    del idempotency_key  # No state is changed; key is still required for client consistency.
    _require_testnet()
    intent = await session.scalar(
        select(EscrowListingIntent).where(
            EscrowListingIntent.id == intent_id,
            EscrowListingIntent.seller_id == user.id,
        )
    )
    if intent is None:
        raise HTTPException(status_code=404, detail="Escrow listing intent not found")
    wallet, _ = await _verified_wallet(session, user_id=user.id, wallet_id=intent.seller_wallet_id)
    try:
        await _contract_adapter.prepare_transaction(
            EscrowWalletAction.DEPLOY_LISTING, actor_wallet=wallet, resource_id=str(intent.id)
        )
    except EscrowContractABIUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "contract_abi_pending", "message": str(exc)},
        ) from exc
    raise HTTPException(
        status_code=503,
        detail="No approved escrow transaction adapter is configured",
    )


@router.post("/deals/{deal_id}/receipt", response_model=EscrowTransactionPreparationResponse)
async def prepare_receipt_confirmation(
    deal_id: UUID,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> EscrowTransactionPreparationResponse:
    del idempotency_key  # Preparation is read-only and creates no on-chain state.
    _require_testnet()
    deal = await session.scalar(
        select(EscrowDeal).where(EscrowDeal.id == deal_id, EscrowDeal.buyer_id == user.id)
    )
    if deal is None:
        raise HTTPException(status_code=404, detail="Escrow deal not found")
    wallet, _ = await _verified_wallet(session, user_id=user.id, wallet_id=deal.buyer_wallet_id)
    try:
        await _contract_adapter.prepare_transaction(
            EscrowWalletAction.ACCEPT_RECEIPT, actor_wallet=wallet, resource_id=str(deal.id)
        )
    except EscrowContractABIUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "contract_abi_pending", "message": str(exc)},
        ) from exc
    raise HTTPException(
        status_code=503,
        detail="No approved escrow transaction adapter is configured",
    )


@router.post("/deals/{deal_id}/disputes", response_model=EscrowDisputeResponse, status_code=202)
async def request_dispute(
    deal_id: UUID,
    payload: EscrowDisputeCreate,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> EscrowDisputeResponse:
    """Record a dispute request; it is not an on-chain dispute until ABI-gated tx is confirmed."""
    _require_testnet()
    request_payload = {"deal_id": str(deal_id), **_payload_dict(payload)}
    request_hash = _request_hash(request_payload)
    try:
        replay = await _load_idempotent_resource(
            session,
            actor_id=user.id,
            operation="request_dispute",
            key=idempotency_key,
            request_sha256=request_hash,
            model=EscrowDispute,
        )
        if replay is not None:
            dispute = replay
            if dispute.opened_by != user.id:  # type: ignore[attr-defined]
                raise HTTPException(status_code=404, detail="Dispute not found")
            return EscrowDisputeResponse(
                id=dispute.id, deal_id=dispute.deal_id, opened_by=dispute.opened_by,
                reason_code=dispute.reason_code,
                status=dispute.status,
                created_at=dispute.created_at,
            )
        deal = await session.scalar(
            select(EscrowDeal)
            .where(EscrowDeal.id == deal_id, EscrowDeal.buyer_id == user.id)
            .with_for_update()
        )
        if deal is None:
            raise HTTPException(status_code=404, detail="Escrow deal not found")
        if deal.status not in {
            EscrowDealStatus.FUNDED_REVIEW.value,
            EscrowDealStatus.DELIVERED_DISPUTE_WINDOW.value,
        }:
            raise HTTPException(
                status_code=409,
                detail=(
                    "A dispute requires independently confirmed on-chain funding "
                    "or delivery evidence"
                ),
            )
        dispute = EscrowDispute(
            id=uuid4(), deal_id=deal.id, opened_by=user.id, reason_code=payload.reason_code,
            reason=payload.reason, status="requested",
        )
        session.add(dispute)
        _add_idempotency_record(
            session, actor_id=user.id, operation="request_dispute", key=idempotency_key,
            request_sha256=request_hash, resource_type="dispute", resource_id=dispute.id,
        )
        await session.commit()
        await session.refresh(dispute)
        return EscrowDisputeResponse(
            id=dispute.id, deal_id=dispute.deal_id, opened_by=dispute.opened_by,
            reason_code=dispute.reason_code, status=dispute.status, created_at=dispute.created_at,
        )
    except IntegrityError:
        replay = await _idempotency_race_replay(
            session, actor_id=user.id, operation="request_dispute", key=idempotency_key,
            request_sha256=request_hash, model=EscrowDispute,
        )
        return EscrowDisputeResponse(
            id=replay.id, deal_id=replay.deal_id, opened_by=replay.opened_by,
            reason_code=replay.reason_code, status=replay.status, created_at=replay.created_at,
        )
    except HTTPException:
        await session.rollback()
        raise


@router.get("/seller/balance", response_model=EscrowSellerBalanceResponse)
async def get_seller_balance(user: CurrentUser) -> EscrowSellerBalanceResponse:
    del user
    # The approved design pays a fixed recipient directly; it does not define a
    # withdrawable contract balance ledger. Never fabricate zero or available funds.
    return EscrowSellerBalanceResponse()


@router.post("/withdrawals", response_model=EscrowWithdrawalResponse, status_code=202)
async def prepare_withdrawal(
    payload: EscrowWithdrawalCreate,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> EscrowWithdrawalResponse:
    """Persist a blocked withdrawal intent without an amount or a TON transaction."""
    _require_testnet()
    request_hash = _request_hash(_payload_dict(payload))
    try:
        replay = await _load_idempotent_resource(
            session,
            actor_id=user.id,
            operation="prepare_withdrawal",
            key=idempotency_key,
            request_sha256=request_hash,
            model=EscrowWithdrawal,
        )
        if replay is not None:
            return EscrowWithdrawalResponse(
                id=replay.id, recipient_address=replay.recipient_address,
                status=replay.status, reason_code=replay.reason_code, created_at=replay.created_at,
            )
        wallet, canonical_address = await _verified_wallet(
            session, user_id=user.id, wallet_id=payload.wallet_id
        )
        withdrawal = EscrowWithdrawal(
            id=uuid4(), seller_id=user.id, wallet_id=wallet.id, network="testnet",
            recipient_address=canonical_address, amount_nanotons=None,
            status="blocked_abi_unavailable", reason_code="contract_abi_pending",
            transaction_hash=None,
        )
        session.add(withdrawal)
        _add_idempotency_record(
            session, actor_id=user.id, operation="prepare_withdrawal", key=idempotency_key,
            request_sha256=request_hash, resource_type="withdrawal", resource_id=withdrawal.id,
        )
        await session.commit()
        await session.refresh(withdrawal)
        return EscrowWithdrawalResponse(
            id=withdrawal.id, recipient_address=withdrawal.recipient_address,
            status=withdrawal.status, reason_code=withdrawal.reason_code,
            created_at=withdrawal.created_at,
        )
    except IntegrityError:
        replay = await _idempotency_race_replay(
            session, actor_id=user.id, operation="prepare_withdrawal", key=idempotency_key,
            request_sha256=request_hash, model=EscrowWithdrawal,
        )
        return EscrowWithdrawalResponse(
            id=replay.id, recipient_address=replay.recipient_address,
            status=replay.status, reason_code=replay.reason_code, created_at=replay.created_at,
        )
    except HTTPException:
        await session.rollback()
        raise
