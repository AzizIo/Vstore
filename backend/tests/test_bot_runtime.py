import asyncio
from types import SimpleNamespace
from unittest.mock import AsyncMock, Mock

import pytest
from aiogram.exceptions import TelegramNetworkError

from app import bot as bot_runtime
from app.core.config import Settings


class _SessionContext:
    async def __aenter__(self) -> object:
        return object()

    async def __aexit__(self, *args: object) -> None:
        return None


class _FakeBot:
    def __init__(self) -> None:
        self.session = SimpleNamespace(close=AsyncMock())
        self.set_my_commands = AsyncMock()


def _settings(*, bot_token: str | None = "123456:test-token") -> SimpleNamespace:
    return SimpleNamespace(
        bot_token=bot_token,
        telegram_mini_app_url="https://example.com/miniapp",
        telegram_mini_app_direct_link=None,
        notification_poll_seconds=0.001,
        notification_claim_lease_seconds=300,
        notification_batch_size=10,
    )


@pytest.mark.asyncio
async def test_main_refuses_to_start_without_bot_token(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    bot_factory = Mock()
    dispatcher_factory = Mock()
    monkeypatch.setattr(
        bot_runtime,
        "get_settings",
        lambda: _settings(bot_token=None),
    )
    monkeypatch.setattr(bot_runtime, "Bot", bot_factory)
    monkeypatch.setattr(bot_runtime, "create_dispatcher", dispatcher_factory)

    with pytest.raises(RuntimeError, match="BOT_TOKEN is required"):
        await bot_runtime.main()

    bot_factory.assert_not_called()
    dispatcher_factory.assert_not_called()


@pytest.mark.asyncio
async def test_main_starts_worker_and_closes_bot_session_after_polling(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bot = _FakeBot()
    dispatcher = SimpleNamespace(start_polling=AsyncMock())
    worker_started = asyncio.Event()
    worker_cancelled = asyncio.Event()
    bot_factory = Mock(return_value=fake_bot)
    dispatcher_factory = Mock(return_value=dispatcher)
    session_factory = Mock(return_value=fake_bot.session)

    async def worker(bot: object) -> None:
        assert bot is fake_bot
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            worker_cancelled.set()
            raise

    async def polling(bot: object) -> None:
        assert bot is fake_bot
        await asyncio.wait_for(worker_started.wait(), timeout=1)

    dispatcher.start_polling.side_effect = polling
    monkeypatch.setattr(bot_runtime, "get_settings", _settings)
    monkeypatch.setattr(bot_runtime, "Bot", bot_factory)
    monkeypatch.setattr(bot_runtime, "AiohttpSession", session_factory)
    monkeypatch.setattr(bot_runtime, "create_dispatcher", dispatcher_factory)
    monkeypatch.setattr(bot_runtime, "_run_notification_worker", worker)

    await bot_runtime.main()

    bot_factory.assert_called_once_with(
        token="123456:test-token",
        session=fake_bot.session,
    )
    session_factory.assert_called_once_with(
        timeout=bot_runtime.TELEGRAM_API_TIMEOUT_SECONDS
    )
    dispatcher_factory.assert_called_once_with()
    dispatcher.start_polling.assert_awaited_once_with(fake_bot)
    assert worker_started.is_set()
    assert worker_cancelled.is_set()
    fake_bot.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_main_cleans_up_worker_and_bot_session_when_polling_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bot = _FakeBot()
    dispatcher = SimpleNamespace(start_polling=AsyncMock())
    worker_started = asyncio.Event()
    worker_cancelled = asyncio.Event()

    async def worker(bot: object) -> None:
        assert bot is fake_bot
        worker_started.set()
        try:
            await asyncio.Event().wait()
        except asyncio.CancelledError:
            worker_cancelled.set()
            raise

    async def failing_polling(bot: object) -> None:
        assert bot is fake_bot
        await asyncio.wait_for(worker_started.wait(), timeout=1)
        raise RuntimeError("polling failed")

    dispatcher.start_polling.side_effect = failing_polling
    monkeypatch.setattr(bot_runtime, "get_settings", _settings)
    monkeypatch.setattr(bot_runtime, "Bot", Mock(return_value=fake_bot))
    monkeypatch.setattr(bot_runtime, "AiohttpSession", session_factory)
    monkeypatch.setattr(bot_runtime, "create_dispatcher", Mock(return_value=dispatcher))
    monkeypatch.setattr(bot_runtime, "_run_notification_worker", worker)

    with pytest.raises(RuntimeError, match="polling failed"):
        await bot_runtime.main()

    assert worker_cancelled.is_set()
    fake_bot.session.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_notification_worker_propagates_cancellation_and_releases_session(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    processing_started = asyncio.Event()
    session_exited = asyncio.Event()

    class TrackingSessionContext:
        async def __aenter__(self) -> object:
            return object()

        async def __aexit__(self, *args: object) -> None:
            session_exited.set()
            return None

    async def wait_for_cancel(
        session: object, sender: object, limit: int | None = None
    ) -> object:
        processing_started.set()
        await asyncio.Event().wait()
        return session

    monkeypatch.setattr(bot_runtime, "get_settings", _settings)
    monkeypatch.setattr(
        bot_runtime,
        "async_session_factory",
        lambda: TrackingSessionContext(),
    )
    monkeypatch.setattr(
        bot_runtime,
        "process_due_notifications",
        wait_for_cancel,
    )
    task = asyncio.create_task(
        bot_runtime._run_notification_worker(_FakeBot())  # type: ignore[arg-type]
    )

    await asyncio.wait_for(processing_started.wait(), timeout=1)
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert session_exited.is_set()


@pytest.mark.asyncio
async def test_notification_worker_keeps_running_after_temporary_processing_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    recovered = asyncio.Event()
    attempts = 0

    async def process(
        session: object, sender: object, limit: int | None = None
    ) -> SimpleNamespace:
        nonlocal attempts
        attempts += 1
        if attempts == 1:
            raise RuntimeError("temporary outbox failure")
        recovered.set()
        return SimpleNamespace(claimed=0)

    monkeypatch.setattr(bot_runtime, "get_settings", _settings)
    monkeypatch.setattr(
        bot_runtime,
        "async_session_factory",
        lambda: _SessionContext(),
    )
    monkeypatch.setattr(bot_runtime, "process_due_notifications", process)
    task = asyncio.create_task(
        bot_runtime._run_notification_worker(_FakeBot())  # type: ignore[arg-type]
    )

    try:
        await asyncio.wait_for(recovered.wait(), timeout=1)
    finally:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task

    assert attempts >= 2


@pytest.mark.asyncio
async def test_main_continues_when_telegram_command_menu_registration_fails(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    fake_bot = _FakeBot()
    fake_bot.set_my_commands.side_effect = TelegramNetworkError(
        method=SimpleNamespace(),
        message="temporary Telegram network failure",
    )
    dispatcher = SimpleNamespace(start_polling=AsyncMock())

    monkeypatch.setattr(bot_runtime, "get_settings", _settings)
    monkeypatch.setattr(bot_runtime, "Bot", Mock(return_value=fake_bot))
    session_factory = Mock(return_value=fake_bot.session)
    monkeypatch.setattr(bot_runtime, "AiohttpSession", session_factory)
    monkeypatch.setattr(bot_runtime, "create_dispatcher", Mock(return_value=dispatcher))
    monkeypatch.setattr(bot_runtime, "_run_notification_worker", AsyncMock())

    await bot_runtime.main()

    session_factory.assert_called_once_with(
        timeout=bot_runtime.TELEGRAM_API_TIMEOUT_SECONDS
    )
    fake_bot.set_my_commands.assert_awaited_once_with(bot_runtime.BOT_COMMANDS)
    dispatcher.start_polling.assert_awaited_once_with(fake_bot)
    fake_bot.session.close.assert_awaited_once()


@pytest.mark.parametrize(
    ("lease_seconds", "configured_batch_size", "expected_batch_size"),
    [
        (300, 10, 10),
        (300, 100, 10),
        (60, 10, 2),
        (15, 10, 1),
    ],
)
def test_notification_batch_is_bounded_by_claim_lease(
    lease_seconds: int,
    configured_batch_size: int,
    expected_batch_size: int,
) -> None:
    settings = Settings(
        _env_file=None,
        notification_claim_lease_seconds=lease_seconds,
        notification_batch_size=configured_batch_size,
    )

    assert bot_runtime.TELEGRAM_API_TIMEOUT_SECONDS == 15
    assert bot_runtime.notification_worker_batch_limit(settings) == expected_batch_size
