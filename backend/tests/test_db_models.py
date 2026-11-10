from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Base,
    ListingStatus,
    OrderStatus,
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
        "telegram_notification_outbox",
    }


def test_asset_types_keep_integrations_separate() -> None:
    assert {item.value for item in AssetType} == {"ton_nft", "telegram_gift"}


def test_asset_verification_has_safe_pending_default() -> None:
    assert AssetVerificationStatus.PENDING.value == "pending"


def test_listing_lifecycle_and_free_schema_are_explicit() -> None:
    assert {item.value for item in ListingStatus} == {
        "draft",
        "active",
        "reserved",
        "sold",
        "cancelled",
        "expired",
    }
    assert "price_amount" not in Base.metadata.tables["listings"].columns
    assert "price_currency" not in Base.metadata.tables["listings"].columns
    assert "price_amount" not in Base.metadata.tables["orders"].columns
    assert "price_currency" not in Base.metadata.tables["orders"].columns


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


def test_order_lifecycle_has_only_server_supported_initial_terminal_states() -> None:
    assert {item.value for item in OrderStatus} == {
        "pending_payment",
        "cancelled",
        "expired",
    }
