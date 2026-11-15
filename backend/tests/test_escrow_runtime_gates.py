import pytest

from app.core.config import Settings
from app.main import _should_mount_escrow_router


@pytest.mark.parametrize(
    ("environment", "preview_mode", "network", "expected"),
    [
        ("local", False, "testnet", True),
        ("development", False, "testnet", True),
        ("test", False, "testnet", True),
        ("preview", False, "testnet", True),
        ("production", True, "testnet", True),
        ("production", False, "testnet", False),
        ("production", True, "mainnet", False),
        ("production", False, "mainnet", False),
        ("staging", False, "testnet", False),
        ("", True, "testnet", False),
    ],
)
def test_escrow_api_mount_is_testnet_and_runtime_scoped(
    environment: str,
    preview_mode: bool,
    network: str,
    expected: bool,
) -> None:
    settings = Settings(
        environment=environment,
        preview_mode=preview_mode,
        ton_connect_network=network,
    )

    assert _should_mount_escrow_router(settings) is expected
