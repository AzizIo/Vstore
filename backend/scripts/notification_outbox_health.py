from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Sequence

from app.db.session import async_session_factory, dispose_engine
from app.notifications.diagnostics import (
    NotificationOutboxHealth,
    inspect_notification_outbox,
)


def _non_negative_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise argparse.ArgumentTypeError("must be an integer") from exc
    if parsed < 0:
        raise argparse.ArgumentTypeError("must be zero or greater")
    return parsed


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Inspect Telegram notification outbox health without changing rows."
    )
    parser.add_argument(
        "--json",
        action="store_true",
        dest="json_output",
        help="Print the stable JSON health document.",
    )
    parser.add_argument(
        "--max-due-age-seconds",
        type=_non_negative_int,
        default=300,
        help="Maximum healthy age for the oldest due pending row (default: 300).",
    )
    return parser


def render_human(summary: NotificationOutboxHealth) -> str:
    oldest_due = (
        f"{summary.oldest_due_pending_age_seconds}s"
        if summary.oldest_due_pending_age_seconds is not None
        else "n/a"
    )
    oldest_failed = (
        f"{summary.oldest_failed_age_seconds}s"
        if summary.oldest_failed_age_seconds is not None
        else "n/a"
    )
    lines = [
        f"Notification outbox: {summary.status.upper()}",
        (
            "Rows: "
            f"total={summary.total_count} pending={summary.pending_count} "
            f"processing={summary.processing_count} delivered={summary.delivered_count} "
            f"failed={summary.failed_count}"
        ),
        (
            f"Due pending={summary.due_pending_count}; "
            f"expired/missing processing leases={summary.expired_processing_lease_count}"
        ),
        f"Oldest due pending={oldest_due}; oldest failed={oldest_failed}",
    ]
    if summary.degraded_reasons:
        lines.append("Reasons: " + ", ".join(summary.degraded_reasons))
        lines.append("Action: inspect worker logs and failed rows before retrying deliveries.")
    return "\n".join(lines)


async def _inspect(max_due_age_seconds: int) -> NotificationOutboxHealth:
    try:
        async with async_session_factory() as session:
            return await inspect_notification_outbox(
                session,
                max_due_age_seconds=max_due_age_seconds,
            )
    finally:
        await dispose_engine()


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        summary = asyncio.run(_inspect(args.max_due_age_seconds))
    except Exception:
        # Do not echo exception strings: database drivers may include DSNs or other secrets.
        print(
            "Notification outbox diagnostic failed; check database connectivity and configuration.",
            file=sys.stderr,
        )
        return 2

    if args.json_output:
        print(json.dumps(summary.to_dict(), sort_keys=True))
    else:
        print(render_human(summary))
    return 1 if summary.status == "degraded" else 0


if __name__ == "__main__":
    raise SystemExit(main())
