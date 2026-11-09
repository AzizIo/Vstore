from contextlib import asynccontextmanager
from collections.abc import AsyncIterator

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.auth import router as auth_router
from app.api.health import router as health_router
from app.core.config import get_settings
from app.db.session import dispose_engine


@asynccontextmanager
async def lifespan(_: FastAPI) -> AsyncIterator[None]:
    yield
    await dispose_engine()


settings = get_settings()

app = FastAPI(
    title="VILTARA SHOP API",
    version="0.1.0",
    description="Backend API for the VILTARA SHOP Telegram marketplace.",
    lifespan=lifespan,
)

app.add_middleware(\n    CORSMiddleware,\n    allow_origins=settings.cors_allowed_origins,\n    allow_credentials=False,\n    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],\n    allow_headers=["Authorization", "Content-Type"],\n)\n\napp.include_router(health_router, prefix="/api")\napp.include_router(auth_router, prefix="/api")


@app.get("/", tags=["meta"])
async def root() -> dict[str, str]:
    return {"name": settings.app_name, "status": "running"}
