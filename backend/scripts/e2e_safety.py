"""Fail-closed safety checks for the API-backed E2E environment."""

from __future__ import annotations

import os
from urllib.parse import urlsplit

from redis.asyncio import Redis

from app.core.config import get_settings
_LOOPBACK_HOSTS = {"127.0.0.1", "localhost", "::1"}


def validate_e2e_targets() -> None:
    """Require explicit E2E mode and disposable loopback PostgreSQL/Redis targets."""
    if os.getenv("E2E_MODE") != "1":
        raise RuntimeError("E2E_MODE=1 is required for API-backed E2E operations.")

    settings = get_settings()
    database = urlsplit(settings.database_url)
    if (
        settings.environment != "test"
        or database.scheme != "postgresql+asyncpg"
        or database.hostname not in _LOOPBACK_HOSTS
        or database.port not in {None, 5432}
        or database.path != "/viltara_e2e"
        or database.query
        or database.fragment
    ):
        raise RuntimeError(
            "Refusing E2E operation: DATABASE_URL must target the loopback "
            "PostgreSQL database named viltara_e2e in ENVIRONMENT=test."
        )

    redis_url = urlsplit(settings.redis_url)
    if (
        redis_url.scheme != "redis"
        or redis_url.hostname not in _LOOPBACK_HOSTS
        or redis_url.port not in {None, 6379}
        or redis_url.path != "/0"
        or redis_url.query
        or redis_url.fragment
    ):
        raise RuntimeError(
            "Refusing E2E operation: REDIS_URL must target loopback Redis "
            "database 0 (redis://localhost:6379/0)."
        )


async def assert_e2e_environment() -> None:
    """Validate configured targets and prove the isolated Redis service is reachable."""
    validate_e2e_targets()
    redis = Redis.from_url(
        get_settings().redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        if not await redis.ping():
            raise RuntimeError("The isolated E2E Redis service did not respond to PING.")
    except Exception as exc:
        raise RuntimeError(
            "Refusing E2E operation: the configured loopback Redis service is unavailable."
        ) from exc
    finally:
        await redis.aclose()
