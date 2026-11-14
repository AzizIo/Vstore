"""Create one synthetic Telegram Stars order in a guarded local test database.

Run only from backend/ after configuring the dedicated test bot environment.
The NFT is an intentionally unverified placeholder with no on-chain item address.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import secrets
import sys
import uuid
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from urllib.parse import urlsplit

from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    Order,
    OrderStatus,
    PriceCurrency,
    User,
)
from app.db.session import async_session_factory, dispose_engine
from app.payments_test_bot import _validate_test_bot_runtime


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if not 0 < parsed <= 9_223_372_036_854_775_807:
        raise argparse.ArgumentTypeError("must be a positive PostgreSQL BIGINT")
    return parsed


def _stars_amount(value: str) -> int:
    parsed = _positive_int(value)
    if parsed > 100_000:
        raise argparse.ArgumentTypeError("must be 100000 or less for a test invoice")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--buyer-telegram-id",
        required=True,
        type=_positive_int,
        help="ID returned by /whoami in the Telegram test bot",
    )
    parser.add_argument(
        "--stars",
        type=_stars_amount,
        default=25,
        help="Synthetic XTR invoice amount (default: 25; maximum: 100000)",
    )
    return parser


async def _seed_order(*, buyer_telegram_id: int, stars: int) -> dict[str, object]:
    now = datetime.now(UTC)
    expires_at = now + timedelta(minutes=30)
    order_id = uuid.uuid4()

    async with async_session_factory.begin() as session:
        buyer = await session.scalar(
            select(User).where(User.telegram_id == buyer_telegram_id).with_for_update()
        )
        if buyer is None:
            buyer = User(
                telegram_id=buyer_telegram_id,
                first_name="Stars test buyer",
            )
            session.add(buyer)
            await session.flush()

        seller = User(
            telegram_id=1_000_000_000_000_000 + secrets.randbelow(1_000_000_000_000_000),
            first_name="Synthetic Stars test seller",
        )
        session.add(seller)
        await session.flush()

        asset = NFTAsset(
            asset_type=AssetType.TON_NFT,
            network="testnet",
            external_id=f"stars-test-{uuid.uuid4().hex}",
            item_address=None,
            owner_id=seller.id,
            name="Synthetic Stars test placeholder",
            verification_status=AssetVerificationStatus.PENDING,
        )
        session.add(asset)
        await session.flush()

        listing = Listing(
            asset_id=asset.id,
            seller_id=seller.id,
            status=ListingStatus.RESERVED,
            price_amount=Decimal(stars),
            price_currency=PriceCurrency.XTR,
            title="Telegram Stars test fixture",
        )
        session.add(listing)
        await session.flush()

        order = Order(
            id=order_id,
            listing_id=listing.id,
            buyer_id=buyer.id,
            seller_id=seller.id,
            idempotency_key=f"stars-test-{uuid.uuid4().hex}",
            status=OrderStatus.RESERVED,
            price_amount=Decimal(stars),
            price_currency=PriceCurrency.XTR,
            expires_at=expires_at,
        )
        session.add(order)

    settings_name = urlsplit(get_settings().database_url).path.lstrip("/")
    return {
        "order_id": str(order_id),
        "stars_amount": stars,
        "expires_at_utc": expires_at.isoformat(),
        "database_name": settings_name,
        "asset_fixture": "unverified testnet placeholder; no item_address or wallet transfer",
    }


async def _run(buyer_telegram_id: int, stars: int) -> dict[str, object]:
    try:
        return await _seed_order(buyer_telegram_id=buyer_telegram_id, stars=stars)
    finally:
        await dispose_engine()


def main() -> int:
    args = _parser().parse_args()
    try:
        _validate_test_bot_runtime()
    except RuntimeError as exc:
        print(f"Test-order seeder safety check failed: {exc}", file=sys.stderr)
        return 2

    try:
        result = asyncio.run(_run(args.buyer_telegram_id, args.stars))
    except Exception:
        # Do not echo exception text: database drivers can include DSNs.
        print(
            "Could not seed the test order. Check the local disposable database and migrations.",
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
