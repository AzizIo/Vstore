from collections.abc import AsyncIterator

from app.assets.ton_nft.provider import TONCenterV3Config, TONCenterV3Provider
from app.assets.ton_nft.verifier import TONNFTVerifier
from app.core.config import get_settings


async def get_ton_nft_verifier() -> AsyncIterator[TONNFTVerifier]:
    settings = get_settings()
    base_url = (
        settings.ton_center_mainnet_base_url
        if settings.ton_connect_network == "mainnet"
        else settings.ton_center_testnet_base_url
    )
    api_key = (
        settings.ton_center_api_key.get_secret_value()
        if settings.ton_center_api_key is not None
        else None
    )
    provider = TONCenterV3Provider(
        TONCenterV3Config(
            base_url=base_url,
            api_key=api_key,
            timeout_seconds=settings.ton_center_timeout_seconds,
        )
    )
    try:
        yield TONNFTVerifier(provider)
    finally:
        await provider.aclose()