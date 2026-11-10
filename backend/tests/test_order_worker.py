import asyncio
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest

from app import main


async def test_expiration_worker_continues_after_unexpected_pass_error(monkeypatch) -> None:
    expiration_pass = AsyncMock(side_effect=[RuntimeError("temporary failure"), None])
    logger_exception = Mock()
    session_factory = Mock()

    @asynccontextmanager
    async def session_context():
        yield object()

    session_factory.side_effect = session_context
    sleep = AsyncMock(side_effect=[None, None, asyncio.CancelledError()])
    monkeypatch.setattr(
        main, "get_settings", lambda: SimpleNamespace(order_expiration_poll_seconds=1)
    )
    monkeypatch.setattr(main, "async_session_factory", session_factory)
    monkeypatch.setattr(main, "expire_pending_orders", expiration_pass)
    monkeypatch.setattr(main.logger, "exception", logger_exception)
    monkeypatch.setattr(main.asyncio, "sleep", sleep)

    with pytest.raises(asyncio.CancelledError):
        await main._expire_orders_periodically()

    assert expiration_pass.await_count == 2
    logger_exception.assert_called_once_with("Could not expire pending orders")
    assert session_factory.call_count == 2
