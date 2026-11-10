import asyncio
from types import SimpleNamespace

import pytest

from app import main


class _SessionContext:
    async def __aenter__(self):
        return object()

    async def __aexit__(self, exc_type, exc, traceback):
        return False


@pytest.mark.asyncio
async def test_expiration_worker_retries_after_unexpected_pass_error(monkeypatch) -> None:
    sleep_calls = 0
    pass_calls = 0

    async def fake_sleep(_interval: int) -> None:
        nonlocal sleep_calls
        sleep_calls += 1
        if sleep_calls == 3:
            raise asyncio.CancelledError

    async def expire_once(_session) -> int:
        nonlocal pass_calls
        pass_calls += 1
        if pass_calls == 1:
            raise RuntimeError("temporary worker failure")
        return 0

    monkeypatch.setattr(main.asyncio, "sleep", fake_sleep)
    monkeypatch.setattr(main, "async_session_factory", lambda: _SessionContext())
    monkeypatch.setattr(main, "expire_pending_orders", expire_once)
    monkeypatch.setattr(
        main, "get_settings", lambda: SimpleNamespace(order_expiration_poll_seconds=1)
    )

    with pytest.raises(asyncio.CancelledError):
        await main._expire_orders_periodically()

    assert sleep_calls == 3
    assert pass_calls == 2
