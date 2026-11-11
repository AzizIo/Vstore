"""Run the API-backed E2E safety preflight before migrations or test data writes."""

from __future__ import annotations

import asyncio

from scripts.e2e_safety import assert_e2e_environment


async def main() -> None:
    await assert_e2e_environment()
    print("E2E safety preflight passed: disposable PostgreSQL target and loopback Redis are valid.")


if __name__ == "__main__":
    asyncio.run(main())
