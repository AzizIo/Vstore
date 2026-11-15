"""Request-scoped dependencies for proof-gated escrow services."""

from collections.abc import AsyncIterator

from fastapi import HTTPException, status

from app.core.config import get_settings
from app.escrow.finality_provider import PytoniqTONTestnetEscrowProvider


async def get_escrow_nft_identity_provider() -> AsyncIterator[PytoniqTONTestnetEscrowProvider]:
    """Yield the trust-level-0 testnet provider used for NFT identity evidence.

    This dependency only creates an observer/proof client; it never signs,
    broadcasts, or submits a transaction. The provider enforces the explicit
    collection policy and fail-closed network constraints before returning proof.
    """
    settings = get_settings()
    if settings.ton_connect_network != "testnet":
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "escrow_nft_identity_requires_testnet"},
        )
    try:
        provider = PytoniqTONTestnetEscrowProvider(settings=settings)
    except ValueError as exc:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"code": "escrow_nft_identity_provider_not_configured"},
        ) from exc
    try:
        yield provider
    finally:
        await provider.close()
