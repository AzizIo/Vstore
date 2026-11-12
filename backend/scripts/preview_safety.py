"""Fail-closed safety checks for the isolated Preview runtime.

Run from backend/: python -m scripts.preview_safety guard|preflight
This is deliberately separate from the public HTTPS demo preflight.
"""
from __future__ import annotations

import argparse
import asyncio
import os
from pathlib import Path
from urllib.parse import urlsplit

from alembic.config import Config
from alembic.script import ScriptDirectory
from redis.asyncio import Redis
from sqlalchemy import text
from sqlalchemy.ext.asyncio import create_async_engine

from app.core.config import get_settings

_PREVIEW_DB = "viltara_preview"
_PREVIEW_USER = "viltara_preview"
_PREVIEW_REDIS_DB = "/0"


def validate_preview_targets() -> None:
    """Reject ambiguous/non-Preview targets before migrations or data writes."""
    if os.getenv("PREVIEW_MODE") != "1":
        raise RuntimeError("PREVIEW_MODE=1 is required for Preview-only operations.")

    settings = get_settings()
    database = urlsplit(settings.database_url)
    if (
        database.scheme != "postgresql+asyncpg"
        or database.hostname != "db"
        or database.port not in {None, 5432}
        or database.path != f"/{_PREVIEW_DB}"
        or database.username != _PREVIEW_USER
        or database.query
        or database.fragment
    ):
        raise RuntimeError(
            "Refusing Preview operation: DATABASE_URL must target service db, "
            "database viltara_preview, user viltara_preview, port 5432, with no query options."
        )

    redis_url = urlsplit(settings.redis_url)
    if (
        redis_url.scheme != "redis"
        or redis_url.hostname != "redis"
        or redis_url.port not in {None, 6379}
        or redis_url.path != _PREVIEW_REDIS_DB
        or redis_url.query
        or redis_url.fragment
    ):
        raise RuntimeError(
            "Refusing Preview operation: REDIS_URL must target service redis, "
            "port 6379, database 0, with no query options."
        )

    if settings.ton_connect_network != "testnet":
        raise RuntimeError("Refusing Preview operation: TON_CONNECT_NETWORK must be testnet.")

    app_url = os.getenv("PREVIEW_VITE_TONCONNECT_APP_URL", "")
    manifest_url = os.getenv("PREVIEW_VITE_TONCONNECT_MANIFEST_URL", "")
    if not _valid_https_origin(app_url):
        raise RuntimeError(
            "PREVIEW_VITE_TONCONNECT_APP_URL must be a public HTTPS origin without a path."
        )
    app_origin = app_url.rstrip("/")
    app_host = urlsplit(app_origin).hostname
    expected_manifest = f"{app_origin}/tonconnect-manifest.json"
    if manifest_url != expected_manifest:
        raise RuntimeError(
            "PREVIEW_VITE_TONCONNECT_MANIFEST_URL must equal the app origin plus "
            "/tonconnect-manifest.json."
        )
    if settings.telegram_mini_app_url is None or settings.telegram_mini_app_url.rstrip("/") != app_origin:
        raise RuntimeError(
            "PREVIEW_TELEGRAM_MINI_APP_URL and PREVIEW_VITE_TONCONNECT_APP_URL must match."
        )
    if app_host not in settings.ton_connect_allowed_domains:
        raise RuntimeError(
            "TON_CONNECT_ALLOWED_DOMAINS must contain the exact Preview hostname."
        )
    if app_origin not in settings.cors_allowed_origins:
        raise RuntimeError(
            "CORS_ALLOWED_ORIGINS must contain the exact Preview HTTPS origin."
        )
    if not settings.bot_token or not settings.auth_secret_key:
        raise RuntimeError(
            "Preview Telegram authentication requires PREVIEW_BOT_TOKEN and "
            "PREVIEW_AUTH_SECRET_KEY; the polling bot container itself remains optional."
        )


def _valid_https_origin(value: str) -> bool:
    try:
        parsed = urlsplit(value)
        return (
            parsed.scheme == "https"
            and bool(parsed.hostname)
            and parsed.username is None
            and parsed.password is None
            and parsed.path in {"", "/"}
            and not parsed.query
            and not parsed.fragment
        )
    except ValueError:
        return False


async def assert_preview_dependencies() -> None:
    """Check PostgreSQL, Redis, and that migrations are applied to the expected DB."""
    validate_preview_targets()
    settings = get_settings()
    engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    try:
        async with engine.connect() as connection:
            await connection.execute(text("SELECT 1"))
            current = await connection.scalar(text("SELECT version_num FROM alembic_version"))
        config_path = Path(__file__).resolve().parents[1] / "alembic.ini"
        migration_config = Config(str(config_path))
        script = ScriptDirectory.from_config(migration_config)
        heads = set(script.get_heads())
        if not current or heads != {current}:
            raise RuntimeError(
                "Preview database migrations are not at the single current Alembic head; "
                "apply migrations to the isolated Preview database and rerun preflight."
            )
    except RuntimeError:
        raise
    except Exception as exc:
        raise RuntimeError(
            "Preview PostgreSQL is unavailable or has not been migrated. "
            "No credentials or database URL were printed."
        ) from exc
    finally:
        await engine.dispose()

    redis = Redis.from_url(
        settings.redis_url,
        decode_responses=True,
        socket_connect_timeout=2,
        socket_timeout=2,
    )
    try:
        if not await redis.ping():
            raise RuntimeError("Preview Redis did not respond to PING.")
    except Exception as exc:
        raise RuntimeError(
            "Preview Redis is unavailable. Check the isolated Preview service; "
            "no credentials were printed."
        ) from exc
    finally:
        await redis.aclose()


async def main() -> int:
    parser = argparse.ArgumentParser(description="Fail-closed isolated Preview safety checks.")
    parser.add_argument(
        "command",
        choices=("guard", "preflight"),
        help="'guard' validates targets before migration; 'preflight' also checks DB/Redis/migrations.",
    )
    args = parser.parse_args()
    try:
        if args.command == "guard":
            validate_preview_targets()
            print("Preview target guard passed; database target is explicitly isolated.")
        else:
            await assert_preview_dependencies()
            print("Preview preflight passed: target, configuration, PostgreSQL, Redis and migrations.")
    except RuntimeError as exc:
        print(f"PREVIEW BLOCKED: {exc}")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
