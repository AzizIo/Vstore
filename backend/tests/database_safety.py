from __future__ import annotations

import os
from urllib.parse import urlsplit

import pytest

_ALLOWED_LOCAL_TEST_HOSTS = {"localhost", "127.0.0.1", "::1", "db", "postgres"}


def require_test_database_url(context: str) -> str:
    """Fail closed unless integration tests target an explicitly named local test DB."""

    url = os.getenv("TEST_DATABASE_URL")
    if not url:
        pytest.skip("TEST_DATABASE_URL is not configured")
    if not url.startswith("postgresql+asyncpg://"):
        pytest.fail(f"{context} require a PostgreSQL TEST_DATABASE_URL")

    try:
        parsed = urlsplit(url)
        # Accessing port validates malformed port values before any connection attempt.
        _ = parsed.port
    except ValueError:
        pytest.fail(f"{context} received an invalid TEST_DATABASE_URL")

    database_name = parsed.path.lstrip("/").split("?", maxsplit=1)[0]
    if not database_name or not (
        database_name.startswith("test_") or database_name.endswith("_test")
    ):
        pytest.fail(
            f"{context} require a dedicated test database named with a test_ prefix "
            "or _test suffix"
        )
    if parsed.hostname not in _ALLOWED_LOCAL_TEST_HOSTS:
        pytest.fail(
            f"{context} may only connect to localhost or a local PostgreSQL service alias"
        )
    return url
