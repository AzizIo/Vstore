from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Base,
    ListingStatus,
    OrderStatus,
    PriceCurrency,
)


def test_marketplace_tables_are_registered() -> None:
    assert set(Base.metadata.tables) == {
        "users",
        "wallets",
        "nft_collections",
        "nft_assets",
        "listings",
        "orders",
        "order_events",
        "order_delivery_attempts",
        "telegram_notification_outbox",
        "moderation_audit_log",
        "seller_reviews",
    }


def test_asset_types_keep_integrations_separate() -> None:
    assert {item.value for item in AssetType} == {"ton_nft", "telegram_gift"}


def test_asset_verification_has_safe_pending_default() -> None:
    assert AssetVerificationStatus.PENDING.value == "pending"


def test_listing_lifecycle_and_price_currencies_are_explicit() -> None:
    assert {item.value for item in ListingStatus} == {
        "draft",
        "active",
        "reserved",
        "sold",
        "cancelled",
        "expired",
        "suspended",
    }
    assert {item.value for item in PriceCurrency} == {"TON", "XTR"}


def test_only_one_open_listing_per_asset_is_enforced_on_postgres() -> None:
    table = Base.metadata.tables["listings"]
    index = next(index for index in table.indexes if index.name == "uq_listings_open_asset")

    assert index.unique is True
    assert "active" in str(index.dialect_options["postgresql"]["where"])
    assert "reserved" in str(index.dialect_options["postgresql"]["where"])


def test_nft_asset_external_identity_is_scoped_by_network() -> None:
    table = Base.metadata.tables["nft_assets"]
    constraint = next(
        constraint
        for constraint in table.constraints
        if constraint.name == "uq_nft_assets_type_network_external_id"
    )

    assert [column.name for column in constraint.columns] == [
        "asset_type",
        "network",
        "external_id",
    ]


def test_order_lifecycle_uses_explicit_non_payment_reservation_states() -> None:
    assert {item.value for item in OrderStatus} == {
        "reserved",
        "awaiting_transfer",
        "observing_transfer",
        "completed",
        "cancelled",
        "expired",
    }


def test_delivery_attempt_model_has_immutable_wallet_snapshots_and_retry_states() -> None:
    from app.db.models import OrderDeliveryAttemptStatus

    assert {item.value for item in OrderDeliveryAttemptStatus} == {
        "prepared", "observing", "verified", "failed", "manual_review", "cancelled"
    }
    table = Base.metadata.tables["order_delivery_attempts"]
    assert {"seller_address_snapshot", "buyer_address_snapshot", "query_id"} <= set(table.c.keys())
    assert any(index.name == "uq_order_delivery_attempt_active_order" for index in table.indexes)
    assert any(
        index.name == "uq_order_delivery_attempt_verified_transfer"
        for index in table.indexes
    )
