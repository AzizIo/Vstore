import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from logging import getLogger

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.exc import SQLAlchemyError

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.api.listings import router as listings_router
from app.api.orders import router as orders_router
from app.api.users import router as users_router
from app.api.wallets import router as wallets_router
from app.core.config import get_settings
from app.db.session import async_session_factory, dispose_engine
from app.orders.service import expire_pending_orders

logger = getLogger(__name__)


async def _expire_orders_periodically() -> None:
    poll_interval = get_settings().order_expiration_poll_seconds
    while True:
        await asyncio.sleep(poll_interval)
        try:
            async with async_session_factory() as session:
                await expire_pending_orders(session)
        except SQLAlchemyError:
            logger.exception("Could not expire pending orders")


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    expiration_task = asyncio.create_task(_expire_orders_periodically())
    try:
        yield
    finally:
        expiration_task.cancel()
        try:
            await expiration_task
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
app.include_router(auth_router, prefix="/api")
app.include_router(users_router, prefix="/api")
app.include_router(listings_router, prefix="/api")
app.include_router(wallets_router, prefix="/api")
app.include_router(orders_router, prefix="/api")


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "running"}
