from __future__ import annotations

import asyncio
import hashlib
import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from enum import Enum
from typing import Protocol
from urllib.parse import urlsplit

from aiogram import Bot
from aiogram.client.session.aiohttp import AiohttpSession
from aiogram.client.telegram import TelegramAPIServer
from aiogram.exceptions import TelegramAPIError, TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import get_settings
from app.db.models import Order
from app.db.payments import PaymentEvent, PaymentIntent, PaymentRefund, PaymentTransaction
from app.db.session import async_session_factory

logger = logging.getLogger(__name__)
PAGE_SIZE = 100
MAX_RECONCILIATION_PAGES = 100


class RefundCallOutcome(str, Enum):
    SUCCEEDED = "succeeded"
    RETRYABLE_FAILURE = "retryable_failure"
    PERMANENT_FAILURE = "permanent_failure"
    AMBIGUOUS = "ambiguous"


class RefundLookupResult(str, Enum):
    REFUNDED = "refunded"
    NOT_REFUNDED = "not_refunded"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class RefundCallResult:
    outcome: RefundCallOutcome
    error_code: str | None = None
    retry_after_seconds: int | None = None


class StarsRefundProvider(Protocol):
    async def refund_payment(
        self, *, payer_telegram_id: int, telegram_payment_charge_id: str
    ) -> RefundCallResult: ...

    async def lookup_refund(
        self, *, telegram_payment_charge_id: str
    ) -> RefundLookupResult: ...


@dataclass(frozen=True)
class RefundClaim:
    refund_id: uuid.UUID
    claim_token: uuid.UUID
    transaction_id: uuid.UUID
    intent_id: uuid.UUID
    order_id: uuid.UUID
    payer_telegram_id: int
    telegram_payment_charge_id: str
    attempt_count: int
    reconciliation_count: int
    needs_reconciliation: bool


@dataclass(frozen=True)
class RefundBatchResult:
    claimed: int = 0
    succeeded: int = 0
    retried: int = 0
    reconciliations: int = 0
    manual_review: int = 0


class TelegramStarsRefundProvider:
    """Adapter for Telegram Stars refunds, used only with a dedicated test bot."""

    def __init__(self, bot: Bot) -> None:
        # A caller cannot bypass the test-only runtime guard by directly
        # instantiating the real Telegram adapter in application code.
        expected_test_token = _validate_worker_runtime()
        provided_token = getattr(bot, "token", None)
        if provided_token is None or str(provided_token) != expected_test_token:
            raise RuntimeError("Refund adapter requires the dedicated test bot token")
        self._bot = bot

    async def refund_payment(
        self, *, payer_telegram_id: int, telegram_payment_charge_id: str
    ) -> RefundCallResult:
        try:
            succeeded = await self._bot.refund_star_payment(
                user_id=payer_telegram_id,
                telegram_payment_charge_id=telegram_payment_charge_id,
            )
            if succeeded:
                return RefundCallResult(RefundCallOutcome.SUCCEEDED)
            # A false/empty response is not proof that Telegram did not refund.
            return RefundCallResult(
                RefundCallOutcome.AMBIGUOUS, error_code="provider_no_confirmation"
            )
        except TelegramRetryAfter as exc:
            # A rate-limit response explicitly rejects this request; retry after delay.
            return RefundCallResult(
                RefundCallOutcome.RETRYABLE_FAILURE,
                error_code="telegram_rate_limited",
                retry_after_seconds=int(exc.retry_after),
            )
        except TelegramBadRequest as exc:
            message = str(exc).lower()
            if "already refunded" in message or "charge_already_refunded" in message:
                # Never issue another refund based only on this error; reconcile first.
                return RefundCallResult(
                    RefundCallOutcome.AMBIGUOUS, error_code="provider_already_refunded"
                )
            return RefundCallResult(
                RefundCallOutcome.PERMANENT_FAILURE, error_code="telegram_bad_request"
            )
        except (TelegramAPIError, TimeoutError, OSError):
            # A timeout or server/network error may happen after the side effect.
            return RefundCallResult(
                RefundCallOutcome.AMBIGUOUS, error_code="provider_outcome_unknown"
            )
        except Exception:
            # Unknown errors are conservatively ambiguous, never blindly retried.
            logger.exception("Unexpected Telegram refund adapter error")
            return RefundCallResult(
                RefundCallOutcome.AMBIGUOUS, error_code="provider_outcome_unknown"
            )

    async def lookup_refund(
        self, *, telegram_payment_charge_id: str
    ) -> RefundLookupResult:
        """Search transaction history completely enough to prove refund/no-refund.

        Telegram documents that a refund transaction reuses the original charge ID.
        Outgoing entries have receiver set; incoming payments have source set. If
        pagination is capped or the original charge cannot be found, return UNKNOWN.
        """

        found_original_charge = False
        offset = 0
        try:
            for _ in range(MAX_RECONCILIATION_PAGES):
                response = await self._bot.get_star_transactions(
                    offset=offset, limit=PAGE_SIZE
                )
                transactions = list(getattr(response, "transactions", []) or [])
                for transaction in transactions:
                    if str(getattr(transaction, "id", "")) != telegram_payment_charge_id:
                        continue
                    if getattr(transaction, "receiver", None) is not None:
                        return RefundLookupResult.REFUNDED
                    if getattr(transaction, "source", None) is not None:
                        found_original_charge = True

                if len(transactions) < PAGE_SIZE:
                    return (
                        RefundLookupResult.NOT_REFUNDED
                        if found_original_charge
                        else RefundLookupResult.UNKNOWN
                    )
                offset += len(transactions)
        except Exception:
            logger.exception("Could not reconcile Telegram refund transaction history")
            return RefundLookupResult.UNKNOWN

        # A partial history cannot prove absence of a refund; never retry on it.
        return RefundLookupResult.UNKNOWN


async def claim_due_refunds(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[RefundClaim]:
    settings = get_settings()
    current_time = now or datetime.now(UTC)
    batch_limit = limit or settings.payment_refund_batch_size
    claims: list[RefundClaim] = []

    async with session.begin():
        due = (
            (PaymentRefund.status.in_({"queued", "retry_wait"}))
            & (PaymentRefund.next_attempt_at <= current_time)
        )
        abandoned_lease = (
            (PaymentRefund.status == "processing")
            & (PaymentRefund.locked_until.is_not(None))
            & (PaymentRefund.locked_until <= current_time)
        )
        due_reconciliation = (
            (PaymentRefund.status == "reconciliation_required")
            & (PaymentRefund.next_attempt_at <= current_time)
        )
        jobs = (
            await session.scalars(
                select(PaymentRefund)
                .where(or_(due, abandoned_lease, due_reconciliation))
                .order_by(PaymentRefund.next_attempt_at, PaymentRefund.created_at)
                .limit(batch_limit)
                .with_for_update(skip_locked=True)
            )
        ).all()

        for job in jobs:
            previous_status = job.status
            needs_reconciliation = previous_status in {
                "processing",
                "reconciliation_required",
            }
            transaction_data = (
                await session.execute(
                    select(
                        PaymentTransaction.id,
                        PaymentTransaction.payment_intent_id,
                        PaymentTransaction.payer_telegram_id,
                        PaymentTransaction.telegram_payment_charge_id,
                        PaymentIntent.order_id,
                        PaymentTransaction.status,
                    )
                    .join(
                        PaymentIntent,
                        PaymentIntent.id == PaymentTransaction.payment_intent_id,
                    )
                    .where(PaymentTransaction.id == job.payment_transaction_id)
                )
            ).first()
            if transaction_data is None:
                logger.error(
                    "Refund job %s requires manual review: transaction is missing",
                    job.id,
                )
                job.status = "manual_review"
                job.last_error_code = "refund_transaction_missing"
                job.lease_token = None
                job.locked_until = None
                continue

            (
                transaction_id,
                intent_id,
                payer_id,
                charge_id,
                order_id,
                transaction_status,
            ) = transaction_data
            if transaction_status != "refund_pending":
                if transaction_status == "refunded":
                    job.status = "succeeded"
                    job.completed_at = job.completed_at or current_time
                else:
                    # A refund row must never authorize a charge that is still captured.
                    logger.error(
                        "Refund job %s requires manual review: transaction status is %s",
                        job.id,
                        transaction_status,
                    )
                    job.status = "manual_review"
                    job.last_error_code = "transaction_not_refund_pending"
                job.lease_token = None
                job.locked_until = None
                continue

            token = uuid.uuid4()
            job.status = "processing"
            job.lease_token = token
            job.locked_until = current_time + timedelta(
                seconds=settings.payment_refund_lease_seconds
            )
            if needs_reconciliation:
                job.reconciliation_count += 1
                job.last_reconciled_at = current_time
            else:
                job.attempt_count += 1
                job.request_started_at = current_time

            claims.append(
                RefundClaim(
                    refund_id=job.id,
                    claim_token=token,
                    transaction_id=transaction_id,
                    intent_id=intent_id,
                    order_id=order_id,
                    payer_telegram_id=payer_id,
                    telegram_payment_charge_id=charge_id,
                    attempt_count=job.attempt_count,
                    reconciliation_count=job.reconciliation_count,
                    needs_reconciliation=needs_reconciliation,
                )
            )

    return claims


def _retry_delay(attempt_count: int) -> int:
    settings = get_settings()
    exponent = min(max(attempt_count - 1, 0), 30)
    return min(
        settings.payment_refund_retry_base_seconds * (2**exponent),
        settings.payment_refund_retry_max_seconds,
    )


async def _persist_claim_result(
    session: AsyncSession,
    claim: RefundClaim,
    *,
    now: datetime,
    target_status: str,
    error_code: str | None = None,
    next_attempt_at: datetime | None = None,
    succeeded: bool = False,
    record_failure_event: bool = False,
) -> bool:
    """Persist a worker result only while this worker still owns the lease."""

    async with session.begin():
        header = (
            await session.execute(
                select(PaymentTransaction.payment_intent_id, PaymentIntent.order_id)
                .join(PaymentIntent, PaymentIntent.id == PaymentTransaction.payment_intent_id)
                .where(PaymentTransaction.id == claim.transaction_id)
            )
        ).first()
        if header is None:
            return False
        intent_id, order_id = header

        # Shared lock order: order -> intent -> transaction -> refund job.
        order = await session.scalar(
            select(Order).where(Order.id == order_id).with_for_update()
        )
        intent = await session.scalar(
            select(PaymentIntent).where(PaymentIntent.id == intent_id).with_for_update()
        )
        transaction = await session.scalar(
            select(PaymentTransaction)
            .where(PaymentTransaction.id == claim.transaction_id)
            .with_for_update()
        )
        job = await session.scalar(
            select(PaymentRefund)
            .where(PaymentRefund.id == claim.refund_id)
            .with_for_update()
        )
        if order is None or intent is None or transaction is None or job is None:
            return False
        checked_at = max(now, datetime.now(UTC))
        if (
            job.status != "processing"
            or job.lease_token != claim.claim_token
            or job.locked_until is None
            or job.locked_until <= checked_at
        ):
            # A late worker must not overwrite a newer worker's result. If Telegram
            # already completed the refund, the next worker will reconcile it.
            return False

        if transaction.status not in {"refund_pending", "refunded"}:
            # The transaction state may have changed after the claim. Even a
            # provider success must not rewrite a non-refundable ledger state.
            job.status = "manual_review"
            job.last_error_code = "transaction_not_refund_pending"
            job.lease_token = None
            job.locked_until = None
            logger.error(
                "Refund result rejected for transaction %s with status %s",
                transaction.id,
                transaction.status,
            )
            await session.flush()
            return False

        if succeeded or transaction.status == "refunded":
            transaction.status = "refunded"
            transaction.refunded_at = transaction.refunded_at or checked_at
            transaction.last_error_code = None
            job.status = "succeeded"
            job.completed_at = job.completed_at or checked_at
            job.last_error_code = None
            job.lease_token = None
            job.locked_until = None
            digest = hashlib.sha256(
                f"{transaction.id}:{transaction.telegram_payment_charge_id}:refunded".encode()
            ).hexdigest()
            event_id = f"refund-worker-succeeded:{transaction.id}"
            existing_event = await session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "telegram_stars",
                    PaymentEvent.provider_event_id == event_id,
                )
            )
            if existing_event is None:
                session.add(
                    PaymentEvent(
                        payment_intent_id=intent.id,
                        payment_transaction_id=transaction.id,
                        provider="telegram_stars",
                        provider_event_id=event_id,
                        event_type="refund_succeeded",
                        payload_sha256=digest,
                    )
                )
            elif existing_event.payload_sha256 != digest:
                raise RuntimeError("Refund success event idempotency digest mismatch")

            captured_count = await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.payment_intent_id == intent.id,
                    PaymentTransaction.status == "captured",
                )
            )
            pending_count = await session.scalar(
                select(func.count())
                .select_from(PaymentTransaction)
                .where(
                    PaymentTransaction.payment_intent_id == intent.id,
                    PaymentTransaction.status == "refund_pending",
                )
            )
            if captured_count == 0 and pending_count == 0:
                intent.status = "refunded"
                intent.refunded_at = intent.refunded_at or now
            await session.flush()
            return True

        if transaction.status != "refund_pending":
            target_status = "manual_review"
            error_code = error_code or "transaction_not_refundable"

        job.status = target_status
        job.last_error_code = (error_code or "")[:64] or None
        transaction.last_error_code = (error_code or "")[:64] or None
        job.next_attempt_at = next_attempt_at or job.next_attempt_at
        job.lease_token = None
        job.locked_until = None

        if target_status == "manual_review":
            job.completed_at = None
            logger.error(
                "Refund transaction %s requires manual review: %s",
                transaction.id,
                job.last_error_code or "unspecified_refund_failure",
            )

        if record_failure_event:
            digest = hashlib.sha256(
                f"{transaction.id}:{claim.attempt_count}:{error_code or 'refund_failed'}".encode()
            ).hexdigest()
            event_id = f"refund-worker-failed:{transaction.id}:{claim.attempt_count}"
            existing_event = await session.scalar(
                select(PaymentEvent).where(
                    PaymentEvent.provider == "telegram_stars",
                    PaymentEvent.provider_event_id == event_id,
                )
            )
            if existing_event is None:
                session.add(
                    PaymentEvent(
                        payment_intent_id=intent.id,
                        payment_transaction_id=transaction.id,
                        provider="telegram_stars",
                        provider_event_id=event_id,
                        event_type="refund_failed",
                        payload_sha256=digest,
                    )
                )
            elif existing_event.payload_sha256 != digest:
                raise RuntimeError("Refund failure event idempotency digest mismatch")

        await session.flush()
        return True


async def process_due_refunds(
    session: AsyncSession,
    provider: StarsRefundProvider,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> RefundBatchResult:
    """Claim work in PostgreSQL, call Telegram outside transactions, then persist.

    Any timeout/ambiguous result goes to reconciliation. A stale processing lease
    also reconciles first; it never causes an automatic second refund request.
    """

    # Enforce the same safety boundary even if this orchestration function is
    # called directly instead of through the module entry point.
    _validate_worker_runtime()
    settings = get_settings()
    current_time = now or datetime.now(UTC)
    claims = await claim_due_refunds(session, now=current_time, limit=limit)
    succeeded = retried = reconciliations = manual_review = 0

    for claim in claims:
        if claim.needs_reconciliation:
            try:
                lookup = await provider.lookup_refund(
                    telegram_payment_charge_id=claim.telegram_payment_charge_id
                )
            except Exception:
                logger.exception("Refund reconciliation failed for %s", claim.transaction_id)
                lookup = RefundLookupResult.UNKNOWN

            result_time = max(current_time, datetime.now(UTC))
            if lookup is RefundLookupResult.REFUNDED:
                persisted = await _persist_claim_result(
                    session,
                    claim,
                    now=result_time,
                    target_status="succeeded",
                    succeeded=True,
                )
                succeeded += int(persisted)
            elif lookup is RefundLookupResult.NOT_REFUNDED:
                if claim.reconciliation_count < 2:
                    # Transaction history may lag the refund side effect. Require
                    # two separated complete scans before deciding whether it can
                    # be escalated; negative scans never authorize a second refund.
                    target = "reconciliation_required"
                    next_at = result_time + timedelta(
                        seconds=max(
                            settings.payment_refund_reconcile_delay_seconds,
                            _retry_delay(claim.attempt_count),
                        )
                    )
                    reconciliations += 1
                else:
                    # We cannot prove that Telegram did not accept the prior call.
                    # Keep the funds/customer state for human resolution rather than
                    # risk issuing a second refund against the same charge.
                    target = "manual_review"
                    next_at = None
                    manual_review += 1
                await _persist_claim_result(
                    session,
                    claim,
                    now=result_time,
                    target_status=target,
                    error_code="refund_absent_after_reconciliation",
                    next_attempt_at=next_at,
                )
            else:
                if claim.reconciliation_count >= settings.payment_refund_max_reconcile_attempts:
                    target = "manual_review"
                    next_at = None
                    manual_review += 1
                else:
                    target = "reconciliation_required"
                    next_at = result_time + timedelta(
                        seconds=settings.payment_refund_reconcile_delay_seconds
                    )
                    reconciliations += 1
                await _persist_claim_result(
                    session,
                    claim,
                    now=result_time,
                    target_status=target,
                    error_code="refund_outcome_unknown",
                    next_attempt_at=next_at,
                )
            continue

        try:
            result = await provider.refund_payment(
                payer_telegram_id=claim.payer_telegram_id,
                telegram_payment_charge_id=claim.telegram_payment_charge_id,
            )
        except Exception:
            # A transport error can occur after Telegram has accepted the refund.
            logger.exception("Refund request raised unexpectedly for %s", claim.transaction_id)
            result = RefundCallResult(
                RefundCallOutcome.AMBIGUOUS, error_code="provider_outcome_unknown"
            )

        result_time = max(current_time, datetime.now(UTC))
        if result.outcome is RefundCallOutcome.SUCCEEDED:
            persisted = await _persist_claim_result(
                session,
                claim,
                now=result_time,
                target_status="succeeded",
                succeeded=True,
            )
            succeeded += int(persisted)
        elif result.outcome is RefundCallOutcome.AMBIGUOUS:
            if claim.reconciliation_count >= settings.payment_refund_max_reconcile_attempts:
                target = "manual_review"
                next_at = None
                manual_review += 1
            else:
                target = "reconciliation_required"
                next_at = result_time + timedelta(
                    seconds=settings.payment_refund_reconcile_delay_seconds
                )
                reconciliations += 1
            await _persist_claim_result(
                session,
                claim,
                now=result_time,
                target_status=target,
                error_code=result.error_code or "provider_outcome_unknown",
                next_attempt_at=next_at,
            )
        elif result.outcome is RefundCallOutcome.RETRYABLE_FAILURE:
            if claim.attempt_count >= settings.payment_refund_max_attempts:
                target = "manual_review"
                next_at = None
                manual_review += 1
            else:
                target = "retry_wait"
                if result.retry_after_seconds is not None:
                    # Never retry before a provider-specified Retry-After, even if
                    # it exceeds our configured exponential-backoff cap.
                    delay = max(1, result.retry_after_seconds)
                else:
                    delay = _retry_delay(claim.attempt_count)
                next_at = result_time + timedelta(seconds=delay)
                retried += 1
            await _persist_claim_result(
                session,
                claim,
                now=result_time,
                target_status=target,
                error_code=result.error_code or "refund_retryable_failure",
                next_attempt_at=next_at,
                record_failure_event=True,
            )
        else:
            manual_review += 1
            await _persist_claim_result(
                session,
                claim,
                now=result_time,
                target_status="manual_review",
                error_code=result.error_code or "refund_permanent_failure",
                record_failure_event=True,
            )

    return RefundBatchResult(
        claimed=len(claims),
        succeeded=succeeded,
        retried=retried,
        reconciliations=reconciliations,
        manual_review=manual_review,
    )


def _validate_worker_runtime() -> str:
    settings = get_settings()
    if not settings.telegram_stars_test_enabled:
        raise RuntimeError("Refund worker is disabled unless Telegram Stars test mode is enabled")
    if settings.environment.lower() != "test":
        raise RuntimeError("Refund worker may run only with environment=test")
    if settings.telegram_stars_test_bot_token is None:
        raise RuntimeError("A dedicated Telegram Stars test bot token is required")
    token = settings.telegram_stars_test_bot_token.get_secret_value()
    if not settings.bot_token:
        raise RuntimeError(
            "BOT_TOKEN must be configured so the test token can be checked as distinct"
        )
    if token == settings.bot_token:
        raise RuntimeError("The test refund worker must not use the production bot token")

    try:
        parsed = urlsplit(settings.database_url)
        database_name = parsed.path.lstrip("/").split("?", maxsplit=1)[0]
    except ValueError as exc:
        raise RuntimeError("Refund worker database URL is invalid") from exc
    if parsed.scheme != "postgresql+asyncpg":
        raise RuntimeError("Refund worker requires a dedicated PostgreSQL test database")
    if not (
        database_name.startswith("test_") or database_name.endswith("_test")
    ):
        raise RuntimeError("Refund worker database name must start with test_ or end with _test")
    if parsed.hostname not in {"localhost", "127.0.0.1", "::1", "db", "postgres"}:
        raise RuntimeError("Refund worker only permits a local/test PostgreSQL host")

    return token


def _test_api_server() -> TelegramAPIServer:
    """Route all Bot API calls to Telegram's isolated test environment."""

    return TelegramAPIServer(
        base="https://api.telegram.org/bot{token}/test/{method}",
        file="https://api.telegram.org/file/bot{token}/test/{path}",
    )


async def run_refund_worker() -> None:
    """Run the opt-in local/test worker; no production runtime starts it implicitly."""

    token = _validate_worker_runtime()
    settings = get_settings()
    session = AiohttpSession(api=_test_api_server())
    bot = Bot(token=token, session=session)
    provider = TelegramStarsRefundProvider(bot)
    try:
        while True:
            try:
                async with async_session_factory() as session:
                    result = await process_due_refunds(session, provider)
                if result.claimed == 0:
                    await asyncio.sleep(settings.payment_refund_poll_seconds)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.exception("Telegram Stars refund worker failed; reconciliation will retry")
                await asyncio.sleep(settings.payment_refund_poll_seconds)
    finally:
        await bot.session.close()


def main() -> None:
    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_refund_worker())


if __name__ == "__main__":
    main()
