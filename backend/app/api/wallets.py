import hashlib
import secrets
from collections.abc import Awaitable
from datetime import UTC, datetime, timedelta
from typing import Annotated, cast
from uuid import uuid4

from fastapi import APIRouter, Depends, HTTPException, status
from redis.asyncio import Redis
from redis.exceptions import RedisError
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.models import User, Wallet
from app.db.session import get_db_session
from app.wallets.proof import (
    CHALLENGE_TTL_SECONDS,
    WalletProofConfigurationError,
    WalletProofError,
    validate_proof_configuration,
    verify_wallet_proof,
)
from app.wallets.redis import get_redis_client
from app.wallets.schemas import (
    VerifyWalletProofRequest,
    WalletProofChallengeResponse,
    WalletResponse,
)

router = APIRouter(prefix="/wallets", tags=["wallets"])

_CHALLENGE_KEY_PREFIX = "wallet-proof:challenge:"
_CONSUME_CHALLENGE_SCRIPT = """
if redis.call("GET", KEYS[1]) == ARGV[1] then
    return redis.call("DEL", KEYS[1])
end
return 0
"""


def _challenge_key(payload: str) -> str:
    digest = hashlib.sha256(payload.encode("utf-8")).hexdigest()
    return f"{_CHALLENGE_KEY_PREFIX}{digest}"


def _require_proof_configuration() -> tuple[list[str], str]:
    settings = get_settings()
    try:
        validate_proof_configuration(
            settings.ton_connect_allowed_domains,
            settings.ton_connect_network,
        )
    except WalletProofConfigurationError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="TON Connect proof verification is not configured",
        ) from exc
    return settings.ton_connect_allowed_domains, settings.ton_connect_network


@router.post(
    "/proof/challenge",
    response_model=WalletProofChallengeResponse,
)
async def create_proof_challenge(
    user: Annotated[User, Depends(get_current_user)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> WalletProofChallengeResponse:
    _require_proof_configuration()
    try:
        for _ in range(3):
            payload = secrets.token_urlsafe(32)
            expires_at = datetime.now(UTC) + timedelta(seconds=CHALLENGE_TTL_SECONDS)
            stored = await redis.set(
                _challenge_key(payload),
                str(user.id),
                ex=CHALLENGE_TTL_SECONDS,
                nx=True,
            )
            if stored:
                return WalletProofChallengeResponse(
                    payload=payload,
                    expires_at=expires_at.isoformat(),
                )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Wallet proof challenge storage is unavailable",
        ) from exc

    raise HTTPException(
        status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
        detail="Could not create a wallet proof challenge",
    )


@router.post("/proof/verify", response_model=WalletResponse)
async def verify_proof_and_link_wallet(
    payload: VerifyWalletProofRequest,
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
    redis: Annotated[Redis, Depends(get_redis_client)],
) -> Wallet:
    allowed_domains, expected_network = _require_proof_configuration()
    key = _challenge_key(payload.proof.payload)
    try:
        challenge_user_id = await redis.get(key)
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Wallet proof challenge storage is unavailable",
        ) from exc

    if challenge_user_id != str(user.id):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired wallet proof",
        )

    try:
        verified = verify_wallet_proof(
            payload,
            allowed_domains=allowed_domains,
            expected_network=expected_network,
        )
    except WalletProofError as exc:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired wallet proof",
        ) from exc

    try:
        consumed = await cast(
            Awaitable[int],
            redis.eval(
                _CONSUME_CHALLENGE_SCRIPT,
                1,
                key,
                str(user.id),
            ),
        )
    except RedisError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Wallet proof challenge storage is unavailable",
        ) from exc

    if not consumed:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired wallet proof",
        )

    wallet = await session.scalar(
        select(Wallet)
        .where(
            Wallet.network == verified.network,
            Wallet.address == verified.address,
        )
        .with_for_update()
    )
    if wallet is not None and wallet.user_id != user.id:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This wallet is already linked to another account",
        )

    if wallet is None:
        wallet = Wallet(
            id=uuid4(),
            user_id=user.id,
            address=verified.address,
            network=verified.network,
            is_verified=True,
            is_primary=False,
        )
        session.add(wallet)
    else:
        wallet.is_verified = True

    try:
        await session.commit()
    except IntegrityError as exc:
        await session.rollback()
        if getattr(exc.orig, "constraint_name", None) != "uq_wallets_network_address":
            raise
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail="This wallet is already linked to another account",
        ) from exc

    await session.refresh(wallet)
    return wallet


@router.get("/me", response_model=list[WalletResponse])
async def get_my_wallets(
    user: Annotated[User, Depends(get_current_user)],
    session: Annotated[AsyncSession, Depends(get_db_session)],
) -> list[Wallet]:
    result = await session.scalars(
        select(Wallet)
        .where(Wallet.user_id == user.id)
        .order_by(Wallet.is_primary.desc(), Wallet.created_at.desc())
    )
    return list(result.all())
