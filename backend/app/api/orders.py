from typing import Annotated
from uuid import UUID

from fastapi import APIRouter, Depends, Header, HTTPException, Query, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.assets.ton_nft.dependencies import get_ton_nft_verifier
from app.assets.ton_nft.verifier import TONNFTVerifier
from app.auth.dependencies import get_current_user
from app.db.models import Order, OrderDeliveryAttempt, User
from app.db.session import get_db_session
from app.orders.schemas import (
    DeliveryAttemptResponse,
    DeliveryPrepareRequest,
    DeliverySubmissionRequest,
    OrderCreateRequest,
    OrderDeliveryStateResponse,
    OrderEventResponse,
    OrderListResponse,
    OrderResponse,
)
from app.orders.service import (
    OrderConflict,
    OrderVerificationUnavailable,
    cancel_order,
    create_order,
    get_order,
    get_order_delivery_state,
    list_user_orders,
    prepare_delivery,
    submit_delivery_candidate,
)

router = APIRouter(prefix="/orders", tags=["orders"])
DbSession = Annotated[AsyncSession, Depends(get_db_session)]
CurrentUser = Annotated[User, Depends(get_current_user)]
Verifier = Annotated[TONNFTVerifier, Depends(get_ton_nft_verifier)]


def _response(order: Order) -> OrderResponse:
    return OrderResponse(
        id=order.id,
        listing_id=order.listing_id,
        buyer_id=order.buyer_id,
        seller_id=order.seller_id,
        status=order.status,
        price_amount=order.price_amount,
        price_currency=order.price_currency,
        title=order.listing.title,
        asset_name=order.listing.asset.name,
        asset_type=order.listing.asset.asset_type,
        expires_at=order.expires_at,
        created_at=order.created_at,
        updated_at=order.updated_at,
        events=[OrderEventResponse.model_validate(event) for event in order.events],
    )


def _delivery_state_response(
    order: Order, attempt: OrderDeliveryAttempt | None
) -> OrderDeliveryStateResponse:
    attempt_response = None
    if attempt is not None:
        attempt_response = DeliveryAttemptResponse(
            id=attempt.id,
            status=attempt.status,
            network=attempt.network,
            item_address=attempt.item_address,
            seller_address=attempt.seller_address_snapshot,
            buyer_address=attempt.buyer_address_snapshot,
            query_id=str(attempt.query_id),
            prepared_at=attempt.prepared_at,
            deadline=attempt.deadline,
            submitted_at=attempt.submitted_at,
            candidate_transaction_hash=attempt.candidate_transaction_hash,
            transaction_hash=attempt.transaction_hash,
            trace_id=attempt.trace_id,
            masterchain_seqno=attempt.masterchain_seqno,
            verified_at=attempt.verified_at,
        )
    return OrderDeliveryStateResponse(
        order_id=order.id,
        order_status=order.status,
        attempt=attempt_response,
    )


@router.post("", response_model=OrderResponse, status_code=status.HTTP_201_CREATED)
async def create_order_route(
    payload: OrderCreateRequest,
    session: DbSession,
    user: CurrentUser,
    verifier: Verifier,
    idempotency_key: Annotated[str, Header(alias="Idempotency-Key", min_length=1, max_length=128)],
) -> OrderResponse:
    try:
        order_id = await create_order(
            session,
            buyer_id=user.id,
            listing_id=payload.listing_id,
            idempotency_key=idempotency_key,
            verifier=verifier,
        )
    except OrderVerificationUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except OrderConflict as exc:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail=str(exc)) from exc
    order = await get_order(session, order_id=order_id, user_id=user.id)
    if order is None:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Order unavailable"
        )
    return _response(order)


@router.get("", response_model=OrderListResponse)
async def list_orders(
    session: DbSession,
    user: CurrentUser,
    role: Annotated[str, Query(pattern="^(buyer|seller)$")] = "buyer",
    limit: Annotated[int, Query(ge=1, le=100)] = 20,
    offset: Annotated[int, Query(ge=0)] = 0,
) -> OrderListResponse:
    orders = await list_user_orders(
        session, user_id=user.id, role=role, limit=limit, offset=offset
    )
    return OrderListResponse(items=[_response(order) for order in orders])


@router.post("/{order_id}/delivery/prepare", response_model=OrderDeliveryStateResponse)
async def prepare_order_delivery(
    order_id: UUID,
    payload: DeliveryPrepareRequest,
    session: DbSession,
    user: CurrentUser,
    verifier: Verifier,
    idempotency_key: Annotated[
        str, Header(alias="Idempotency-Key", min_length=1, max_length=128)
    ],
) -> OrderDeliveryStateResponse:
    try:
        await prepare_delivery(
            session,
            order_id=order_id,
            seller_id=user.id,
            seller_wallet_id=payload.seller_wallet_id,
            idempotency_key=idempotency_key,
            verifier=verifier,
        )
    except OrderVerificationUnavailable as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, detail=str(exc)
        ) from exc
    except OrderConflict as exc:
        error_status = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Order not found"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=error_status, detail=str(exc)) from exc

    state = await get_order_delivery_state(
        session, order_id=order_id, user_id=user.id
    )
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    order, attempt = state
    return _delivery_state_response(order, attempt)


@router.post(
    "/{order_id}/delivery/submissions",
    response_model=OrderDeliveryStateResponse,
)
async def submit_order_delivery(
    order_id: UUID,
    payload: DeliverySubmissionRequest,
    session: DbSession,
    user: CurrentUser,
) -> OrderDeliveryStateResponse:
    try:
        await submit_delivery_candidate(
            session,
            order_id=order_id,
            seller_id=user.id,
            transaction_hash=payload.transaction_hash,
        )
    except OrderConflict as exc:
        error_status = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Order not found"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=error_status, detail=str(exc)) from exc

    state = await get_order_delivery_state(
        session, order_id=order_id, user_id=user.id
    )
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    order, attempt = state
    return _delivery_state_response(order, attempt)


@router.get("/{order_id}/delivery", response_model=OrderDeliveryStateResponse)
async def get_order_delivery(
    order_id: UUID,
    session: DbSession,
    user: CurrentUser,
) -> OrderDeliveryStateResponse:
    state = await get_order_delivery_state(
        session, order_id=order_id, user_id=user.id
    )
    if state is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    order, attempt = state
    return _delivery_state_response(order, attempt)


@router.get("/{order_id}", response_model=OrderResponse)
async def get_order_route(
    order_id: UUID, session: DbSession, user: CurrentUser
) -> OrderResponse:
    order = await get_order(session, order_id=order_id, user_id=user.id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return _response(order)


@router.post("/{order_id}/cancel", response_model=OrderResponse)
async def cancel_order_route(
    order_id: UUID, session: DbSession, user: CurrentUser
) -> OrderResponse:
    try:
        await cancel_order(session, order_id=order_id, buyer_id=user.id)
    except OrderConflict as exc:
        error_status = (
            status.HTTP_404_NOT_FOUND
            if str(exc) == "Order not found"
            else status.HTTP_409_CONFLICT
        )
        raise HTTPException(status_code=error_status, detail=str(exc)) from exc
    order = await get_order(session, order_id=order_id, user_id=user.id)
    if order is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Order not found")
    return _response(order)
