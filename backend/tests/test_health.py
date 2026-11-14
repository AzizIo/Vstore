from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient

from app.api import health
from app.main import app


@pytest.fixture(autouse=True)
def default_database_migrations_ready(monkeypatch) -> None:
    async def migrations_ready() -> bool:
        return True

    monkeypatch.setattr(health, "_database_migrations_ready", migrations_ready)


def test_readiness_returns_each_dependency_status(monkeypatch) -> None:
    async def database_ready() -> bool:
        return True

    async def redis_ready() -> bool:
        return True

    monkeypatch.setattr(health, "_database_ready", database_ready)
    monkeypatch.setattr(health, "_redis_ready", redis_ready)
    monkeypatch.setattr(health, "_authentication_ready", lambda: True)
    monkeypatch.setattr(health, "_ton_connect_proof_ready", lambda: True)
    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(
            ton_connect_allowed_domains=["shop.example.test"],
            ton_connect_network="testnet",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "ok",
            "database_migrations": "ok",
            "redis": "ok",
            "authentication": "ok",
            "ton_connect_proof": "ok",
            "ton_connect_proof_domains": ["shop.example.test"],
        },
    }


def test_readiness_returns_503_when_a_dependency_is_unavailable(monkeypatch) -> None:
    async def database_ready() -> bool:
        return False

    async def redis_ready() -> bool:
        return True

    monkeypatch.setattr(health, "_database_ready", database_ready)
    monkeypatch.setattr(health, "_redis_ready", redis_ready)
    monkeypatch.setattr(health, "_authentication_ready", lambda: True)
    monkeypatch.setattr(health, "_ton_connect_proof_ready", lambda: True)
    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(
            ton_connect_allowed_domains=["shop.example.test"],
            ton_connect_network="testnet",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "not_ready",
        "checks": {
            "database": "error",
            "database_migrations": "ok",
            "redis": "ok",
            "authentication": "ok",
            "ton_connect_proof": "ok",
            "ton_connect_proof_domains": ["shop.example.test"],
        },
    }


def test_readiness_returns_503_when_database_migrations_are_behind(monkeypatch) -> None:
    async def dependency_ready() -> bool:
        return True

    async def migrations_behind() -> bool:
        return False

    monkeypatch.setattr(health, "_database_ready", dependency_ready)
    monkeypatch.setattr(health, "_database_migrations_ready", migrations_behind)
    monkeypatch.setattr(health, "_redis_ready", dependency_ready)
    monkeypatch.setattr(health, "_authentication_ready", lambda: True)
    monkeypatch.setattr(health, "_ton_connect_proof_ready", lambda: True)
    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(
            ton_connect_allowed_domains=["shop.example.test"],
            ton_connect_network="testnet",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["checks"]["database_migrations"] == "error"


def test_readiness_reports_both_dependencies_unavailable(monkeypatch) -> None:
    async def database_ready() -> bool:
        return False

    async def redis_ready() -> bool:
        return False

    monkeypatch.setattr(health, "_database_ready", database_ready)
    monkeypatch.setattr(health, "_redis_ready", redis_ready)
    monkeypatch.setattr(health, "_authentication_ready", lambda: True)
    monkeypatch.setattr(health, "_ton_connect_proof_ready", lambda: True)
    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(
            ton_connect_allowed_domains=["shop.example.test"],
            ton_connect_network="testnet",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"]["checks"] == {
        "database": "error",
        "database_migrations": "ok",
        "redis": "error",
        "authentication": "ok",
        "ton_connect_proof": "ok",
        "ton_connect_proof_domains": ["shop.example.test"],
    }


def test_readiness_returns_503_when_authentication_is_not_configured(monkeypatch) -> None:
    async def dependency_ready() -> bool:
        return True

    monkeypatch.setattr(health, "_database_ready", dependency_ready)
    monkeypatch.setattr(health, "_redis_ready", dependency_ready)
    monkeypatch.setattr(health, "_authentication_ready", lambda: False)
    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(
            ton_connect_allowed_domains=["shop.example.test"],
            ton_connect_network="testnet",
        ),
    )

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "not_ready",
        "checks": {
            "database": "ok",
            "database_migrations": "ok",
            "redis": "ok",
            "authentication": "error",
            "ton_connect_proof": "ok",
            "ton_connect_proof_domains": ["shop.example.test"],
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



def test_readiness_exposes_disabled_ton_connect_without_breaking_catalogue_health(
    monkeypatch,
) -> None:
    async def dependency_ready() -> bool:
        return True

    monkeypatch.setattr(health, "_database_ready", dependency_ready)
    monkeypatch.setattr(health, "_redis_ready", dependency_ready)
    monkeypatch.setattr(health, "_authentication_ready", lambda: True)
    monkeypatch.setattr(health, "_ton_connect_proof_ready", lambda: False)

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {
            "database": "ok",
            "database_migrations": "ok",
            "redis": "ok",
            "authentication": "ok",
            "ton_connect_proof": "error",
            "ton_connect_proof_domains": [],
        },
    }


def test_ton_connect_proof_readiness_uses_backend_configuration(monkeypatch) -> None:
    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(
            ton_connect_allowed_domains=["shop.example.test"],
            ton_connect_network="testnet",
        ),
    )

    assert health._ton_connect_proof_ready() is True

    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(
            ton_connect_allowed_domains=[],
            ton_connect_network="testnet",
        ),
    )

    assert health._ton_connect_proof_ready() is False
