from types import SimpleNamespace

import pytest

from scripts import preview_safety


@pytest.fixture
def preview_settings(monkeypatch):
    settings = SimpleNamespace(
        database_url="postgresql+asyncpg://viltara_preview:secret@db:5432/viltara_preview",
        redis_url="redis://redis:6379/0",
        ton_connect_network="testnet",
        ton_connect_allowed_domains=["preview.example"],
        telegram_mini_app_url="https://preview.example",
        cors_allowed_origins=["https://preview.example"],
        bot_token="test-only-token",
        auth_secret_key="test-only-secret",
    )
    monkeypatch.setattr(preview_safety, "get_settings", lambda: settings)
    monkeypatch.setenv("PREVIEW_MODE", "1")
    monkeypatch.setenv("PREVIEW_VITE_TONCONNECT_APP_URL", "https://preview.example")
    monkeypatch.setenv(
        "PREVIEW_VITE_TONCONNECT_MANIFEST_URL",
        "https://preview.example/tonconnect-manifest.json",
    )
    return settings


def test_accepts_only_explicit_isolated_preview_targets(preview_settings):
    preview_safety.validate_preview_targets()


def test_requires_preview_opt_in(preview_settings, monkeypatch):
    monkeypatch.delenv("PREVIEW_MODE")
    with pytest.raises(RuntimeError, match="PREVIEW_MODE=1"):
        preview_safety.validate_preview_targets()


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://user:secret@localhost:5432/viltara",
        "postgresql+asyncpg://viltara_preview:secret@production-db:5432/viltara_preview",
        "postgresql+asyncpg://viltara_preview:secret@db:5432/production",
        "postgresql+asyncpg://viltara_preview:secret@db:5433/viltara_preview",
        "postgresql+asyncpg://viltara_preview:secret@db:5432/viltara_preview?sslmode=require",
    ],
)
def test_rejects_ambiguous_or_non_preview_database(preview_settings, database_url):
    preview_settings.database_url = database_url
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        preview_safety.validate_preview_targets()


@pytest.mark.parametrize(
    "redis_url",
    [
        "redis://localhost:6379/0",
        "redis://remote-cache:6379/0",
        "redis://redis:6379/1",
        "rediss://redis:6379/0",
        "redis://redis:6380/0",
    ],
)
def test_rejects_non_preview_redis(preview_settings, redis_url):
    preview_settings.redis_url = redis_url
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        preview_safety.validate_preview_targets()


def test_preview_must_stay_on_testnet(preview_settings):
    preview_settings.ton_connect_network = "mainnet"
    with pytest.raises(RuntimeError, match="testnet"):
        preview_safety.validate_preview_targets()


def test_preview_hostname_must_match_allowlist(preview_settings):
    preview_settings.ton_connect_allowed_domains = ["other.example"]
    with pytest.raises(RuntimeError, match="exact Preview hostname"):
        preview_safety.validate_preview_targets()


def test_manifest_must_match_preview_origin(preview_settings, monkeypatch):
    monkeypatch.setenv(
        "PREVIEW_VITE_TONCONNECT_MANIFEST_URL",
        "https://other.example/tonconnect-manifest.json",
    )
    with pytest.raises(RuntimeError, match="MANIFEST_URL"):
        preview_safety.validate_preview_targets()


def test_cors_must_allow_exact_preview_origin(preview_settings):
    preview_settings.cors_allowed_origins = ["https://other.example"]
    with pytest.raises(RuntimeError, match="CORS_ALLOWED_ORIGINS"):
        preview_safety.validate_preview_targets()


def test_auth_token_required_even_when_polling_bot_is_optional(preview_settings):
    preview_settings.bot_token = None
    with pytest.raises(RuntimeError, match="PREVIEW_BOT_TOKEN"):
        preview_safety.validate_preview_targets()
