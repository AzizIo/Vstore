"""Seed a single verified seller NFT into the disposable API-backed E2E database."""

from __future__ import annotations

import asyncio
from datetime import UTC, datetime
from urllib.parse import urlparse
from uuid import uuid4

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    NFTAsset,
    User,
    Wallet,
)
from app.db.session import async_session_factory, dispose_engine
from scripts.e2e_ton_provider import (
    E2E_NFT_ITEM_ADDRESS,
    E2E_NFT_NAME,
    E2E_SELLER_TELEGRAM_ID,
    E2E_SELLER_WALLET_ADDRESS,
)


def _assert_isolated_e2e_database() -> None:
    settings = get_settings()
    database = urlparse(settings.database_url)
    if (
        settings.environment != "test"
        or database.hostname not in {"127.0.0.1", "localhost"}
        or database.path != "/viltara_e2e"
    ):
        raise SystemExit(
            "Refusing to seed: this script requires ENVIRONMENT=test and the "
            "loopback viltara_e2e database."
        )


async def seed() -> None:
    _assert_isolated_e2e_database()
    now = datetime.now(UTC)

    async with async_session_factory() as session:
        seller = await session.scalar(
            select(User).where(User.telegram_id == E2E_SELLER_TELEGRAM_ID)
        )
        if seller is None:
            seller = User(
                id=uuid4(),
                telegram_id=E2E_SELLER_TELEGRAM_ID,
                username="e2e_seller",
                first_name="E2E Seller",
                language_code="en",
            )
            session.add(seller)
            await session.flush()
        else:
            seller.username = "e2e_seller"
            seller.first_name = "E2E Seller"
            seller.is_blocked = False

        wallet = await session.scalar(
            select(Wallet).where(
                Wallet.network == "mainnet",
                Wallet.address == E2E_SELLER_WALLET_ADDRESS,
            )
        )
        if wallet is None:
            wallet = Wallet(
                id=uuid4(),
                user_id=seller.id,
                address=E2E_SELLER_WALLET_ADDRESS,
                network="mainnet",
                is_verified=True,
                is_primary=True,
            )
            session.add(wallet)
        else:
            wallet.user_id = seller.id
            wallet.is_verified = True
            wallet.is_primary = True

        asset = await session.scalar(
            select(NFTAsset).where(
                NFTAsset.asset_type == AssetType.TON_NFT,
                NFTAsset.network == "mainnet",
                NFTAsset.external_id == E2E_NFT_ITEM_ADDRESS,
            )
        )
        if asset is None:
            asset = NFTAsset(
                id=uuid4(),
                asset_type=AssetType.TON_NFT,
                network="mainnet",
                external_id=E2E_NFT_ITEM_ADDRESS,
                item_address=E2E_NFT_ITEM_ADDRESS,
                owner_id=seller.id,
                name=E2E_NFT_NAME,
                description="Seeded verified asset for API-backed E2E.",
                verification_status=AssetVerificationStatus.VERIFIED,
                verified_at=now,
            )
            session.add(asset)
        else:
            asset.item_address = E2E_NFT_ITEM_ADDRESS
            asset.owner_id = seller.id
            asset.name = E2E_NFT_NAME
            asset.verification_status = AssetVerificationStatus.VERIFIED
            asset.verified_at = now

        await session.commit()

    await dispose_engine()
    print("Seeded isolated E2E seller, verified wallet and NFT fixture.")


if __name__ == "__main__":
    asyncio.run(seed())
