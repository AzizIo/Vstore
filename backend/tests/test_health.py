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

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 200
    assert response.json() == {
        "status": "ready",
        "checks": {"database": "ok", "redis": "ok"},
    }


def test_readiness_returns_503_when_a_dependency_is_unavailable(monkeypatch) -> None:
    async def database_ready() -> bool:
        return False

    async def redis_ready() -> bool:
        return True

    monkeypatch.setattr(health, "_database_ready", database_ready)
    monkeypatch.setattr(health, "_redis_ready", redis_ready)

    with TestClient(app) as client:
        response = client.get("/api/health/ready")

    assert response.status_code == 503
    assert response.json()["detail"] == {
        "status": "not_ready",
        "checks": {"database": "error", "redis": "ok"},
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
    }
