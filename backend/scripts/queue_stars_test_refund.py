"""Queue a real Telegram Test Server Stars charge for an explicit test refund.

This command changes only one captured charge in the guarded local test database.
The separate refund worker then calls refundStarPayment through Telegram's test API.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
import uuid
from datetime import UTC, datetime

from sqlalchemy import func, select

from app.db.models import Order
from app.db.payments import PaymentEvent, PaymentIntent, PaymentRefund, PaymentTransaction
from app.db.session import async_session_factory, dispose_engine
from app.orders.payment_service import PaymentConflict, queue_stars_refund
from app.payments_test_bot import _validate_test_bot_runtime


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--order-id", required=True, type=uuid.UUID)
    parser.add_argument(
        "--confirm-test-refund",
        action="store_true",
        help=(
            "Required acknowledgement that one captured Telegram Test Server charge "
            "will be refunded"
        ),
    )
    return parser


async def _queue_refund(order_id: uuid.UUID) -> dict[str, str]:
    now = datetime.now(UTC)

    async with async_session_factory.begin() as session:
        # Preserve the application's shared lock order: order -> intent -> transaction -> refund.
        order = await session.scalar(
            select(Order).where(Order.id == order_id).with_for_update()
        )
        if order is None:
            raise PaymentConflict("Test order was not found")

        intent = await session.scalar(
            select(PaymentIntent)
            .where(PaymentIntent.order_id == order.id)
            .with_for_update()
        )
        if intent is None or intent.provider != "telegram_stars" or intent.currency != "XTR":
            raise PaymentConflict("Order has no Telegram Stars payment intent")
        if intent.status != "paid":
            raise PaymentConflict("Only a paid test intent can be queued for a refund")

        transactions = list(
            (
                await session.scalars(
                    select(PaymentTransaction)
                    .where(PaymentTransaction.payment_intent_id == intent.id)
                    .with_for_update()
                )
            ).all()
        )
        if len(transactions) != 1:
            raise PaymentConflict("Expected exactly one test charge for this order")

        transaction = transactions[0]
        if (
            transaction.provider != "telegram_stars"
            or transaction.currency != "XTR"
            or transaction.status != "captured"
            or not transaction.telegram_payment_charge_id
        ):
            raise PaymentConflict("The test charge is not in a refundable captured state")

        existing_refund = await session.scalar(
            select(PaymentRefund).where(
                PaymentRefund.payment_transaction_id == transaction.id
            )
        )
        event_id = f"manual-test-refund:{transaction.id}"
        existing_event = await session.scalar(
            select(PaymentEvent).where(
                PaymentEvent.provider == "telegram_stars",
                PaymentEvent.provider_event_id == event_id,
            )
        )
        if existing_refund is not None or existing_event is not None:
            raise PaymentConflict("A refund workflow already exists for this test charge")

        transaction.status = "refund_pending"
        transaction.refund_requested_at = now
        transaction.last_error_code = "manual_test_refund"

        other_captured = await session.scalar(
            select(func.count())
            .select_from(PaymentTransaction)
            .where(
                PaymentTransaction.payment_intent_id == intent.id,
                PaymentTransaction.id != transaction.id,
                PaymentTransaction.status == "captured",
            )
        )
        if other_captured == 0:
            intent.status = "refund_pending"
            intent.refund_requested_at = now
            intent.last_error_code = "manual_test_refund"

        refund = await queue_stars_refund(
            session,
            transaction,
            reason_code="manual_test_refund",
            now=now,
        )
        digest = hashlib.sha256(
            (
                f"{intent.id}:{transaction.id}:"
                f"{transaction.telegram_payment_charge_id}:manual_test_refund"
            ).encode()
        ).hexdigest()
        session.add(
            PaymentEvent(
                payment_intent_id=intent.id,
                payment_transaction_id=transaction.id,
                provider="telegram_stars",
                provider_event_id=event_id,
                event_type="refund_requested",
                payload_sha256=digest,
            )
        )
        await session.flush()

        return {
            "order_id": str(order.id),
            "payment_transaction_id": str(transaction.id),
            "refund_id": str(refund.id),
            "transaction_status": transaction.status,
            "refund_status": refund.status,
            "action": "queued_for_telegram_test_server_refund",
        }


async def _run(order_id: uuid.UUID) -> dict[str, str]:
    try:
        return await _queue_refund(order_id)
    finally:
        await dispose_engine()


def main() -> int:
    args = _parser().parse_args()
    if not args.confirm_test_refund:
        print(
            "Refusing to queue a refund without --confirm-test-refund.",
            file=sys.stderr,
        )
        return 2

    try:
        _validate_test_bot_runtime()
    except RuntimeError as exc:
        print(f"Test refund guard rejected the runtime: {exc}", file=sys.stderr)
        return 2

    try:
        result = asyncio.run(_run(args.order_id))
    except (PaymentConflict, ValueError) as exc:
        print(f"Could not queue test refund: {exc}", file=sys.stderr)
        return 2
    except Exception:
        # Database exceptions can contain connection details; never echo them.
        print(
            "Could not queue the test refund. Check the disposable test database and migrations.",
            file=sys.stderr,
        )
        return 2

    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
