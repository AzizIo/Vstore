from collections.abc import AsyncIterator

from app.assets.ton_nft.provider import TONCenterV3Config, TONCenterV3Provider
from app.assets.ton_nft.verifier import TONNFTVerifier
from app.core.config import get_settings


def build_ton_nft_verifier() -> TONNFTVerifier:
    """Build a verifier for the configured TON network.

    The caller owns the returned verifier's provider and must close it when the
    verifier is used outside a FastAPI dependency scope.
    """

    settings = get_settings()
    network = settings.ton_connect_network
    base_url = (
        settings.ton_center_mainnet_base_url
        if network == "mainnet"
        else settings.ton_center_testnet_base_url
    )
    api_key = (
        settings.ton_center_api_key.get_secret_value()
        if settings.ton_center_api_key is not None
        else None
    )
    return TONNFTVerifier(
        TONCenterV3Provider(
            TONCenterV3Config(
                base_url=base_url,
                api_key=api_key,
                timeout_seconds=settings.ton_center_timeout_seconds,
            )
        ),
        network=network,
    )


async def get_ton_nft_verifier() -> AsyncIterator[TONNFTVerifier]:
    verifier = build_ton_nft_verifier()
    try:
        yield verifier
    finally:
        await verifier.provider.aclose()
