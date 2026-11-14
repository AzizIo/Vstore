from __future__ import annotations

import asyncio
import os
from pathlib import Path
from uuid import uuid4

import pytest
from alembic import command
from alembic.config import Config
from fastapi.testclient import TestClient
from sqlalchemy import select, text
from sqlalchemy.engine import make_url
from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from sqlalchemy.pool import NullPool
from sqlalchemy.pool import NullPool

from app.auth.dependencies import get_current_user
from app.core.config import get_settings
from app.db.models import AdminUserAuditLog, User
from app.db.session import get_db_session
from app.main import app
from tests.database_safety import require_test_database_url

pytestmark = pytest.mark.integration


@pytest.fixture(scope="module")
def admin_user_database() -> str:
    """Create a disposable DB so immutable audit rows cannot leak into other tests."""
    source_url = make_url(
        require_test_database_url("Admin user-management integration tests")
    )
    database_name = f"admin_user_{uuid4().hex[:12]}_test"
    temporary_url = source_url.set(database=database_name)
    maintenance_url = source_url.set(database="postgres")

    async def create_database() -> None:
        engine = create_async_engine(
            maintenance_url,
            poolclass=NullPool,
            isolation_level="AUTOCOMMIT",
        )
        try:
            async with engine.connect() as connection:
                await connection.execute(
                    text(f'CREATE DATABASE "{database_name}"')
                )
        finally:
            await engine.dispose()

    async def drop_database() -> None:
        engine = create_async_engine(
            maintenance_url,
            poolclass=NullPool,
            isolation_level="AUTOCOMMIT",
        )
        try:
            async with engine.connect() as connection:
                await connection.execute(
                    text(f'DROP DATABASE IF EXISTS "{database_name}" WITH (FORCE)')
                )
        finally:
            await engine.dispose()

    previous_url = os.environ.get("DATABASE_URL")
    created = False
    try:
        asyncio.run(create_database())
        created = True
        os.environ["DATABASE_URL"] = temporary_url.render_as_string(
            hide_password=False
        )
        get_settings.cache_clear()
        config = Config(str(Path(__file__).resolve().parents[1] / "alembic.ini"))
        command.upgrade(config, "head")
        yield temporary_url.render_as_string(hide_password=False)
    finally:
        if previous_url is None:
            os.environ.pop("DATABASE_URL", None)
        else:
            os.environ["DATABASE_URL"] = previous_url
        get_settings.cache_clear()
        if created:
            asyncio.run(drop_database())

@pytest.mark.asyncio
async def test_block_unblock_idempotency_audit_and_immutability(
    admin_user_database: str,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    engine = create_async_engine(
        admin_user_database, pool_pre_ping=True, poolclass=NullPool
    )
    factory = async_sessionmaker(engine, expire_on_commit=False)
    suffix = uuid4().int % 1_000_000_000
    admin = User(telegram_id=7_000_000_000 + suffix, first_name="Admin fixture")
    target = User(
        telegram_id=8_000_000_000 + suffix,
        username=f"beta_user_{suffix}",
        first_name="Beta user",
    )
    try:
        async with factory.begin() as session:
            session.add_all([admin, target])
        settings = get_settings()
        previous_admin_ids = list(settings.admin_telegram_ids)
        monkeypatch.setattr(settings, "admin_telegram_ids", [admin.telegram_id])

        previous_overrides = app.dependency_overrides.copy()
        app.dependency_overrides[get_current_user] = lambda: admin

        async def override_database_session():
            async with factory() as session:
                yield session

        app.dependency_overrides[get_db_session] = override_database_session

        try:
            client = TestClient(app)
            block_payload = {"reason": "Repeated policy violations confirmed"}
            block_headers = {"Idempotency-Key": f"block-user-{uuid4()}"}
            block_url = f"/api/admin/users/{target.id}/block"

            first = client.post(block_url, headers=block_headers, json=block_payload)
            assert first.status_code == 200, first.text
            block_result = first.json()
            assert block_result["is_blocked"] is True
            first_audit_id = block_result["audit"]["id"]

            replay = client.post(block_url, headers=block_headers, json=block_payload)
            assert replay.status_code == 200, replay.text
            assert replay.json()["audit"]["id"] == first_audit_id
            assert replay.json()["is_blocked"] is True

            mismatch = client.post(
                block_url,
                headers=block_headers,
                json={"reason": "A different reason for the same operation"},
            )
            assert mismatch.status_code == 409

            duplicate_block = client.post(
                block_url,
                headers={"Idempotency-Key": f"second-block-{uuid4()}"},
                json=block_payload,
            )
            assert duplicate_block.status_code == 409

            unblock_payload = {"reason": "Restriction review has been completed"}
            unblock_headers = {"Idempotency-Key": f"unblock-user-{uuid4()}"}
            unblock_url = f"/api/admin/users/{target.id}/unblock"
            unblocked = client.post(
                unblock_url, headers=unblock_headers, json=unblock_payload
            )
            assert unblocked.status_code == 200, unblocked.text
            unblock_audit_id = unblocked.json()["audit"]["id"]
            assert unblocked.json()["is_blocked"] is False

            unblock_replay = client.post(
                unblock_url, headers=unblock_headers, json=unblock_payload
            )
            assert unblock_replay.status_code == 200, unblock_replay.text
            assert unblock_replay.json()["audit"]["id"] == unblock_audit_id

            searched = client.get(
                "/api/admin/users", params={"q": str(target.telegram_id), "limit": 10}
            )
            assert searched.status_code == 200, searched.text
            assert searched.json()["total"] == 1
            assert searched.json()["items"][0]["telegram_id"] == target.telegram_id

            detail = client.get(f"/api/admin/users/{target.id}")
            assert detail.status_code == 200, detail.text
            assert detail.json()["is_blocked"] is False
            assert "access_token" not in detail.text
            assert "private_key" not in detail.text
            assert "seed_phrase" not in detail.text

            audit_page = client.get(f"/api/admin/users/{target.id}/audit")
            assert audit_page.status_code == 200, audit_page.text
            assert {row["action"] for row in audit_page.json()["items"]} >= {
                "blocked",
                "unblocked",
            }

            async with factory() as session:
                persisted_target = await session.get(User, target.id)
                assert persisted_target is not None
                assert persisted_target.is_blocked is False
                audit_rows = list(
                    (
                        await session.scalars(
                            select(AdminUserAuditLog).where(
                                AdminUserAuditLog.target_user_id == target.id
                            )
                        )
                    ).all()
                )
                assert {row.action for row in audit_rows} == {"blocked", "unblocked"}
                assert len(audit_rows) == 2

                for statement, parameters in (
                    (
                        "UPDATE admin_user_audit_log SET reason = 'tampered' WHERE id = :id",
                        {"id": audit_rows[0].id},
                    ),
                    (
                        "DELETE FROM admin_user_audit_log WHERE id = :id",
                        {"id": audit_rows[0].id},
                    ),
                    ("TRUNCATE TABLE admin_user_audit_log", {}),
                ):
                    with pytest.raises(DBAPIError):
                        async with session.begin_nested():
                            await session.execute(text(statement), parameters)
                await session.rollback()
        finally:
            if "client" in locals():
                client.close()
            app.dependency_overrides.clear()
            app.dependency_overrides.update(previous_overrides)
            monkeypatch.setattr(settings, "admin_telegram_ids", previous_admin_ids)
    finally:
        await engine.dispose()
