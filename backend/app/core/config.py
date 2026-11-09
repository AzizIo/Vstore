from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    app_name: str = "VILTARA SHOP API"
    environment: str = "local"
    database_url: str = "postgresql+asyncpg://viltara:viltara@localhost:5432/viltara"
    redis_url: str = "redis://localhost:6379/0"
    bot_token: str | None = None
    auth_secret_key: str | None = None
    auth_token_ttl_seconds: int = 3600

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )


@lru_cache
def get_settings() -> Settings:
    return Settings()
