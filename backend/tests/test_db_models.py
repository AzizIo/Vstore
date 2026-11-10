from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Base,
    ListingStatus,
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
    }
    assert {item.value for item in PriceCurrency} == {"TON", "XTR"}


def test_only_one_open_listing_per_asset_is_enforced_on_postgres() -> None:
    table = Base.metadata.tables["listings"]
    index = next(index for index in table.indexes if index.name == "uq_listings_open_asset")

    assert index.unique is True
    assert "active" in str(index.dialect_options["postgresql"]["where"])
    assert "reserved" in str(index.dialect_options["postgresql"]["where"])
