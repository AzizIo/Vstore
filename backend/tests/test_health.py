from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.main import app


def test_readiness_returns_each_dependency_status(monkeypatch) -> None:
    async def database_ready() -> bool:
        return True

    async def redis_ready() -> bool:
        return True

    monkeypatch.setattr(health, "_database_ready", database_ready)
    monkeypatch.setattr(health, "_redis_ready", redis_ready)
    monkeypatch.setattr(health, "_authentication_ready", lambda: True)

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok", "authentication": "ok"},
    }


def test_readiness_returns_503_when_a_dependency_is_unavailable(monkeypatch) -> None:
    async def database_ready() -> bool:
        return False

    async def redis_ready() -> bool:
        return True

    monkeypatch.setattr(health, "_database_ready", database_ready)
    monkeypatch.setattr(health, "_redis_ready", redis_ready)
    monkeypatch.setattr(health, "_authentication_ready", lambda: True)

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "not_ready",
        "checks": {
            "database": "error",
            "redis": "ok",
            "authentication": "ok",
        },
    }


def test_readiness_reports_both_dependencies_unavailable(monkeypatch) -> None:
    async def database_ready() -> bool:
        return False

    async def redis_ready() -> bool:
        return False

    monkeypatch.setattr(health, "_database_ready", database_ready)
    monkeypatch.setattr(health, "_redis_ready", redis_ready)

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["checks"] == {
        "database": "error",
        "redis": "error",
        "authentication": "ok",
    }


def test_readiness_returns_503_when_authentication_is_not_configured(monkeypatch) -> None:
    async def dependency_ready() -> bool:
        return True

    monkeypatch.setattr(health, "_database_ready", dependency_ready)
    monkeypatch.setattr(health, "_redis_ready", dependency_ready)
    monkeypatch.setattr(health, "_authentication_ready", lambda: False)

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "not_ready",
        "checks": {
            "database": "ok",
            "redis": "ok",
            "authentication": "error",
        },
    }


@pytest.mark.parametrize(
    ("bot_token", "secret_key", "expected"),
    [
        (None, "s" * 32, False),
        ("", "s" * 32, False),
        ("   ", "s" * 32, False),
        ("bot-token", None, False),
        ("bot-token", "", False),
        ("bot-token", "short", False),
        ("bot-token", " " * 32, False),
        ("bot-token", "s" * 32, True),
    ],
)
def test_authentication_readiness_requires_usable_credentials(
    monkeypatch,
    bot_token: str | None,
    secret_key: str | None,
    expected: bool,
) -> None:
    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(bot_token=bot_token, auth_secret_key=secret_key),
    )

    assert health._authentication_ready() is expected
