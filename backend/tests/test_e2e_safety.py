from types import SimpleNamespace

import pytest

from scripts.e2e_safety import validate_e2e_targets


@pytest.fixture
def e2e_settings(monkeypatch):
    settings = SimpleNamespace(
        environment="test",
        database_url="postgresql+asyncpg://user:pass@127.0.0.1:5432/viltara_e2e",
        redis_url="redis://127.0.0.1:6379/0",
    )
    monkeypatch.setattr("scripts.e2e_safety.get_settings", lambda: settings)
    monkeypatch.setenv("E2E_MODE", "1")
    return settings


def test_accepts_only_the_disposable_loopback_targets(e2e_settings):
    validate_e2e_targets()


def test_requires_explicit_e2e_mode(e2e_settings, monkeypatch):
    monkeypatch.delenv("E2E_MODE")
    with pytest.raises(RuntimeError, match="E2E_MODE=1"):
        validate_e2e_targets()


@pytest.mark.parametrize(
    "database_url",
    [
        "postgresql+asyncpg://user:pass@db.example:5432/viltara_e2e",
        "postgresql+asyncpg://user:pass@127.0.0.1:5432/production",
        "postgresql+asyncpg://user:pass@127.0.0.1:5433/viltara_e2e",
        "postgresql+asyncpg://user:pass@127.0.0.1:5432/viltara_e2e?sslmode=require",
    ],
)
def test_rejects_non_disposable_database_targets(e2e_settings, database_url):
    e2e_settings.database_url = database_url
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_e2e_targets()


@pytest.mark.parametrize(
    "redis_url",
    [
        "redis://redis.example:6379/0",
        "redis://127.0.0.1:6379/1",
        "redis://127.0.0.1:6380/0",
        "rediss://127.0.0.1:6379/0",
        "redis://127.0.0.1:6379/0?ssl_cert_reqs=required",
    ],
)
def test_rejects_non_disposable_redis_targets(e2e_settings, redis_url):
    e2e_settings.redis_url = redis_url
    with pytest.raises(RuntimeError, match="REDIS_URL"):
        validate_e2e_targets()


def test_requires_test_environment(e2e_settings):
    e2e_settings.environment = "production"
    with pytest.raises(RuntimeError, match="DATABASE_URL"):
        validate_e2e_targets()
