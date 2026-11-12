"""Assert the persisted result of the API-backed seller-to-buyer Playwright journey."""

from __future__ import annotations

import asyncio
from decimal import Decimal

from redis.asyncio import Redis
from sqlalchemy import select

from app.core.config import get_settings
from app.db.models import (
    Listing,
    ListingStatus,
    ModerationAuditLog,
    NFTAsset,
    Order,
    OrderEvent,
    OrderStatus,
    TelegramNotificationOutbox,
    User,
)
from app.db.session import async_session_factory, dispose_engine
from scripts.e2e_safety import assert_e2e_environment
from scripts.e2e_ton_provider import (
    E2E_BUYER_TELEGRAM_ID,
    E2E_SELLER_TELEGRAM_ID,
)


async def assert_journey() -> None:
    await assert_e2e_environment()

    async with async_session_factory() as session:
        seller = await session.scalar(
            select(User).where(User.telegram_id == E2E_SELLER_TELEGRAM_ID)
        )
        buyer = await session.scalar(
            select(User).where(User.telegram_id == E2E_BUYER_TELEGRAM_ID)
        )
        assert seller is not None, "The seller was not authenticated through the API."
        assert buyer is not None, "The buyer was not authenticated through the API."

        listings = list(
            (
                await session.scalars(
                    select(Listing).where(
                        Listing.seller_id == seller.id,
                        Listing.title.in_(
                            ["E2E Published NFT", "E2E Admin Moderation Listing"]
                        ),
                    )
                )
            ).all()
        )
        marketplace_listings = [
            item
            for item in listings
            if item.title == "E2E Published NFT"
            and item.status is not ListingStatus.CANCELLED
        ]
        moderation_listings = [
            item for item in listings
            if item.title == "E2E Admin Moderation Listing"
        ]
        assert len(marketplace_listings) == 1, (
            f"Expected one non-cancelled marketplace listing, got {len(marketplace_listings)}."
        )
        assert len(moderation_listings) == 1, (
            f"Expected one isolated moderation listing, got {len(moderation_listings)}."
        )
        moderation_listing = moderation_listings[0]
        assert moderation_listing.status is ListingStatus.CANCELLED
        moderation_events = list(
            (
                await session.scalars(
                    select(ModerationAuditLog).where(
                        ModerationAuditLog.target_id == moderation_listing.id
                    )
                )
            ).all()
        )
        assert [event.action for event in sorted(
            moderation_events, key=lambda item: item.occurred_at
        )] == ["suspended", "restored"]
        listing = marketplace_listings[0]
        assert listing.status is ListingStatus.SOLD, (
            "Expected sold listing after independently verified delivery, "
            f"got {listing.status.value}."
        )
        assert listing.price_amount == Decimal("15.75")
        assert listing.price_currency.value == "TON"
        assert listing.title == "E2E Published NFT"

        orders = list(
            (
                await session.scalars(
                    select(Order).where(
                        Order.seller_id == seller.id,
                        Order.buyer_id == buyer.id,
                    )
                )
            ).all()
        )
        assert len(orders) == 1, f"Expected one buyer order, got {len(orders)}."
        order = orders[0]
        assert order.listing_id == listing.id
        assert order.status is OrderStatus.COMPLETED
        assert order.price_amount == Decimal("15.75")
        assert order.price_currency.value == "TON"

        events = list(
            (
                await session.scalars(
                    select(OrderEvent).where(OrderEvent.order_id == order.id)
                )
            ).all()
        )
        assert [event.to_status for event in sorted(events, key=lambda item: item.created_at)] == [
            OrderStatus.RESERVED,
            OrderStatus.AWAITING_TRANSFER,
            OrderStatus.OBSERVING_TRANSFER,
            OrderStatus.COMPLETED,
        ], (
            "Unexpected delivery lifecycle event history: "
            f"{[event.to_status.value for event in events]}."
        )
        assert events[0].from_status is None
        assert events[0].actor_id == buyer.id
        assert events[0].actor_type == "buyer"

        delivered_asset = await session.scalar(
            select(NFTAsset).where(NFTAsset.id == listing.asset_id)
        )
        assert delivered_asset is not None
        assert delivered_asset.owner_id == buyer.id

        outbox = list(
            (
                await session.scalars(
                    select(TelegramNotificationOutbox).where(
                        TelegramNotificationOutbox.order_id == order.id
                    )
                )
            ).all()
        )
        assert len(outbox) == 8, (
            "Expected four lifecycle events for buyer and seller, "
            f"got {len(outbox)}."
        )
        assert {item.recipient_role for item in outbox} == {"buyer", "seller"}
        assert {item.event_type for item in outbox} == {
            "order_created",
            "delivery_prepared",
            "delivery_submitted",
            "delivery_confirmed",
        }
        assert len({item.dedupe_key for item in outbox}) == 8
        assert {item.status for item in outbox} == {"pending"}
        assert {item.recipient_telegram_id for item in outbox} == {
            E2E_SELLER_TELEGRAM_ID,
            E2E_BUYER_TELEGRAM_ID,
        }
        seller_id = str(seller.id)

    redis = Redis.from_url(get_settings().redis_url, decode_responses=True)
    try:
        challenge_keys = await redis.keys("wallet-proof:challenge:*")
        challenge_owners = {
            await redis.get(key) for key in challenge_keys
        }
        assert seller_id in challenge_owners, (
            "The verified Telegram API session did not persist a wallet-proof "
            "challenge bound to the seller in Redis."
        )
        challenge_ttls = [await redis.ttl(key) for key in challenge_keys]
        assert any(ttl > 0 for ttl in challenge_ttls), (
            "The Redis wallet-proof challenge must have a positive TTL."
        )
    finally:
        await redis.aclose()

    await dispose_engine()
    print(
        "API-backed E2E persistence verified: moderation audit append-only decisions, "
        "one cancelled moderation fixture, one completed marketplace listing, seller-signed "
        "transfer independently verified, four order events and eight pending outbox rows."
    )


if __name__ == "__main__":
    asyncio.run(assert_journey())
