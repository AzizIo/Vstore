import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import getLogger

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.admin.moderation import router as admin_moderation_router
from app.api.assets import router as assets_router
from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.listings import router as listings_router
from app.api.orders import router as orders_router
from app.api.reviews import router as reviews_router
from app.api.users import router as users_router
from app.api.wallets import router as wallets_router
from app.assets.ton_nft.observer import run_delivery_observer_pass
from app.core.config import get_settings
from app.db.session import async_session_factory, dispose_engine
from app.listings.service import expire_active_listings
from app.orders.service import expire_pending_orders

logger = getLogger(__name__)


async def _expire_orders_periodically() -> None:
    poll_interval = get_settings().order_expiration_poll_seconds
    while True:
        try:
            await asyncio.sleep(poll_interval)
            async with async_session_factory() as session:
                await expire_pending_orders(session)
            async with async_session_factory() as session:
                await expire_active_listings(session)
        except asyncio.CancelledError:
            raise
        except Exception:
            # Keep the worker alive after a transient failure; the next poll retries.
            logger.exception("Could not complete marketplace expiration; the next poll will retry")


async def _observe_delivery_attempts_periodically() -> None:
    poll_interval = get_settings().delivery_observer_poll_seconds
    while True:
        try:
            await asyncio.sleep(poll_interval)
            result = await run_delivery_observer_pass(async_session_factory)
            if result.claimed:
                logger.info(
                    "Delivery observer pass: claimed=%s verified=%s retried=%s "
                    "manual_review=%s lease_lost=%s",
                    result.claimed,
                    result.verified,
                    result.retried,
                    result.manual_review,
                    result.lease_lost,
                )
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.exception(
                "Could not complete delivery observer pass; the next poll will retry"
            )


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    expiration_task = asyncio.create_task(_expire_orders_periodically())
    delivery_observer_task = asyncio.create_task(
        _observe_delivery_attempts_periodically()
    )
    try:
        yield
    finally:
        expiration_task.cancel()
        delivery_observer_task.cancel()
        for task in (expiration_task, delivery_observer_task):
            try:
                await task
            except asyncio.CancelledError:
                pass
        await dispose_engine()


settings = get_settings()

app = FastAPI(
    title="VILTARA SHOP API",
    version="0.1.0",
    description="Backend API for the VILTARA SHOP Telegram marketplace.",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=False,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=["Authorization", "Content-Type"],
)

app.include_router(health_router, prefix="/api")
app.include_router(admin_moderation_router, prefix="/api")
app.include_router(assets_router, prefix="/api")
app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(listings_router, prefix="/api")
app.include_router(wallets_router, prefix="/api")
app.include_router(orders_router, prefix="/api")
app.include_router(reviews_router, prefix="/api")


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "running"}
