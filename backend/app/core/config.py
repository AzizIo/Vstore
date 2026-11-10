from functools import lru_cache
from typing import Literal

from pydantic import Field, SecretStr
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VILTARA SHOP API"
    environment: str = "local"
    database_url: str = "postgresql+asyncpg://viltara:viltara@localhost:5432/viltara"
    redis_url: str = "redis://localhost:6379/0"
    bot_token: str | None = None
    auth_secret_key: str | None = None
    auth_token_ttl_seconds: int = 3600
    order_pending_ttl_seconds: int = Field(default=900, gt=0)
    order_expiration_poll_seconds: int = Field(default=30, gt=0)
    ton_connect_allowed_domains: list[str] = Field(default_factory=list)
    ton_connect_network: Literal["mainnet", "testnet"] = "mainnet"
    ton_center_api_key: SecretStr | None = None
    ton_center_mainnet_base_url: str = "https://toncenter.com/api/v3"
    ton_center_testnet_base_url: str = "https://testnet.toncenter.com/api/v3"
    ton_center_timeout_seconds: float = Field(default=8.0, gt=0, le=60)
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
