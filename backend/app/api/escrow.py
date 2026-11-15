"""Isolated escrow API. Not mounted until integration scope is approved in main.py."""

from __future__ import annotations

import hashlib
import json
import re
import secrets
from dataclasses import asdict
from datetime import UTC, datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Annotated
from uuid import UUID, uuid4

from fastapi import APIRouter, Depends, Header, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.ton_nft.address import AddressError, normalize_address
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
    DealEscrowDeploymentSnapshot,
    EscrowContractABIUnavailable,
    EscrowWalletAction,
    PinnedTONEscrowContractAdapter,
)
from app.escrow.dependencies import get_escrow_nft_identity_provider
from app.escrow.domain import EscrowDealStatus
from app.escrow.finality_provider import (
    EscrowProviderInvalidEvidence,
    EscrowProviderUnavailable,
    PytoniqTONTestnetEscrowProvider,
)
from app.escrow.models import (
    EscrowDeal,
    EscrowDispute,
    EscrowIdempotencyRecord,
    EscrowListingIntent,
    EscrowWalletActionRecord,
)
from app.escrow.nft_identity import (
    NFTIdentityEvidenceError,
    same_nft_identity_anchor,
    validate_nft_identity_snapshot,
)
from app.escrow.reservation import (
    EscrowListingReservationConflict,
    reserve_listing_for_escrow,
)
from app.escrow.schemas import (
    EscrowDealCreate,
    EscrowDealResponse,
    EscrowDisputeCreate,
    EscrowListingIntentCreate,
    EscrowListingIntentResponse,
    EscrowNftProjection,
    EscrowPageResponse,
    EscrowSellerBalanceResponse,
    EscrowTransactionPreparationResponse,
    EscrowWalletReferenceInput,
    EscrowWalletReferenceResponse,
    EscrowWithdrawalCreate,
)
from app.escrow.service import (
    EscrowActionConflict,
    canonical_request_sha256,
    create_or_replay_action,
    record_submission_reference,
)
from app.escrow.ton_abi import (
    TONABIError,
    derive_deployment,
    load_pinned_code_boc,
    validate_snapshot,
    verify_compiled_code,
)


def _ton_nano(value: Decimal) -> str:
    amount = value * _NANOTON
    if amount <= 0 or amount != amount.to_integral_value():
        raise HTTPException(status_code=409, detail="TON principal precision is invalid")
    return str(int(amount))


def _listing_actions(intent: EscrowListingIntent, actor_id: UUID) -> list[str]:
    if actor_id == intent.seller_id:
        return []
    return ["create_deal_intent"] if intent.status in {"intent_only", "active"} else []


def _deal_actions(deal: EscrowDeal, actor_id: UUID) -> list[str]:
    if actor_id == deal.seller_id:
        if deal.status == "intent_created":
            # Activation is separately gated by a trust-level-0 account-state
            # proof in its preparation route. It is safe to expose here while
            # the user deploys; premature calls fail closed until deployed.
            return ["create_deal_escrow", "activate_deal"]
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


async def _listing_projection(
    session: AsyncSession,
    intent: EscrowListingIntent,
    actor_id: UUID,
) -> EscrowListingIntentResponse:
    asset = await session.get(NFTAsset, intent.asset_id)
    return EscrowListingIntentResponse(
        id=intent.marketplace_listing_id,
        listing_key=intent.listing_key,
        seller_id=intent.seller_id,
        state=intent.status, network="testnet",
        nft=EscrowNftProjection(
            asset_id=intent.asset_id,
            title=asset.name if asset and asset.name else "TON NFT",
            image_url=asset.image_url if asset else None, item_address=intent.item_address,
            collection_address=intent.collection_address_snapshot,
        ),
        seller_wallet_address=intent.seller_address_snapshot,
        price_nano=_ton_nano(intent.price_amount),
        available_actions=_listing_actions(intent, actor_id),
        created_at=intent.created_at, updated_at=intent.updated_at,
    )


async def _deal_projection(
    session: AsyncSession,
    deal: EscrowDeal,
    actor_id: UUID,
) -> EscrowDealResponse:
    intent = await session.get(EscrowListingIntent, deal.listing_intent_id)
    asset = await session.get(NFTAsset, intent.asset_id) if intent else None
    dispute = await session.scalar(select(EscrowDispute).where(EscrowDispute.deal_id == deal.id))
    return EscrowDealResponse(
        id=deal.id,
        listing_id=deal.marketplace_listing_id,
        listing_key=deal.listing_key_snapshot,
        buyer_id=deal.buyer_id, seller_id=deal.seller_id, state=deal.status, network="testnet",
        nft=EscrowNftProjection(
            asset_id=intent.asset_id if intent else None,
            title=asset.name if asset and asset.name else "TON NFT",
            image_url=asset.image_url if asset else None, item_address=deal.item_address,
            collection_address=deal.collection_address_snapshot,
        ),
        escrow_address=deal.contract_address, seller_wallet_address=deal.seller_address_snapshot,
        buyer_wallet_address=deal.buyer_address_snapshot,
        price_nano=str(int(deal.principal_nanotons)),
        buyer_review_deadline=None,
        dispute_deadline=None,
        available_actions=_deal_actions(deal, actor_id),
        created_at=deal.created_at, updated_at=deal.updated_at,
        dispute=({
            "id": str(dispute.id),
            "status": (
                "open" if dispute.status in {"requested", "confirmed"}
                else "under_review" if dispute.status == "manual_review"
                else "resolved_seller" if dispute.status == "rejected"
                else dispute.status
            ),
            "reason_code": dispute.reason_code,
            "summary": dispute.reason, "opened_at": dispute.created_at.isoformat(),
            "resolved_at": dispute.resolved_at.isoformat() if dispute.resolved_at else None,
            "resolution_note": None,
        } if dispute else None),
    )


router = APIRouter(prefix="/escrow", tags=["ton-escrow"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
IdentityProvider = Annotated[
    PytoniqTONTestnetEscrowProvider,
    Depends(get_escrow_nft_identity_provider),
]
IdempotencyKey = Annotated[str, Header(alias="Idempotency-Key", min_length=8, max_length=128)]

_NANOTON = Decimal(1_000_000_000)


_DEPLOYMENT_SNAPSHOT_BINDINGS = {
    "network": "network",
    "network_id": "network_id",
    "protocol_version": "protocol_version",
    "listing_key": "listing_key_snapshot",
    "seller_address": "seller_address_snapshot",
    "buyer_address": "buyer_address_snapshot",
    "collection_address": "collection_address_snapshot",
    "item_address": "item_address",
    "principal_nanotons": "principal_nanotons",
    "execution_reserve_nanotons": "execution_reserve_nanotons",
    "seller_deployment_refund_nanotons": "seller_deployment_refund_nanotons",
    "nft_transfer_value_nanotons": "nft_transfer_value_nanotons",
    "deal_salt": "deal_salt",
    "activation_query_id": "activation_query_id",
    "fund_query_id": "fund_query_id",
    "nft_deposit_query_id": "nft_deposit_query_id",
    "nft_release_query_id": "nft_release_query_id",
    "nft_return_to_escrow_query_id": "nft_return_to_escrow_query_id",
    "oracle_key_a": "oracle_key_a",
    "oracle_key_b": "oracle_key_b",
    "oracle_key_c": "oracle_key_c",
    "resolver_key_a": "resolver_key_a",
    "resolver_key_b": "resolver_key_b",
    "resolver_key_c": "resolver_key_c",
    "deployment_value_nanotons": "deployment_value_nanotons",
    "activation_value_nanotons": "activation_value_nanotons",
    "action_value_nanotons": "action_value_nanotons",
    "nft_deposit_value_nanotons": "nft_deposit_value_nanotons",
    "nft_return_value_nanotons": "nft_return_value_nanotons",
    "contract_state": "contract_state",
    "deadline_unix": "deadline_unix",
    "observed_chain_time_unix": "observed_chain_time_unix",
    "dispute_phase": "dispute_phase",
    "nft_in_escrow": "nft_in_escrow",
    "principal_locked": "principal_locked",
}


_DEPLOYMENT_SNAPSHOT_VERSION = 1
_HEX_256 = re.compile(r"^[0-9a-fA-F]{64}$")
_GETTER_SNAPSHOT_FIELDS = (
    "contract_state",
    "deadline_unix",
    "observed_chain_time_unix",
    "dispute_phase",
    "nft_in_escrow",
    "principal_locked",
    "recovery_previous_owner",
    "recovery_item_address",
)


def _canonical_sha256(value: object) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _new_query_ids(count: int = 5) -> tuple[int, ...]:
    values: set[int] = set()
    while len(values) < count:
        candidate = secrets.randbits(64)
        if candidate:
            values.add(candidate)
    return tuple(values)


def _authority_keys(values: list[str], setting_name: str) -> tuple[int, int, int]:
    if len(values) != 3 or any(
        not isinstance(value, str) or not _HEX_256.fullmatch(value)
        for value in values
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "escrow_authority_keys_unconfigured", "setting": setting_name},
        )
    parsed = tuple(int(value, 16) for value in values)
    if len(set(parsed)) != 3 or any(value == 0 for value in parsed):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "escrow_authority_keys_invalid", "setting": setting_name},
        )
    return parsed  # type: ignore[return-value]


def _initial_deployment_snapshot(
    deal: EscrowDeal,
) -> tuple[dict[str, object], str, str, str]:
    """Build the immutable testnet terms before reserving the marketplace listing.

    Missing/unapproved authority keys or invalid pinned artifacts fail the deal-intent
    request before the listing is reserved, so the NFT cannot be stranded by a
    deployment that is impossible to prepare.
    """

    settings = get_settings()
    oracle_keys = _authority_keys(
        settings.ton_escrow_oracle_public_keys, "TON_ESCROW_ORACLE_PUBLIC_KEYS"
    )
    resolver_keys = _authority_keys(
        settings.ton_escrow_resolver_public_keys, "TON_ESCROW_RESOLVER_PUBLIC_KEYS"
    )
    if len(set((*oracle_keys, *resolver_keys))) != 6:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "escrow_authority_keys_must_be_unique"},
        )
    activation_id, fund_id, deposit_id, release_id, return_id = _new_query_ids()
    snapshot = DealEscrowDeploymentSnapshot(
        network="testnet",
        network_id=-3,
        protocol_version=1,
        listing_key=deal.listing_key_snapshot,
        seller_address=deal.seller_address_snapshot,
        buyer_address=deal.buyer_address_snapshot,
        collection_address=deal.collection_address_snapshot,
        item_address=deal.item_address,
        principal_nanotons=int(deal.principal_nanotons),
        execution_reserve_nanotons=settings.ton_escrow_execution_reserve_nanotons,
        seller_deployment_refund_nanotons=settings.ton_escrow_seller_deployment_refund_nanotons,
        nft_transfer_value_nanotons=settings.ton_escrow_nft_transfer_value_nanotons,
        deal_salt=deal.deal_salt,
        activation_query_id=activation_id,
        fund_query_id=fund_id,
        nft_deposit_query_id=deposit_id,
        nft_release_query_id=release_id,
        nft_return_to_escrow_query_id=return_id,
        oracle_key_a=oracle_keys[0],
        oracle_key_b=oracle_keys[1],
        oracle_key_c=oracle_keys[2],
        resolver_key_a=resolver_keys[0],
        resolver_key_b=resolver_keys[1],
        resolver_key_c=resolver_keys[2],
        deployment_value_nanotons=settings.ton_escrow_deployment_value_nanotons,
        activation_value_nanotons=settings.ton_escrow_activation_value_nanotons,
        action_value_nanotons=settings.ton_escrow_action_value_nanotons,
        nft_deposit_value_nanotons=settings.ton_escrow_nft_deposit_value_nanotons,
        nft_return_value_nanotons=settings.ton_escrow_nft_return_value_nanotons,
        contract_state=0,
        deadline_unix=0,
        observed_chain_time_unix=0,
        dispute_phase=0,
        nft_in_escrow=False,
        principal_locked=False,
    )
    try:
        validate_snapshot(snapshot)
        code_boc = load_pinned_code_boc()
        artifacts = verify_compiled_code(code_boc)
        deployment = derive_deployment(code_boc, snapshot)
    except TONABIError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "escrow_deployment_snapshot_invalid"},
        ) from exc
    values = asdict(snapshot)
    return values, _canonical_sha256(values), deployment.address, artifacts.abi_version


def _build_deployment_snapshot(
    deal: EscrowDeal,
    *,
    allow_initial_state: bool = False,
) -> tuple[DealEscrowDeploymentSnapshot | None, tuple[str, ...]]:
    """Load and cryptographically bind persisted immutable terms plus verified getter state."""

    stored = getattr(deal, "deployment_snapshot_json", None)
    stored_hash = getattr(deal, "deployment_snapshot_sha256", None)
    version = getattr(deal, "deployment_snapshot_version", None)
    source = getattr(deal, "deployment_snapshot_source", None)
    if not isinstance(stored, dict) or not isinstance(stored_hash, str):
        # Missing persisted evidence is an incomplete snapshot, not evidence of
        # tampering. Keep the explicit storage-field markers so callers return a
        # stable retryable "incomplete" code instead of "integrity failed".
        return None, (
            "deployment_snapshot_json",
            "deployment_snapshot_sha256",
            "deployment_snapshot_version",
            "deployment_snapshot_source",
            *tuple(_DEPLOYMENT_SNAPSHOT_BINDINGS),
        )
    if version != _DEPLOYMENT_SNAPSHOT_VERSION or source != "pinned-dealescrow-v1":
        return None, ("deployment_snapshot_version",)
    if not _HEX_256.fullmatch(stored_hash) or _canonical_sha256(stored) != stored_hash:
        return None, ("deployment_snapshot_sha256",)

    values: dict[str, object] = dict(stored)
    getter = getattr(deal, "getter_snapshot_json", None)
    if getter is not None:
        getter_hash = getattr(deal, "getter_snapshot_sha256", None)
        block_hash = getattr(deal, "getter_snapshot_block_hash", None)
        seqno = getattr(deal, "getter_snapshot_masterchain_seqno", None)
        provider = getattr(deal, "getter_snapshot_provider", None)
        if (
            not isinstance(getter, dict)
            or not isinstance(getter_hash, str)
            or not _HEX_256.fullmatch(getter_hash)
            or _canonical_sha256(getter) != getter_hash
            or isinstance(seqno, bool)
            or not isinstance(seqno, int)
            or seqno <= 0
            or not isinstance(block_hash, str)
            or not _HEX_256.fullmatch(block_hash)
            or not isinstance(provider, str)
            or not provider.strip()
        ):
            return None, ("getter_snapshot_integrity",)
        if any(field not in getter for field in _GETTER_SNAPSHOT_FIELDS):
            return None, ("getter_snapshot_fields",)
        # The getter evidence JSON also retains other authenticated storage fields
        # (e.g. attempt counters and evidence hashes), but the immutable constructor
        # dataclass only receives the snapshot's documented getter members.
        values.update({field: getter[field] for field in _GETTER_SNAPSHOT_FIELDS})
    elif not allow_initial_state or deal.status != EscrowDealStatus.INTENT_CREATED.value:
        return None, ("finalized_getter_snapshot",)

    try:
        snapshot = DealEscrowDeploymentSnapshot(**values)
        validate_snapshot(snapshot)
        if (
            snapshot.network != deal.network
            or snapshot.listing_key != deal.listing_key_snapshot
            or snapshot.seller_address != deal.seller_address_snapshot
            or snapshot.buyer_address != deal.buyer_address_snapshot
            or snapshot.collection_address != deal.collection_address_snapshot
            or snapshot.item_address != deal.item_address
            or snapshot.principal_nanotons != int(deal.principal_nanotons)
            or snapshot.deal_salt != deal.deal_salt
        ):
            return None, ("deployment_snapshot_core_terms_mismatch",)
        if deal.contract_address and deal.contract_address != derive_deployment(
            load_pinned_code_boc(), snapshot
        ).address:
            return None, ("deployment_snapshot_contract_address_mismatch",)
    except (TONABIError, TypeError, ValueError, KeyError):
        return None, ("deployment_snapshot_invalid",)
    return snapshot, ()


def _prepared_action_response(
    action_record: EscrowWalletActionRecord,
) -> EscrowTransactionPreparationResponse:
    payload = action_record.unsigned_payload_json
    bocs = action_record.unsigned_bocs_json
    if (
        not isinstance(payload, dict)
        or not isinstance(bocs, dict)
        or not isinstance(action_record.unsigned_payload_sha256, str)
        or not isinstance(action_record.unsigned_boc_sha256, str)
        or not _HEX_256.fullmatch(action_record.unsigned_payload_sha256)
        or not _HEX_256.fullmatch(action_record.unsigned_boc_sha256)
        or _canonical_sha256(payload) != action_record.unsigned_payload_sha256
        or _canonical_sha256(bocs) != action_record.unsigned_boc_sha256
        or not action_record.unsigned_boc_ref
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "stored_unsigned_payload_integrity_failed"},
        )
    return EscrowTransactionPreparationResponse(
        status="prepared",
        network="testnet",
        action_id=action_record.id,
        payload=payload,
        payload_sha256=action_record.unsigned_payload_sha256,
        unsigned_boc_sha256=action_record.unsigned_boc_sha256,
    )


def _action_query_id(
    action: EscrowWalletAction,
    snapshot: DealEscrowDeploymentSnapshot,
    action_record: EscrowWalletActionRecord,
) -> int | None:
    fixed_ids = {
        EscrowWalletAction.ACTIVATE_DEAL: snapshot.activation_query_id,
        EscrowWalletAction.DEPOSIT_NFT: snapshot.nft_deposit_query_id,
        EscrowWalletAction.FUND_DEAL: snapshot.fund_query_id,
        EscrowWalletAction.ACCEPT_DEAL: snapshot.nft_release_query_id,
        EscrowWalletAction.RETURN_NFT_TO_ESCROW: snapshot.nft_return_to_escrow_query_id,
    }
    if action in fixed_ids:
        expected = fixed_ids[action]
        if action_record.query_id is not None and action_record.query_id != str(expected):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "stored_action_query_id_conflict"},
            )
        action_record.query_id = str(expected)
        return expected
    if action in {
        EscrowWalletAction.OPEN_DISPUTE,
        EscrowWalletAction.TIMEOUT_DEAL,
        EscrowWalletAction.RECOVER_UNEXPECTED_NFT,
    }:
        if action_record.query_id is None:
            used = {
                snapshot.activation_query_id,
                snapshot.fund_query_id,
                snapshot.nft_deposit_query_id,
                snapshot.nft_release_query_id,
                snapshot.nft_return_to_escrow_query_id,
            }
            query_id = secrets.randbits(64)
            while query_id == 0 or query_id in used:
                query_id = secrets.randbits(64)
            action_record.query_id = str(query_id)
        try:
            query_id = int(action_record.query_id)
        except (TypeError, ValueError) as exc:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "stored_action_query_id_invalid"},
            ) from exc
        if not 0 < query_id < (1 << 64):
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "stored_action_query_id_invalid"},
            )
        return query_id
    return None


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
    lock: bool = False,
) -> tuple[Wallet, str]:
    statement = select(Wallet).where(
        Wallet.id == wallet_id,
        Wallet.user_id == user_id,
        Wallet.is_verified.is_(True),
        Wallet.network == "testnet",
    )
    if lock:
        statement = statement.with_for_update().execution_options(populate_existing=True)
    wallet = await session.scalar(statement)
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


async def _verify_escrow_nft_identity(
    provider: PytoniqTONTestnetEscrowProvider,
    *,
    item_address: str,
    collection_address: str,
    expected_owner_address: str,
    minimum_masterchain_seqno: int = 0,
) -> dict[str, object]:
    """Require same-block, allowlisted TEP-62 identity evidence for escrow."""
    try:
        evidence = await provider.verify_nft_identity(
            item_address=item_address,
            collection_address=collection_address,
            expected_owner_address=expected_owner_address,
            minimum_masterchain_seqno=minimum_masterchain_seqno,
        )
    except EscrowProviderUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "escrow_nft_identity_provider_unavailable"},
        ) from exc
    except EscrowProviderInvalidEvidence as exc:
        message = str(exc)
        if "No escrow NFT collection policy is configured" in message:
            raise HTTPException(
                status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
                detail={"code": "escrow_nft_collection_policy_unconfigured"},
            ) from exc
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "escrow_nft_identity_unverified"},
        ) from exc
    if evidence is None:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "escrow_nft_owner_mismatch"},
        )
    try:
        return validate_nft_identity_snapshot(
            evidence,
            evidence.get("evidence_sha256"),
        )
    except NFTIdentityEvidenceError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "escrow_nft_identity_evidence_invalid"},
        ) from exc


@router.post("/listing-intents", response_model=EscrowListingIntentResponse, status_code=201)
async def create_listing_intent(
    payload: EscrowListingIntentCreate, user: CurrentUser, session: DbSession,
    identity_provider: IdentityProvider, idempotency_key: IdempotencyKey,
) -> EscrowListingIntentResponse:
    """Create a seller intent over a normal draft/active TON marketplace listing."""
    _require_testnet()
    actor_id = user.id
    request_hash = _request_hash(_payload_dict(payload))
    try:
        replay = await _load_idempotent_resource(
            session, actor_id=actor_id, operation="create_listing_intent", key=idempotency_key,
            request_sha256=request_hash, model=EscrowListingIntent,
        )
        if replay is not None:
            return await _listing_projection(session, replay, actor_id)

        asset = await session.scalar(select(NFTAsset).where(
            NFTAsset.id == payload.asset_id, NFTAsset.owner_id == actor_id,
            NFTAsset.network == "testnet", NFTAsset.asset_type == AssetType.TON_NFT,
            NFTAsset.verification_status == AssetVerificationStatus.VERIFIED,
        ).with_for_update())
        if asset is None or not asset.item_address:
            raise HTTPException(status_code=409,
                detail="Only verified seller-owned TON testnet NFTs are eligible")
        wallet, seller_address = await _verified_wallet(session, user_id=actor_id,
            wallet_id=payload.seller_wallet_id)
        try:
            item_address = normalize_address(asset.item_address)
        except AddressError as exc:
            raise HTTPException(status_code=409,
                detail="Stored NFT item address is invalid") from exc
        if asset.collection_id is None:
            raise HTTPException(status_code=409,
                detail="A verified testnet NFT collection is required for DealEscrow")
        collection = await session.get(NFTCollection, asset.collection_id)
        if collection is None or collection.network != "testnet":
            raise HTTPException(status_code=409,
                detail="NFT collection is not verified for TON testnet escrow")
        try:
            collection_address = normalize_address(collection.address)
        except AddressError as exc:
            raise HTTPException(status_code=409,
                detail="Stored NFT collection address is invalid") from exc
        asset_snapshot = {
            "id": asset.id,
            "owner_id": asset.owner_id,
            "network": asset.network,
            "asset_type": asset.asset_type,
            "verification_status": asset.verification_status,
            "external_id": asset.external_id,
            "item_address": item_address,
            "collection_id": asset.collection_id,
            "collection_address": collection_address,
        }
        seller_wallet_id = wallet.id
        expected_seller_address = seller_address
        # No row locks are held during proof-provider I/O.
        await session.rollback()
        identity_snapshot = await _verify_escrow_nft_identity(
            identity_provider,
            item_address=item_address,
            collection_address=collection_address,
            expected_owner_address=expected_seller_address,
        )

        # Preserve the marketplace lock order used by order reservation and
        # publication: Listing -> seller Wallet -> NFTAsset. Provider I/O above
        # happened without locks; now lock existing candidate listings in stable
        # id order before locking the seller wallet and asset.
        candidate_listing_ids = list(
            (
                await session.scalars(
                    select(Listing.id)
                    .where(
                        Listing.asset_id == asset_snapshot["id"],
                        Listing.status.in_((ListingStatus.ACTIVE, ListingStatus.DRAFT)),
                    )
                    .order_by(Listing.id)
                )
            ).all()
        )
        locked_listings: list[Listing] = []
        if candidate_listing_ids:
            locked_listings = list(
                (
                    await session.scalars(
                        select(Listing)
                        .where(Listing.id.in_(candidate_listing_ids))
                        .order_by(Listing.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).all()
            )
            if {row.id for row in locked_listings} != set(candidate_listing_ids):
                raise HTTPException(
                    status_code=409,
                    detail={"code": "escrow_nft_listing_changed_during_proof"},
                )

        wallet, current_seller_address = await _verified_wallet(
            session,
            user_id=actor_id,
            wallet_id=seller_wallet_id,
            lock=True,
        )
        if wallet.id != seller_wallet_id or current_seller_address != expected_seller_address:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_seller_wallet_changed_during_proof"},
            )

        asset = await session.scalar(
            select(NFTAsset)
            .where(NFTAsset.id == asset_snapshot["id"])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            asset is None
            or asset.owner_id != actor_id
            or asset.owner_id != asset_snapshot["owner_id"]
            or asset.network != asset_snapshot["network"]
            or asset.asset_type != asset_snapshot["asset_type"]
            or asset.verification_status != asset_snapshot["verification_status"]
            or asset.external_id != asset_snapshot["external_id"]
            or asset.collection_id != asset_snapshot["collection_id"]
            or asset.item_address is None
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_asset_changed_during_proof"},
            )
        try:
            current_item_address = normalize_address(asset.item_address)
        except AddressError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_asset_changed_during_proof"},
            ) from exc
        if current_item_address != asset_snapshot["item_address"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_asset_changed_during_proof"},
            )

        collection = await session.scalar(
            select(NFTCollection)
            .where(NFTCollection.id == asset_snapshot["collection_id"])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if collection is None or collection.network != "testnet":
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_collection_changed_during_proof"},
            )
        try:
            current_collection_address = normalize_address(collection.address)
        except AddressError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_collection_changed_during_proof"},
            ) from exc
        if current_collection_address != asset_snapshot["collection_address"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_collection_changed_during_proof"},
            )

        # A draft or active listing may have appeared while provider I/O was in
        # flight. Never acquire a newly-discovered Listing lock after the asset
        # lock (that would invert the shared order); retry instead.
        current_candidate_listing_ids = list(
            (
                await session.scalars(
                    select(Listing.id)
                    .where(
                        Listing.asset_id == asset_snapshot["id"],
                        Listing.status.in_((ListingStatus.ACTIVE, ListingStatus.DRAFT)),
                    )
                    .order_by(Listing.id)
                )
            ).all()
        )
        if current_candidate_listing_ids != candidate_listing_ids:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_listing_changed_during_proof"},
            )

        # Any reserved/review-pending listing blocks a new escrow intent even
        # when an unrelated draft row also exists for the same asset.
        reserved_or_review_listing = await session.scalar(
            select(Listing.id).where(
                Listing.asset_id == asset_snapshot["id"],
                Listing.status.in_(
                    (ListingStatus.RESERVED, ListingStatus.PENDING_REVIEW)
                ),
            )
        )
        if reserved_or_review_listing is not None:
            raise HTTPException(
                status_code=409,
                detail="NFT already has a reserved or review-pending listing",
            )

        # A second open intent for a different draft of the same NFT is also
        # disallowed; idempotent replay was handled before leaving the first
        # transaction. Intent rows are locked last, after shared marketplace rows.
        if candidate_listing_ids:
            existing_open_intents = list(
                (
                    await session.scalars(
                        select(EscrowListingIntent)
                        .where(
                            EscrowListingIntent.marketplace_listing_id.in_(
                                candidate_listing_ids
                            ),
                            EscrowListingIntent.status.in_(
                                ("intent_only", "active", "reserved", "manual_review")
                            ),
                        )
                        .order_by(EscrowListingIntent.id)
                        .with_for_update()
                        .execution_options(populate_existing=True)
                    )
                ).all()
            )
            if existing_open_intents:
                raise HTTPException(
                    status_code=409,
                    detail="An open escrow listing intent already exists for this NFT",
                )

        listing = next(
            (row for row in locked_listings if row.status is ListingStatus.ACTIVE),
            None,
        )
        if listing is None:
            listing = next(
                (row for row in locked_listings if row.status is ListingStatus.DRAFT),
                None,
            )
        if listing is not None and listing.seller_id != actor_id:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_listing_owner_mismatch"},
            )
        if listing is None:
            conflict = await session.scalar(
                select(Listing.id).where(
                    Listing.asset_id == asset.id,
                    Listing.status.in_(
                        (ListingStatus.RESERVED, ListingStatus.PENDING_REVIEW)
                    ),
                )
            )
            if conflict is not None:
                raise HTTPException(
                    status_code=409,
                    detail="NFT already has a reserved or review-pending listing",
                )

        price_nano = Decimal(payload.price_nano)
        price_amount = price_nano / _NANOTON
        if price_amount <= 0 or price_amount * _NANOTON != price_nano:
            raise HTTPException(
                status_code=422,
                detail="price_nano must be a positive integer nanotons",
            )

        if listing is not None and listing.status is ListingStatus.ACTIVE:
            if (
                listing.price_currency is not PriceCurrency.TON
                or listing.price_amount != price_amount
            ):
                raise HTTPException(
                    status_code=409,
                    detail="Active listing price/currency must match the escrow intent",
                )
        elif listing is not None:
            listing.price_amount = price_amount
            listing.price_currency = PriceCurrency.TON
            if not listing.title:
                listing.title = asset.name
        else:
            listing = Listing(
                id=uuid4(),
                asset_id=asset.id,
                seller_id=actor_id,
                status=ListingStatus.DRAFT,
                price_amount=price_amount,
                price_currency=PriceCurrency.TON,
                title=asset.name,
            )
            session.add(listing)
            await session.flush()

        existing_intent = await session.scalar(select(EscrowListingIntent).where(
            EscrowListingIntent.marketplace_listing_id == listing.id,
        ).with_for_update())
        if existing_intent is not None:
            raise HTTPException(status_code=409,
                detail="An escrow listing intent already exists for this listing")
        intent = EscrowListingIntent(
            id=uuid4(), marketplace_listing_id=listing.id, asset_id=asset.id, seller_id=actor_id,
            seller_wallet_id=wallet.id, network="testnet", item_address=item_address,
            listing_key=secrets.token_hex(32), collection_address_snapshot=collection_address,
            nft_identity_snapshot_json=identity_snapshot,
            nft_identity_snapshot_sha256=str(identity_snapshot["evidence_sha256"]),
            seller_address_snapshot=seller_address,
            price_amount=price_amount, price_currency="TON", status="intent_only",
            contract_address=None, contract_abi_version=None, idempotency_key=idempotency_key,
        )
        session.add(intent)
        _add_idempotency_record(session, actor_id=actor_id, operation="create_listing_intent",
            key=idempotency_key, request_sha256=request_hash,
            resource_type="listing_intent", resource_id=intent.id)
        await session.commit()
        await session.refresh(intent)
        return await _listing_projection(session, intent, actor_id)
    except IntegrityError:
        replay = await _idempotency_race_replay(session, actor_id=actor_id,
            operation="create_listing_intent", key=idempotency_key,
            request_sha256=request_hash, model=EscrowListingIntent)
        return await _listing_projection(session, replay, actor_id)
    except HTTPException:
        await session.rollback()
        raise


@router.get("/marketplace/listing-intents", response_model=EscrowPageResponse)
async def discover_listing_intents(user: CurrentUser, session: DbSession, limit: int = 20,
    offset: int = 0):
    _require_testnet()
    rows = list((await session.scalars(
        select(EscrowListingIntent).join(Listing,
            Listing.id == EscrowListingIntent.marketplace_listing_id)
        .where(EscrowListingIntent.status.in_(("intent_only", "active")),
               Listing.status == ListingStatus.ACTIVE, EscrowListingIntent.seller_id != user.id)
        .order_by(EscrowListingIntent.created_at.desc(), EscrowListingIntent.id.desc())
        .offset(max(offset, 0)).limit(min(max(limit, 1), 50))
    )).all())
    return EscrowPageResponse(
        items=[await _listing_projection(session, row, user.id) for row in rows],
        total=len(rows),
    )


@router.get("/listing-intents", response_model=EscrowPageResponse)
async def list_seller_listing_intents(user: CurrentUser, session: DbSession, limit: int = 20,
    offset: int = 0):
    rows = list((await session.scalars(
        select(EscrowListingIntent).where(EscrowListingIntent.seller_id == user.id)
        .order_by(EscrowListingIntent.created_at.desc(), EscrowListingIntent.id.desc())
        .offset(max(offset, 0)).limit(min(max(limit, 1), 50))
    )).all())
    return EscrowPageResponse(
        items=[await _listing_projection(session, row, user.id) for row in rows],
        total=len(rows),
    )


@router.get("/listing-intents/{listing_id}", response_model=EscrowListingIntentResponse)
async def get_listing_intent(listing_id: UUID, user: CurrentUser, session: DbSession):
    intent = await session.scalar(select(EscrowListingIntent).where(
        EscrowListingIntent.marketplace_listing_id == listing_id,
    ))
    if intent is None:
        raise HTTPException(status_code=404, detail="Escrow listing intent not found")
    if intent.seller_id != user.id:
        listing = await session.get(Listing, intent.marketplace_listing_id)
        if (
            listing is None
            or listing.status is not ListingStatus.ACTIVE
            or intent.status not in {"intent_only", "active"}
        ):
            raise HTTPException(status_code=404, detail="Escrow listing intent not found")
    return await _listing_projection(session, intent, user.id)

@router.post("/deals", response_model=EscrowDealResponse, status_code=201)
async def create_deal_intent(
    payload: EscrowDealCreate,
    user: CurrentUser,
    session: DbSession,
    identity_provider: IdentityProvider,
    idempotency_key: IdempotencyKey,
) -> EscrowDealResponse:
    _require_testnet()
    actor_id = user.id
    request_hash = _request_hash(_payload_dict(payload))
    try:
        replay = await _load_idempotent_resource(session, actor_id=actor_id,
            operation="create_deal_intent",
            key=idempotency_key, request_sha256=request_hash, model=EscrowDeal)
        if replay is not None:
            if replay.buyer_id != actor_id:
                raise HTTPException(status_code=404, detail="Escrow deal not found")
            return await _deal_projection(session, replay, actor_id)
        intent = await session.scalar(select(EscrowListingIntent).where(
            EscrowListingIntent.marketplace_listing_id == payload.listing_id))
        if intent is None or intent.status not in {"intent_only", "active"}:
            raise HTTPException(status_code=404, detail="Escrow listing intent not found")
        if intent.seller_id == actor_id:
            raise HTTPException(status_code=409, detail="A seller cannot buy their own listing")
        if not intent.listing_key or not intent.collection_address_snapshot:
            raise HTTPException(
                status_code=409,
                detail="Escrow listing is missing immutable collection or listing identity",
            )
        listing = await session.scalar(
            select(Listing).where(Listing.id == intent.marketplace_listing_id)
        )
        if (
            listing is None
            or listing.status is not ListingStatus.ACTIVE
            or listing.asset_id != intent.asset_id
        ):
            raise HTTPException(status_code=409, detail="Underlying listing is no longer active")
        if (
            listing.price_currency is not PriceCurrency.TON
            or listing.price_amount != intent.price_amount
        ):
            raise HTTPException(
                status_code=409,
                detail="Active listing price/currency changed after the escrow intent",
            )
        asset = await session.get(NFTAsset, intent.asset_id)
        if (
            asset is None
            or asset.owner_id != intent.seller_id
            or asset.network != "testnet"
            or asset.asset_type is not AssetType.TON_NFT
            or asset.verification_status is not AssetVerificationStatus.VERIFIED
            or asset.item_address is None
            or asset.collection_id is None
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_asset_not_verified"},
            )
        try:
            asset_item_address = normalize_address(asset.item_address)
        except AddressError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_asset_not_verified"},
            ) from exc
        collection = await session.get(NFTCollection, asset.collection_id)
        if collection is None or collection.network != "testnet":
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_collection_not_verified"},
            )
        try:
            asset_collection_address = normalize_address(collection.address)
        except AddressError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_collection_not_verified"},
            ) from exc
        if (
            asset.id != intent.asset_id
            or asset_item_address != intent.item_address
            or asset_collection_address != intent.collection_address_snapshot
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_identity_snapshot_mismatch"},
            )
        asset_snapshot = {
            "id": asset.id,
            "owner_id": asset.owner_id,
            "network": asset.network,
            "asset_type": asset.asset_type,
            "verification_status": asset.verification_status,
            "item_address": asset_item_address,
            "collection_id": asset.collection_id,
            "collection_address": asset_collection_address,
        }
        # Require identity evidence from the seller intent before repeating a
        # trusted, same-block proof immediately before the reservation.
        try:
            initial_identity = validate_nft_identity_snapshot(
                intent.nft_identity_snapshot_json,
                intent.nft_identity_snapshot_sha256,
            )
        except NFTIdentityEvidenceError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_identity_snapshot_required"},
            ) from exc
        if (
            initial_identity.get("item_address") != intent.item_address
            or initial_identity.get("collection_address") != intent.collection_address_snapshot
            or initial_identity.get("owner_address") != intent.seller_address_snapshot
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_identity_snapshot_mismatch"},
            )

        # Capture the immutable facts, then end the read transaction before
        # proof-provider I/O. Re-lock/revalidate afterwards.
        intent_id = intent.id
        intent_snapshot = {
            "marketplace_listing_id": intent.marketplace_listing_id,
            "asset_id": intent.asset_id,
            "seller_id": intent.seller_id,
            "listing_key": intent.listing_key,
            "item_address": intent.item_address,
            "collection_address_snapshot": intent.collection_address_snapshot,
            "seller_address_snapshot": intent.seller_address_snapshot,
            "price_amount": intent.price_amount,
            "price_currency": intent.price_currency,
            "nft_identity_snapshot_json": intent.nft_identity_snapshot_json,
            "nft_identity_snapshot_sha256": intent.nft_identity_snapshot_sha256,
        }
        listing_snapshot = {
            "id": listing.id,
            "asset_id": listing.asset_id,
            "seller_id": listing.seller_id,
            "price_amount": listing.price_amount,
            "price_currency": listing.price_currency,
        }
        await session.rollback()
        identity_snapshot = await _verify_escrow_nft_identity(
            identity_provider,
            item_address=str(intent_snapshot["item_address"]),
            collection_address=str(intent_snapshot["collection_address_snapshot"]),
            expected_owner_address=str(intent_snapshot["seller_address_snapshot"]),
        )
        if not same_nft_identity_anchor(initial_identity, identity_snapshot):
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_identity_changed_since_listing"},
            )

        # Match ordinary order reservation: buyer User -> Listing -> wallet ->
        # NFTAsset. Lock marketplace rows before the asset so an Order and an
        # EscrowDeal cannot form an asset/listing lock cycle. No locks span proof I/O.
        await session.scalar(select(User.id).where(User.id == actor_id).with_for_update())
        listing = await session.scalar(
            select(Listing)
            .where(Listing.id == intent_snapshot["marketplace_listing_id"])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            listing is None
            or listing.status is not ListingStatus.ACTIVE
            or any(
                getattr(listing, field) != value
                for field, value in listing_snapshot.items()
            )
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_listing_changed_during_proof"},
            )

        buyer_wallet, buyer_address = await _verified_wallet(
            session,
            user_id=actor_id,
            wallet_id=payload.buyer_wallet_id,
            lock=True,
        )

        asset = await session.scalar(
            select(NFTAsset)
            .where(NFTAsset.id == intent_snapshot["asset_id"])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if (
            asset is None
            or asset.owner_id != asset_snapshot["owner_id"]
            or asset.network != asset_snapshot["network"]
            or asset.asset_type != asset_snapshot["asset_type"]
            or asset.verification_status != asset_snapshot["verification_status"]
            or asset.collection_id != asset_snapshot["collection_id"]
            or asset.item_address is None
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_asset_changed_during_proof"},
            )
        try:
            locked_asset_item_address = normalize_address(asset.item_address)
        except AddressError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_asset_changed_during_proof"},
            ) from exc
        if locked_asset_item_address != asset_snapshot["item_address"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_identity_snapshot_mismatch"},
            )

        collection = await session.scalar(
            select(NFTCollection)
            .where(NFTCollection.id == asset_snapshot["collection_id"])
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if collection is None or collection.network != "testnet":
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_collection_changed_during_proof"},
            )
        try:
            locked_collection_address = normalize_address(collection.address)
        except AddressError as exc:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_collection_changed_during_proof"},
            ) from exc
        if locked_collection_address != asset_snapshot["collection_address"]:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_nft_identity_snapshot_mismatch"},
            )

        intent = await session.scalar(
            select(EscrowListingIntent)
            .where(EscrowListingIntent.id == intent_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        if intent is None or intent.status not in {"intent_only", "active"}:
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_intent_changed_during_proof"},
            )
        if any(
            getattr(intent, field) != value
            for field, value in intent_snapshot.items()
        ):
            raise HTTPException(
                status_code=409,
                detail={"code": "escrow_intent_snapshot_changed_during_proof"},
            )

        principal = intent.price_amount * _NANOTON
        if principal <= 0 or principal != principal.to_integral_value():
            raise HTTPException(status_code=409, detail="TON principal precision is invalid")
        deal = EscrowDeal(
            id=uuid4(),
            listing_intent_id=intent.id,
            marketplace_listing_id=intent.marketplace_listing_id,
            listing_key_snapshot=intent.listing_key,
            seller_id=intent.seller_id,
            buyer_id=actor_id,
            buyer_wallet_id=buyer_wallet.id,
            network="testnet",
            deal_salt=secrets.token_hex(32),
            collection_address_snapshot=intent.collection_address_snapshot,
            nft_identity_snapshot_json=identity_snapshot,
            nft_identity_snapshot_sha256=str(identity_snapshot["evidence_sha256"]),
            contract_address=None,
            contract_abi_version=None,
            item_address=intent.item_address,
            seller_address_snapshot=intent.seller_address_snapshot,
            buyer_address_snapshot=buyer_address,
            price_amount=intent.price_amount,
            price_currency="TON",
            principal_nanotons=principal,
            status=EscrowDealStatus.INTENT_CREATED.value,
            last_chain_seqno=None,
            idempotency_key=idempotency_key,
        )
        # Freeze all constructor parameters and derive the deterministic contract
        # address before reserving the underlying marketplace listing. Missing
        # authority keys or invalid ABI artifacts fail without locking the NFT.
        snapshot_values, snapshot_sha256, predicted_address, abi_version = (
            _initial_deployment_snapshot(deal)
        )
        deal.deployment_snapshot_json = snapshot_values
        deal.deployment_snapshot_sha256 = snapshot_sha256
        deal.deployment_snapshot_version = _DEPLOYMENT_SNAPSHOT_VERSION
        deal.deployment_snapshot_source = "pinned-dealescrow-v1"
        deal.contract_address = predicted_address
        deal.contract_abi_version = abi_version
        # The normal Order path locks this same Listing row. Reserve both
        # projections in the same transaction so one NFT cannot be sold twice.
        try:
            reserve_listing_for_escrow(listing, intent)
        except EscrowListingReservationConflict as exc:
            raise HTTPException(status_code=409, detail=str(exc)) from exc
        session.add(deal)
        _add_idempotency_record(session, actor_id=actor_id, operation="create_deal_intent",
            key=idempotency_key,
            request_sha256=request_hash, resource_type="deal", resource_id=deal.id)
        await session.commit()
        await session.refresh(deal)
        return await _deal_projection(session, deal, actor_id)
    except IntegrityError:
        replay = await _idempotency_race_replay(session, actor_id=actor_id,
            operation="create_deal_intent",
            key=idempotency_key, request_sha256=request_hash, model=EscrowDeal)
        if replay.buyer_id != actor_id:
            raise HTTPException(status_code=404, detail="Escrow deal not found") from None
        return await _deal_projection(session, replay, actor_id)
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
    return EscrowPageResponse(items=[await _deal_projection(session, row,
        user.id) for row in rows], total=len(rows))


@router.get("/seller/deals", response_model=EscrowPageResponse)
async def list_seller_deals(user: CurrentUser, session: DbSession, limit: int = 20,
    offset: int = 0):
    rows = list((await session.scalars(select(EscrowDeal).where(EscrowDeal.seller_id == user.id)
        .order_by(EscrowDeal.created_at.desc(), EscrowDeal.id.desc()).offset(max(offset, 0))
        .limit(min(max(limit, 1), 50)))).all())
    return EscrowPageResponse(items=[await _deal_projection(session, row,
        user.id) for row in rows], total=len(rows))


async def _prepare_action(
    deal_id: UUID, action: EscrowWalletAction, user: User,
    session: AsyncSession,
    identity_provider: PytoniqTONTestnetEscrowProvider, idempotency_key: str,
    request_context: dict[str, object] | None = None,
):
    _require_testnet()
    actor_id = user.id
    # Do not hold a database row lock across ownership-provider calls.
    deal = await session.scalar(select(EscrowDeal).where(
        deal_id == EscrowDeal.id,
        (EscrowDeal.buyer_id == actor_id) | (EscrowDeal.seller_id == actor_id),
    ))
    if deal is None:
        raise HTTPException(status_code=404, detail="Escrow deal not found")
    validated_status = deal.status
    immutable_snapshot_fields = (
        "id", "buyer_id", "seller_id", "listing_key_snapshot", "item_address",
        "collection_address_snapshot", "seller_address_snapshot", "buyer_address_snapshot",
        "principal_nanotons", "deal_salt", "network",
        "nft_identity_snapshot_json", "nft_identity_snapshot_sha256",
    )
    validated_snapshot = {
        field: getattr(deal, field, None) for field in immutable_snapshot_fields
    }
    ownership_check: tuple[str, str] | None = None

    # Idempotency replay precedes current-state eligibility checks. Once an
    # action exists, a retry must resolve to that same durable action even if
    # the deal has since moved to another state.
    existing_action = await session.scalar(
        select(EscrowWalletActionRecord)
        .where(
            EscrowWalletActionRecord.actor_id == actor_id,
            EscrowWalletActionRecord.action_type == action.value,
            EscrowWalletActionRecord.idempotency_key == idempotency_key,
        )
        .with_for_update()
    )
    if existing_action is not None:
        intent_for_replay = await session.get(EscrowListingIntent, deal.listing_intent_id)
        if intent_for_replay is None:
            raise HTTPException(status_code=404, detail="Escrow listing intent not found")
        replay_wallet_id = (
            intent_for_replay.seller_wallet_id
            if actor_id == deal.seller_id
            else deal.buyer_wallet_id
        )
        replay_wallet_address = (
            deal.seller_address_snapshot
            if actor_id == deal.seller_id
            else deal.buyer_address_snapshot
        )
        replay_hash = canonical_request_sha256({
            "actor_id": str(actor_id),
            "deal_id": str(deal.id),
            "action_type": action.value,
            "network": deal.network,
            "wallet_id": str(replay_wallet_id),
            "wallet_address": replay_wallet_address,
            "listing_key": deal.listing_key_snapshot,
            "item_address": deal.item_address,
            "collection_address": deal.collection_address_snapshot,
            "seller_address": deal.seller_address_snapshot,
            "buyer_address": deal.buyer_address_snapshot,
            "principal_nanotons": str(deal.principal_nanotons),
            "deal_salt": deal.deal_salt,
            "context": request_context or {},
        })
        if (
            existing_action.deal_id != deal.id
            or existing_action.request_sha256 != replay_hash
        ):
            await session.rollback()
            raise HTTPException(status_code=409, detail={"code": "idempotency_payload_conflict"})
        if getattr(existing_action, "unsigned_payload_json", None) is not None:
            # Return the byte-for-byte persisted payload on every exact retry, even
            # if its chain submission is being reconciled by another worker.
            return _prepared_action_response(existing_action)
        if existing_action.status == "blocked_abi":
            replay_error_code = (
                existing_action.last_error_code or "deployment_snapshot_incomplete"
            )
            raise HTTPException(status_code=503, detail={
                "code": replay_error_code,
                "action_id": str(existing_action.id),
                "action_status": existing_action.status,
                "message": "This durable action remains blocked; no new payload was generated",
            })
        if existing_action.status not in {"pending"}:
            raise HTTPException(
                status_code=409,
                detail={
                    "code": "escrow_action_not_retryable",
                    "action_id": str(existing_action.id),
                    "action_status": existing_action.status,
                },
            )

    seller_states = {
        EscrowWalletAction.CREATE_DEAL_ESCROW: "intent_created",
        EscrowWalletAction.ACTIVATE_DEAL: "intent_created",
        EscrowWalletAction.DEPOSIT_NFT: "awaiting_nft",
        EscrowWalletAction.WITHDRAW_UNSOLD_NFT: "expired",
    }
    buyer_states = {
        EscrowWalletAction.FUND_DEAL: {"awaiting_buyer_funds"},
        EscrowWalletAction.ACCEPT_DEAL: {"funded_review"},
        EscrowWalletAction.OPEN_DISPUTE: {"funded_review", "delivered_dispute_window"},
    }
    if action in seller_states:
        if deal.seller_id != actor_id or deal.status != seller_states[action]:
            raise HTTPException(status_code=409,
                detail="Seller action is not available for this deal state")
        intent = await session.get(EscrowListingIntent, deal.listing_intent_id)
        if intent is None:
            raise HTTPException(status_code=404, detail="Escrow listing intent not found")
        wallet, wallet_address = await _verified_wallet(
            session, user_id=actor_id, wallet_id=intent.seller_wallet_id,
        )
        if wallet_address != deal.seller_address_snapshot:
            raise HTTPException(status_code=409,
                detail="Verified seller wallet snapshot has changed")
        if action in {
            EscrowWalletAction.CREATE_DEAL_ESCROW,
            EscrowWalletAction.ACTIVATE_DEAL,
            EscrowWalletAction.DEPOSIT_NFT,
        }:
            ownership_check = (deal.item_address, deal.seller_address_snapshot)
        if action is EscrowWalletAction.WITHDRAW_UNSOLD_NFT:
            if not deal.contract_address:
                raise HTTPException(status_code=503,
                    detail={"code": "contract_address_unavailable"})
            ownership_check = (deal.item_address, deal.contract_address)
    elif action in buyer_states:
        if deal.buyer_id != actor_id or deal.status not in buyer_states[action]:
            raise HTTPException(status_code=409,
                detail="Buyer action is not available for this deal state")
        wallet, wallet_address = await _verified_wallet(
            session, user_id=actor_id, wallet_id=deal.buyer_wallet_id,
        )
        if wallet_address != deal.buyer_address_snapshot:
            raise HTTPException(status_code=409,
                detail="Verified buyer wallet snapshot has changed")
    elif action is EscrowWalletAction.RETURN_NFT_TO_ESCROW:
        if deal.buyer_id != actor_id or deal.status != "disputed":
            raise HTTPException(status_code=409,
                detail="Buyer NFT return is not available in this deal state")
        wallet, wallet_address = await _verified_wallet(
            session, user_id=actor_id, wallet_id=deal.buyer_wallet_id,
        )
        if wallet_address != deal.buyer_address_snapshot:
            raise HTTPException(status_code=409,
                detail="Verified buyer wallet snapshot has changed")
        ownership_check = (deal.item_address, deal.buyer_address_snapshot)
    else:
        raise HTTPException(status_code=409, detail="Unsupported escrow action")

    try:
        identity_snapshot = validate_nft_identity_snapshot(
            deal.nft_identity_snapshot_json,
            deal.nft_identity_snapshot_sha256,
        )
    except NFTIdentityEvidenceError as exc:
        raise HTTPException(
            status_code=503,
            detail={"code": "escrow_nft_identity_snapshot_required"},
        ) from exc
    if (
        identity_snapshot.get("item_address") != deal.item_address
        or identity_snapshot.get("collection_address") != deal.collection_address_snapshot
        or identity_snapshot.get("owner_address") != deal.seller_address_snapshot
    ):
        raise HTTPException(
            status_code=409,
            detail={"code": "escrow_nft_identity_snapshot_mismatch"},
        )

    if not deal.collection_address_snapshot:
        raise HTTPException(status_code=503, detail={"code": "nft_collection_snapshot_unavailable"})
    intent = await session.get(EscrowListingIntent, deal.listing_intent_id)
    if intent is None:
        raise HTTPException(status_code=404, detail="Escrow listing intent not found")
    validated_wallet_id = wallet.id
    validated_wallet_address = wallet_address
    # Re-prove immutable item/collection identity before every new wallet action.
    # Owner-sensitive actions additionally require the expected owner at this block.
    # End the read transaction before provider I/O so no row locks span network calls.
    await session.rollback()
    current_identity = await _verify_escrow_nft_identity(
        identity_provider,
        item_address=str(validated_snapshot["item_address"]),
        collection_address=str(validated_snapshot["collection_address_snapshot"]),
        expected_owner_address=ownership_check[1] if ownership_check is not None else None,
        minimum_masterchain_seqno=int(identity_snapshot["masterchain_seqno"]),
    )
    if not same_nft_identity_anchor(identity_snapshot, current_identity):
        raise HTTPException(
            status_code=409,
            detail={"code": "escrow_nft_identity_changed_since_snapshot"},
        )

    # Reacquire the deal lock only after external identity proof has finished.
    locked_deal = await session.scalar(
        select(EscrowDeal)
        .where(
            EscrowDeal.id == validated_snapshot["id"],
            (EscrowDeal.buyer_id == actor_id) | (EscrowDeal.seller_id == actor_id),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if locked_deal is None or locked_deal.status != validated_status:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "escrow_deal_changed_during_validation"}
        )
    if any(
        getattr(locked_deal, field) != value
        for field, value in validated_snapshot.items()
    ):
        await session.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "escrow_deal_snapshot_changed"}
        )
    deal = locked_deal
    wallet, wallet_address = await _verified_wallet(
        session, user_id=actor_id, wallet_id=validated_wallet_id
    )
    if wallet_address != validated_wallet_address:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "escrow_wallet_changed_during_validation"}
        )
    action_hash = canonical_request_sha256({
        "actor_id": str(actor_id),
        "deal_id": str(deal.id),
        "action_type": action.value,
        "network": deal.network,
        "wallet_id": str(wallet.id),
        "wallet_address": wallet_address,
        "listing_key": deal.listing_key_snapshot,
        "item_address": deal.item_address,
        "collection_address": deal.collection_address_snapshot,
        "seller_address": deal.seller_address_snapshot,
        "buyer_address": deal.buyer_address_snapshot,
        "principal_nanotons": str(deal.principal_nanotons),
        "deal_salt": deal.deal_salt,
        "context": request_context or {},
    })
    try:
        action_record, created = await create_or_replay_action(
            session, actor_id=actor_id, deal_id=deal.id, action_type=action.value,
            idempotency_key=idempotency_key, request_sha256=action_hash,
        )
    except EscrowActionConflict as exc:
        await session.rollback()
        raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
    except IntegrityError:
        await session.rollback()
        try:
            action_record, created = await create_or_replay_action(
                session, actor_id=actor_id, deal_id=deal.id, action_type=action.value,
                idempotency_key=idempotency_key, request_sha256=action_hash,
            )
        except EscrowActionConflict as exc:
            await session.rollback()
            raise HTTPException(status_code=409, detail={"code": str(exc)}) from exc
        except IntegrityError as exc:
            await session.rollback()
            raise HTTPException(
                status_code=409, detail={"code": "escrow_action_idempotency_race"}
            ) from exc

    # Commit the durable action identity before constructing its response. No
    # signing, message submission or network broadcast happens in this endpoint.
    if created or action_record.status == "pending":
        await session.commit()
        await session.refresh(action_record)

    if getattr(action_record, "unsigned_payload_json", None) is not None:
        return _prepared_action_response(action_record)
    if action_record.status == "blocked_abi":
        raise HTTPException(status_code=503, detail={
            "code": action_record.last_error_code or "contract_abi_pending",
            "action_id": str(action_record.id),
            "action_status": action_record.status,
            "message": "This durable action is blocked and has no unsigned payload",
        })
    if action_record.status != "pending":
        raise HTTPException(
            status_code=409,
            detail={"code": "escrow_action_not_retryable", "action_id": str(action_record.id)},
        )

    snapshot, missing_snapshot_fields = _build_deployment_snapshot(
        deal,
        allow_initial_state=(action is EscrowWalletAction.CREATE_DEAL_ESCROW),
    )
    if snapshot is None:
        error_code = (
            "deployment_snapshot_incomplete"
            if "deployment_snapshot_json" in missing_snapshot_fields
            or "finalized_getter_snapshot" in missing_snapshot_fields
            or "deployment_snapshot_sha256" in missing_snapshot_fields
            else "deployment_snapshot_integrity_failed"
        )
        action_record.status = "blocked_abi"
        action_record.last_error_code = error_code
        await session.commit()
        raise HTTPException(status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail={
            "code": error_code,
            "action_id": str(action_record.id),
            "action_status": action_record.status,
            "missing_fields": list(missing_snapshot_fields),
            "message": (
                "Required immutable terms or independently verified getter state are unavailable"
            ),
        })

    try:
        if action_record.attempt_id is None:
            action_record.attempt_id = uuid4().hex
        query_id = _action_query_id(action, snapshot, action_record)
        if action_record.attempt_count == 0:
            action_record.attempt_count = 1
        # Persist attempt/query identity before local serialization. A process crash
        # can resume the same durable action rather than minting a second query ID.
        await session.commit()
        await session.refresh(action_record)

        adapter = PinnedTONEscrowContractAdapter()
        reason_hash: int | None = None
        if action is EscrowWalletAction.OPEN_DISPUTE:
            reason = (request_context or {}).get("reason")
            if not isinstance(reason, str) or len(reason.strip()) < 5:
                raise EscrowContractABIUnavailable("a bounded dispute reason is required")
            reason_hash = int(hashlib.sha256(reason.encode("utf-8")).hexdigest(), 16)

        prepared = await adapter.prepare_transaction(
            action,
            actor_wallet=wallet,
            resource_id=str(deal.id),
            deal_snapshot=snapshot,
            reason_hash=reason_hash,
            query_id=query_id,
        )
        payload_dict = prepared.to_tonconnect_dict()
        unsigned_bocs = {
            "format": "tonconnect-message-bocs-v1",
            "network": "testnet",
            "messages": [
                {
                    "index": index,
                    "address": message.address,
                    "amount_nanotons": message.amount,
                    "payload_boc_base64": message.payload,
                    "state_init_boc_base64": message.state_init,
                }
                for index, message in enumerate(prepared.messages)
            ],
        }
        if not unsigned_bocs["messages"] or not any(
            item["payload_boc_base64"] or item["state_init_boc_base64"]
            for item in unsigned_bocs["messages"]
        ):
            raise EscrowContractABIUnavailable("adapter returned no exact unsigned BOC")
        action_record.unsigned_payload_json = payload_dict
        action_record.unsigned_payload_sha256 = _canonical_sha256(payload_dict)
        action_record.unsigned_bocs_json = unsigned_bocs
        action_record.unsigned_boc_sha256 = _canonical_sha256(unsigned_bocs)
        action_record.unsigned_boc_ref = (
            f"db://escrow_wallet_actions/{action_record.id}/unsigned_bocs_json"
        )
        action_record.status = "prepared"
        action_record.last_error_code = None
        action_record.next_retry_at = None
        action_record.lease_token = None
        action_record.lease_until = None
        await session.commit()
        await session.refresh(action_record)
        return _prepared_action_response(action_record)
    except EscrowContractABIUnavailable as exc:
        action_record.status = "blocked_abi"
        action_record.last_error_code = "contract_abi_unavailable"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "contract_abi_unavailable",
                "action_id": str(action_record.id),
                "action_status": action_record.status,
                "message": "The pinned DealEscrow adapter refused transaction preparation",
            },
        ) from exc
    except HTTPException:
        raise
    except Exception as exc:
        # Do not expose provider/client details or BOCs in the error response. There
        # is deliberately no signing or broadcast in this handler.
        action_record.status = "manual_review"
        action_record.last_error_code = "unsigned_payload_persistence_failed"
        await session.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={
                "code": "unsigned_payload_persistence_failed",
                "action_id": str(action_record.id),
                "message": "Unsigned transaction evidence could not be persisted safely",
            },
        ) from exc


@router.post("/deals/{deal_id}/prepare/create-deal-escrow",
    response_model=EscrowTransactionPreparationResponse)
async def prepare_deal_escrow(deal_id: UUID, user: CurrentUser, session: DbSession,
    identity_provider: IdentityProvider, idempotency_key: IdempotencyKey):
    return await _prepare_action(deal_id, EscrowWalletAction.CREATE_DEAL_ESCROW, user, session,
        identity_provider, idempotency_key)


@router.post(
    "/deals/{deal_id}/prepare/activate-deal",
    response_model=EscrowTransactionPreparationResponse,
)
async def prepare_deal_activation(
    deal_id: UUID,
    request: Request,
    user: CurrentUser,
    session: DbSession,
    identity_provider: IdentityProvider,
    idempotency_key: IdempotencyKey,
):
    """Prepare seller activation only after a trusted LiteServer proves deployment.

    The endpoint never signs or broadcasts. It checks the deterministic escrow
    address, pinned code hash and immutable constructor terms at a trust-level-0
    masterchain head, then persists the getter snapshot before building the
    idempotent unsigned ActivateDeal payload.
    """
    _require_testnet()
    actor_id = user.id

    existing = await session.scalar(
        select(EscrowWalletActionRecord)
        .where(
            EscrowWalletActionRecord.actor_id == actor_id,
            EscrowWalletActionRecord.action_type == EscrowWalletAction.ACTIVATE_DEAL.value,
            EscrowWalletActionRecord.idempotency_key == idempotency_key,
        )
        .with_for_update()
    )
    if existing is not None:
        return await _prepare_action(
            deal_id, EscrowWalletAction.ACTIVATE_DEAL, SimpleNamespace(id=actor_id), session,
            identity_provider, idempotency_key,
        )

    deal = await session.scalar(
        select(EscrowDeal).where(
            EscrowDeal.id == deal_id,
            EscrowDeal.seller_id == actor_id,
        )
    )
    if deal is None:
        raise HTTPException(status_code=404, detail={"code": "escrow_deal_not_found"})
    if deal.status != EscrowDealStatus.INTENT_CREATED.value:
        raise HTTPException(status_code=409, detail={"code": "activation_state_invalid"})
    if (
        not deal.contract_address
        or not isinstance(deal.deployment_snapshot_json, dict)
        or not isinstance(deal.deployment_snapshot_sha256, str)
        or _canonical_sha256(deal.deployment_snapshot_json) != deal.deployment_snapshot_sha256
    ):
        raise HTTPException(
            status_code=503, detail={"code": "deployment_snapshot_incomplete"}
        )

    provider = getattr(request.app.state, "ton_escrow_finality_provider", None)
    if provider is None:
        raise HTTPException(
            status_code=503, detail={"code": "escrow_finality_provider_unavailable"}
        )

    expected_contract = deal.contract_address
    expected_snapshot_sha = deal.deployment_snapshot_sha256
    deployment_proof_input = SimpleNamespace(
        network=deal.network,
        contract_address=expected_contract,
        deployment_snapshot_json=dict(deal.deployment_snapshot_json),
        deployment_snapshot_sha256=expected_snapshot_sha,
    )
    await session.rollback()
    try:
        getter, masterchain_seqno, masterchain_block_hash, provider_id = (
            await provider.verify_deployed_account(deployment_proof_input)  # type: ignore[arg-type]
        )
    except Exception as exc:
        # Provider details and proof material are deliberately not returned.
        from app.escrow.provider import EscrowProviderInvalidEvidence, EscrowProviderUnavailable

        if isinstance(exc, EscrowProviderInvalidEvidence):
            raise HTTPException(
                status_code=409, detail={"code": "escrow_deployment_not_proven"}
            ) from exc
        if isinstance(exc, EscrowProviderUnavailable):
            raise HTTPException(
                status_code=503, detail={"code": "escrow_finality_provider_unavailable"}
            ) from exc
        raise HTTPException(
            status_code=503, detail={"code": "escrow_deployment_proof_failed"}
        ) from exc

    if (
        getter.get("contract_state") != 0
        or getter.get("nft_in_escrow") is not False
        or getter.get("principal_locked") is not False
    ):
        raise HTTPException(
            status_code=409, detail={"code": "escrow_contract_not_awaiting_activation"}
        )
    if (
        isinstance(masterchain_seqno, bool)
        or not isinstance(masterchain_seqno, int)
        or masterchain_seqno <= 0
        or not isinstance(masterchain_block_hash, str)
        or not _HEX_256.fullmatch(masterchain_block_hash)
        or not isinstance(provider_id, str)
        or not provider_id.strip()
        or any(field not in getter for field in _GETTER_SNAPSHOT_FIELDS)
    ):
        raise HTTPException(
            status_code=503, detail={"code": "escrow_deployment_proof_incomplete"}
        )

    locked_deal = await session.scalar(
        select(EscrowDeal)
        .where(
            EscrowDeal.id == deal_id,
            EscrowDeal.seller_id == actor_id,
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if (
        locked_deal is None
        or locked_deal.status != EscrowDealStatus.INTENT_CREATED.value
        or locked_deal.contract_address != expected_contract
        or locked_deal.deployment_snapshot_sha256 != expected_snapshot_sha
    ):
        await session.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "escrow_deal_changed_during_proof"}
        )
    current_seqno = locked_deal.getter_snapshot_masterchain_seqno or 0
    if current_seqno > masterchain_seqno:
        await session.rollback()
        raise HTTPException(
            status_code=409, detail={"code": "stale_escrow_getter_proof"}
        )

    getter_json = dict(getter)
    locked_deal.getter_snapshot_json = getter_json
    locked_deal.getter_snapshot_sha256 = _canonical_sha256(getter_json)
    locked_deal.getter_snapshot_masterchain_seqno = masterchain_seqno
    locked_deal.getter_snapshot_block_hash = masterchain_block_hash
    locked_deal.getter_snapshot_provider = provider_id
    locked_deal.getter_snapshot_observed_at = datetime.now(UTC)
    await session.commit()

    return await _prepare_action(
        deal_id, EscrowWalletAction.ACTIVATE_DEAL, SimpleNamespace(id=actor_id), session,
        identity_provider, idempotency_key,
    )


@router.post("/deals/{deal_id}/prepare/deposit-nft",
    response_model=EscrowTransactionPreparationResponse)
async def prepare_nft_deposit(deal_id: UUID, user: CurrentUser, session: DbSession,
    identity_provider: IdentityProvider,
    idempotency_key: IdempotencyKey):
    return await _prepare_action(
        deal_id, EscrowWalletAction.DEPOSIT_NFT, user, session, identity_provider, idempotency_key
    )


@router.post("/deals/{deal_id}/prepare/funding",
    response_model=EscrowTransactionPreparationResponse)
async def prepare_buyer_funding(deal_id: UUID, user: CurrentUser, session: DbSession,
    identity_provider: IdentityProvider,
    idempotency_key: IdempotencyKey):
    return await _prepare_action(
        deal_id, EscrowWalletAction.FUND_DEAL, user, session, identity_provider, idempotency_key
    )


@router.post("/deals/{deal_id}/prepare/accept", response_model=EscrowTransactionPreparationResponse)
async def prepare_buyer_acceptance(deal_id: UUID, user: CurrentUser, session: DbSession,
    identity_provider: IdentityProvider,
    idempotency_key: IdempotencyKey):
    return await _prepare_action(
        deal_id, EscrowWalletAction.ACCEPT_DEAL, user, session, identity_provider, idempotency_key
    )


@router.post("/deals/{deal_id}/prepare/dispute",
    response_model=EscrowTransactionPreparationResponse)
async def prepare_dispute(
    deal_id: UUID, payload: EscrowDisputeCreate, user: CurrentUser,
    session: DbSession, identity_provider: IdentityProvider,
    idempotency_key: IdempotencyKey,
):
    return await _prepare_action(
        deal_id,
        EscrowWalletAction.OPEN_DISPUTE,
        user,
        session,
        identity_provider,
        idempotency_key,
        {"reason": payload.reason, "reason_code": payload.reason_code},
    )


@router.post("/deals/{deal_id}/prepare/nft-return",
    response_model=EscrowTransactionPreparationResponse)
async def prepare_buyer_nft_return(
    deal_id: UUID, user: CurrentUser, session: DbSession, identity_provider: IdentityProvider,
    idempotency_key: IdempotencyKey,
):
    return await _prepare_action(deal_id, EscrowWalletAction.RETURN_NFT_TO_ESCROW, user,
        session, identity_provider, idempotency_key)


@router.post("/deals/{deal_id}/prepare/withdraw-unsold-nft",
    response_model=EscrowTransactionPreparationResponse)
async def prepare_unsold_nft_withdrawal(
    deal_id: UUID, user: CurrentUser, session: DbSession, identity_provider: IdentityProvider,
    idempotency_key: IdempotencyKey,
):
    return await _prepare_action(
        deal_id, EscrowWalletAction.WITHDRAW_UNSOLD_NFT, user, session,
        identity_provider, idempotency_key)


@router.post(
    "/wallet-references",
    response_model=EscrowWalletReferenceResponse,
    status_code=status.HTTP_200_OK,
)
async def submit_wallet_reference(
    payload: EscrowWalletReferenceInput,
    user: CurrentUser,
    session: DbSession,
    idempotency_key: IdempotencyKey,
) -> EscrowWalletReferenceResponse:
    """Persist one client-reported wallet reference as an untrusted reconciliation hint.

    This route deliberately does not call a blockchain provider, mark the action
    finalized, update DealEscrow state, or release a marketplace listing. Only the
    trust-level-zero observer can reconcile a reported transaction independently.
    """

    _require_testnet()
    actor_id = user.id
    normalized_reference = payload.reference.strip()
    if not normalized_reference:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail={"code": "empty_wallet_reference"},
        )

    action = await session.scalar(
        select(EscrowWalletActionRecord)
        .where(
            EscrowWalletActionRecord.id == payload.action_id,
            EscrowWalletActionRecord.actor_id == actor_id,
            EscrowWalletActionRecord.action_type == payload.action,
            EscrowWalletActionRecord.network == "testnet",
        )
        .with_for_update()
    )
    if action is None:
        # Do not disclose whether another user's action ID exists.
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"code": "escrow_action_not_found"},
        )

    reference_sha256 = hashlib.sha256(
        normalized_reference.encode("utf-8")
    ).hexdigest()
    request_sha256 = canonical_request_sha256(
        {
            "actor_id": str(actor_id),
            "action_id": str(action.id),
            "action": payload.action,
            "reference_sha256": reference_sha256,
        }
    )
    operation = "wallet_reference"

    prior = await session.scalar(
        select(EscrowIdempotencyRecord)
        .where(
            EscrowIdempotencyRecord.actor_id == actor_id,
            EscrowIdempotencyRecord.operation == operation,
            EscrowIdempotencyRecord.idempotency_key == idempotency_key,
        )
        .with_for_update()
    )
    if prior is not None:
        if (
            prior.request_sha256 != request_sha256
            or prior.resource_type != "wallet_action"
            or prior.resource_id != action.id
        ):
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "idempotency_payload_conflict"},
            )
        if action.submission_reference_sha256 != reference_sha256:
            await session.rollback()
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail={"code": "stored_wallet_reference_conflict"},
            )
        return _wallet_reference_response(action)

    # Store the idempotency receipt in the same transaction as the untrusted hint.
    # A transaction reference can never write deal status or owner state.
    receipt = EscrowIdempotencyRecord(
        actor_id=actor_id,
        operation=operation,
        idempotency_key=idempotency_key,
        request_sha256=request_sha256,
        resource_type="wallet_action",
        resource_id=action.id,
    )
    session.add(receipt)
    try:
        record_submission_reference(action, reference=normalized_reference)
    except EscrowActionConflict as exc:
        if (
            str(exc) == "submission_reference_conflict"
            and action.status == "manual_review"
        ):
            # Persist the safety quarantine for a conflicting client claim, along
            # with this key's receipt. The canonical deal/listing state is untouched.
            await session.commit()
        else:
            await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": str(exc)},
        ) from exc

    try:
        await session.commit()
        await session.refresh(action)
    except IntegrityError as exc:
        await session.rollback()
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail={"code": "wallet_reference_idempotency_race"},
        ) from exc
    return _wallet_reference_response(action)


def _wallet_reference_response(
    action: EscrowWalletActionRecord,
) -> EscrowWalletReferenceResponse:
    reference_hash = action.submission_reference_sha256
    if (
        not isinstance(reference_hash, str)
        or not _HEX_256.fullmatch(reference_hash)
    ):
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "stored_wallet_reference_integrity_failed"},
        )
    if action.status == "manual_review":
        reconciliation_status = "manual_review"
    elif action.status == "finalized":
        reconciliation_status = "already_finalized"
    else:
        reconciliation_status = "awaiting_independent_chain_reconciliation"
    return EscrowWalletReferenceResponse(
        action_id=action.id,
        status=action.status,
        reference_sha256=reference_hash,
        reconciliation_status=reconciliation_status,
    )


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
async def blocked_legacy_withdrawal(
    payload: EscrowWithdrawalCreate, user: CurrentUser, session: DbSession,
    idempotency_key: IdempotencyKey,
):
    del payload, user, session, idempotency_key
    raise HTTPException(status_code=503, detail={"code": "contract_abi_pending"})
