import asyncio

from fastapi import APIRouter, HTTPException, status
from redis.asyncio import Redis
from sqlalchemy import text

from app.core.config import get_settings
from app.db.session import engine

router = APIRouter(tags=["health"])
settings = get_settings()

CHECK_TIMEOUT_SECONDS = 2.0


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
    checks = {
        "database": "ok" if database_ok else "error",
        "redis": "ok" if redis_ok else "error",
    }

    if not database_ok or not redis_ok:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail={"status": "not_ready", "checks": checks},
        )

    return {"status": "ready", "checks": checks}
