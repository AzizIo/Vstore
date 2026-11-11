import asyncio
from contextlib import suppress

from fastapi import APIRouter, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine
from app.wallets.proof import WalletProofConfigurationError, validate_proof_configuration

router = APIRouter(tags=["health"])
settings = get_settings()

CHECK_TIMEOUT_SECONDS = 2.0


def _ton_connect_proof_ready() -> bool:
    try:
        validate_proof_configuration(
            settings.ton_connect_allowed_domains,
            settings.ton_connect_network,
        )
    except WalletProofConfigurationError:
        return False
    return True


def _authentication_ready() -> bool:
    secret_key = settings.auth_secret_key
    return bool(
        settings.bot_token
        and settings.bot_token.strip()
        and secret_key
        and len(secret_key.strip()) >= 32
    )


async def _database_ready() -> bool:
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            async with engine.connect() as connection:
                await connection.execute(text("SELECT 1"))
        return True
    except Exception:
        return False


async def _redis_ready() -> bool:
    redis: Redis | None = None
    try:
        async with asyncio.timeout(CHECK_TIMEOUT_SECONDS):
            redis = Redis.from_url(settings.redis_url, decode_responses=True)
            await redis.ping()
        return True
    except Exception:
        return False
    finally:
        if redis is not None:
            with suppress(Exception):
                await redis.aclose()


@router.get("/health/live")
async def liveness() -> dict[str, str]:
    return {"status": "ok"}


@router.get("/health/ready")
async def readiness() -> dict[str, object]:
    database_ok, redis_ok = await asyncio.gather(
        _database_ready(),
        _redis_ready(),
    )
    authentication_ok = _authentication_ready()
    ton_connect_proof_ok = _ton_connect_proof_ready()
    checks = {
        "database": "ok" if database_ok else "error",
        "redis": "ok" if redis_ok else "error",
        "authentication": "ok" if authentication_ok else "error",
        # Wallet proof is separately gated: it does not take the public catalogue offline.
        "ton_connect_proof": "ok" if ton_connect_proof_ok else "error",
        # Domains are public origins, not secrets. Preflight uses this to verify that
        # the API allowlist includes the exact Mini App host in the public manifest.
        "ton_connect_proof_domains": (
            list(settings.ton_connect_allowed_domains) if ton_connect_proof_ok else []
        ),
    }

    if not database_ok or not redis_ok or not authentication_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks},
        )

    return {"status": "ready", "checks": checks}
