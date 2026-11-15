from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VILTARA SHOP API"
    environment: str = "local"
    # Explicit marker for the isolated Preview stack; never set by production Compose.
    preview_mode: bool = False
    database_url: str = "postgresql+asyncpg://viltara:viltara@localhost:5432/viltara"
    redis_url: str = "redis://localhost:6379/0"
    bot_token: str | None = None
    # Isolated Telegram Stars test bot; never reuse the production bot token.
    telegram_stars_test_enabled: bool = False
    telegram_stars_test_bot_token: SecretStr | None = None
    auth_secret_key: str | None = None
    auth_token_ttl_seconds: int = 3600
    # Server-side allowlist; an empty list disables admin access.
    admin_telegram_ids: list[int] = Field(default_factory=list)
    order_pending_ttl_seconds: int = Field(default=900, gt=0)
    delivery_preparation_ttl_seconds: int = Field(default=900, gt=0)
    order_expiration_poll_seconds: int = Field(default=30, gt=0)
    delivery_observer_poll_seconds: int = Field(default=5, gt=0)
    delivery_observer_batch_size: int = Field(default=10, gt=0, le=100)
    delivery_observer_lease_seconds: int = Field(default=300, gt=0)
    delivery_observer_concurrency: int = Field(default=5, gt=0, le=10)
    delivery_observer_retry_base_seconds: int = Field(default=5, gt=0)
    delivery_observer_retry_max_seconds: int = Field(default=300, gt=0)
    delivery_observer_max_attempts: int = Field(default=20, gt=0)
    notification_poll_seconds: int = Field(default=5, gt=0)
    notification_batch_size: int = Field(default=10, gt=0, le=100)
    notification_claim_lease_seconds: int = Field(default=300, gt=0)
    notification_max_attempts: int = Field(default=8, gt=0)
    notification_retry_base_seconds: int = Field(default=5, gt=0)
    notification_retry_max_seconds: int = Field(default=3600, gt=0)
    payment_refund_poll_seconds: int = Field(default=5, gt=0)
    payment_refund_batch_size: int = Field(default=10, gt=0, le=100)
    payment_refund_lease_seconds: int = Field(default=300, gt=0)
    payment_refund_max_attempts: int = Field(default=8, gt=0)
    payment_refund_retry_base_seconds: int = Field(default=10, gt=0)
    payment_refund_retry_max_seconds: int = Field(default=1800, gt=0)
    payment_refund_reconcile_delay_seconds: int = Field(default=30, gt=0)
    payment_refund_max_reconcile_attempts: int = Field(default=20, gt=0)
    telegram_mini_app_url: str | None = None
    telegram_mini_app_direct_link: str | None = None
    ton_connect_allowed_domains: list[str] = Field(default_factory=list)
    ton_connect_network: Literal["mainnet", "testnet"] = "mainnet"
    ton_center_api_key: SecretStr | None = None
    ton_center_mainnet_base_url: str = "https://toncenter.com/api/v3"
    ton_center_testnet_base_url: str = "https://testnet.toncenter.com/api/v3"
    ton_center_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
    # DealEscrow v1 deployment terms. The authority lists intentionally default empty;
    # deployment/action preparation stays blocked until approved testnet keys are supplied.
    ton_escrow_oracle_public_keys: list[str] = Field(default_factory=list)
    ton_escrow_resolver_public_keys: list[str] = Field(default_factory=list)
    ton_escrow_execution_reserve_nanotons: int = Field(default=500_000_000, gt=0)
    ton_escrow_seller_deployment_refund_nanotons: int = Field(default=20_000_000, gt=0)
    ton_escrow_nft_transfer_value_nanotons: int = Field(default=50_000_000, gt=0)
    ton_escrow_deployment_value_nanotons: int = Field(default=100_000_000, gt=0)
    ton_escrow_activation_value_nanotons: int = Field(default=10_000_000, gt=0)
    ton_escrow_action_value_nanotons: int = Field(default=10_000_000, gt=0)
    ton_escrow_nft_deposit_value_nanotons: int = Field(default=10_000_000, gt=0)
    ton_escrow_nft_return_value_nanotons: int = Field(default=10_000_000, gt=0)
    # A trust-level-0 Pytoniq proof verifier is opt-in and only supports TON testnet.
    ton_escrow_finality_enabled: bool = False
    ton_escrow_finality_min_depth: int = Field(default=2, ge=1, le=16)
    ton_escrow_finality_batch_deals: int = Field(default=25, ge=1, le=100)
    ton_metadata_ipfs_gateway_url: str = "https://ipfs.io/ipfs"
    cors_allowed_origins: list[str] = [
        "http://localhost:5173",
        "http://127.0.0.1:5173",
    ]

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
