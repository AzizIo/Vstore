import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app.api import health


class FakeConnection:
    def __init__(self, *, delay: float = 0, error: Exception | None = None) -> None:
        self.delay = delay
        self.error = error
        self.executed = False

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return False

    async def execute(self, statement) -> None:
        if self.delay:
            await asyncio.sleep(self.delay)
        if self.error is not None:
            raise self.error
        self.executed = True


class FakeEngine:
    def __init__(self, connection: FakeConnection) -> None:
        self.connection = connection

    def connect(self) -> FakeConnection:
        return self.connection


@pytest.mark.asyncio
async def test_database_probe_returns_true_when_query_succeeds(monkeypatch) -> None:
    connection = FakeConnection()
    monkeypatch.setattr(health, "engine", FakeEngine(connection))

    assert await health._database_ready() is True
    assert connection.executed is True


@pytest.mark.asyncio
async def test_database_probe_returns_false_when_query_fails(monkeypatch) -> None:
    connection = FakeConnection(error=ConnectionError("database unavailable"))
    monkeypatch.setattr(health, "engine", FakeEngine(connection))

    assert await health._database_ready() is False


@pytest.mark.asyncio
async def test_database_probe_returns_false_when_query_times_out(monkeypatch) -> None:
    connection = FakeConnection(delay=0.05)
    monkeypatch.setattr(health, "engine", FakeEngine(connection))
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.001)

    assert await health._database_ready() is False


def configure_redis(monkeypatch, *, ping_side_effect=None, close_side_effect=None):
    redis = AsyncMock()
    redis.ping.side_effect = ping_side_effect
    redis.aclose.side_effect = close_side_effect
    from_url = Mock(return_value=redis)
    monkeypatch.setattr(health.Redis, "from_url", from_url)
    monkeypatch.setattr(
        health,
        "settings",
        SimpleNamespace(redis_url="redis://redis:6379/0"),
    )
    return redis, from_url


@pytest.mark.asyncio
async def test_redis_probe_returns_true_and_closes_client(monkeypatch) -> None:
    redis, from_url = configure_redis(monkeypatch)

    assert await health._redis_ready() is True

    from_url.assert_called_once_with("redis://redis:6379/0", decode_responses=True)
    redis.ping.assert_awaited_once_with()
    redis.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_redis_probe_returns_false_and_closes_client_on_ping_error(monkeypatch) -> None:
    redis, _ = configure_redis(
        monkeypatch,
        ping_side_effect=ConnectionError("redis unavailable"),
    )

    assert await health._redis_ready() is False
    redis.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_redis_probe_returns_false_and_closes_client_on_timeout(monkeypatch) -> None:
    async def slow_ping() -> None:
        await asyncio.sleep(0.05)

    redis, _ = configure_redis(monkeypatch, ping_side_effect=slow_ping)
    monkeypatch.setattr(health, "CHECK_TIMEOUT_SECONDS", 0.001)

    assert await health._redis_ready() is False
    redis.aclose.assert_awaited_once_with()


@pytest.mark.asyncio
async def test_redis_probe_suppresses_client_close_error(monkeypatch) -> None:
    redis, _ = configure_redis(
        monkeypatch,
        close_side_effect=RuntimeError("close failed"),
    )

    assert await health._redis_ready() is True
    redis.aclose.assert_awaited_once_with()
