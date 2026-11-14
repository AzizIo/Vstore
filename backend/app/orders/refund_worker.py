from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import Decimal
from typing import Any, Protocol

from aiogram.exceptions import TelegramBadRequest, TelegramRetryAfter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.config import get_settings
from app.db.payments import PaymentRefundJob, PaymentTransaction
from app.orders.payment_service import PaymentConflict, record_stars_refund_result

logger = logging.getLogger(__name__)


class RefundProvider(Protocol):
    async def get_star_transactions(self, *, offset: int, limit: int) -> Any:
        """Return Telegram StarTransactions for the dedicated test bot."""

    async def refund_star_payment(
        self, *, user_id: int, telegram_payment_charge_id: str
    ) -> bool:
        """Refund one successful Stars charge."""


@dataclass(frozen=True, slots=True)
class RefundClaim:
    job_id: uuid.UUID
    transaction_id: uuid.UUID
    claim_token: uuid.UUID
    telegram_payment_charge_id: str
    payer_telegram_id: int
    currency: str
    amount: Decimal
    provider: str
    transaction_status: str
    request_started_at: datetime | None
    attempt_count: int


@dataclass(frozen=True, slots=True)
class RefundHistory:
    complete: bool
    original_payment_seen: bool
    refund_seen: bool
    pages_read: int


@dataclass(frozen=True, slots=True)
class RefundWorkerResult:
    claimed: int = 0
    refunded: int = 0
    reconciled: int = 0
    deferred: int = 0
    manual_review: int = 0
    lease_lost: int = 0


class RefundLeaseLost(RuntimeError):
    """A different worker owns the refund job now."""


def _retry_delay(attempt_count: int) -> int:
    settings = get_settings()
    delay = settings.telegram_stars_refund_retry_base_seconds * (
        2 ** max(attempt_count - 1, 0)
    )
    return min(delay, settings.telegram_stars_refund_retry_max_seconds)


async def claim_due_refund_jobs(
    session: AsyncSession,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> list[RefundClaim]:
    """Claim due jobs with SKIP LOCKED; provider I/O happens after commit."""

    settings = get_settings()
    current_time = now or datetime.now(UTC)
    batch_limit = limit or settings.telegram_stars_refund_batch_size
    claims: list[RefundClaim] = []

    async with session.begin():
        result = await session.execute(
            select(PaymentRefundJob, PaymentTransaction)
            .join(
                PaymentTransaction,
                PaymentTransaction.id == PaymentRefundJob.payment_transaction_id,
            )
            .where(
                or_(
                    (
                        PaymentRefundJob.status.in_(("pending", "reconciling"))
                        & (PaymentRefundJob.next_attempt_at <= current_time)
                    ),
                    (
                        (PaymentRefundJob.status == "processing")
                        & (PaymentRefundJob.lease_expires_at <= current_time)
                    ),
                )
            )
            .order_by(
                PaymentRefundJob.next_attempt_at.asc(),
                PaymentRefundJob.created_at.asc(),
            )
            .limit(batch_limit)
            .with_for_update(skip_locked=True, of=PaymentRefundJob)
        )

        for job, transaction in result:
            token = uuid.uuid4()
            job.status = "processing"
            job.claim_token = token
            job.lease_expires_at = current_time + timedelta(
                seconds=settings.telegram_stars_refund_lease_seconds
            )
            job.attempt_count += 1
            claims.append(
                RefundClaim(
                    job_id=job.id,
                    transaction_id=transaction.id,
                    claim_token=token,
                    telegram_payment_charge_id=transaction.telegram_payment_charge_id,
                    payer_telegram_id=transaction.payer_telegram_id,
                    currency=transaction.currency,
                    amount=Decimal(transaction.amount),
                    provider=transaction.provider,
                    transaction_status=transaction.status,
                    request_started_at=job.request_started_at,
                    attempt_count=job.attempt_count,
                )
            )

    return claims


async def _heartbeat(
    session: AsyncSession, claim: RefundClaim, *, now: datetime | None = None
) -> None:
    settings = get_settings()
    current_time = now or datetime.now(UTC)
    async with session.begin():
        job = await session.scalar(
            select(PaymentRefundJob)
            .where(
                PaymentRefundJob.id == claim.job_id,
                PaymentRefundJob.status == "processing",
                PaymentRefundJob.claim_token == claim.claim_token,
            )
            .with_for_update()
        )
        if job is None:
            raise RefundLeaseLost("Refund job lease was lost")
        job.lease_expires_at = current_time + timedelta(
            seconds=settings.telegram_stars_refund_lease_seconds
        )


async def _scan_provider_history(
    session: AsyncSession,
    provider: RefundProvider,
    claim: RefundClaim,
) -> RefundHistory:
    """Find the exact incoming charge and any refund with the same provider ID."""

    settings = get_settings()
    page_size = settings.telegram_stars_refund_history_page_size
    max_pages = settings.telegram_stars_refund_history_max_pages
    offset = 0
    pages_read = 0
    original_seen = False
    refund_seen = False
    complete = False

    while pages_read < max_pages:
        response = await provider.get_star_transactions(offset=offset, limit=page_size)
        transactions = list(getattr(response, "transactions", ()) or ())
        pages_read += 1

        for item in transactions:
            if str(getattr(item, "id", "")) != claim.telegram_payment_charge_id:
                continue

            source = getattr(item, "source", None)
            source_user = getattr(source, "user", None) if source is not None else None
            amount = getattr(item, "amount", None)
            if (
                source is not None
                and getattr(source, "type", None) == "user"
                and getattr(source, "transaction_type", None) == "invoice_payment"
                and getattr(source_user, "id", None) == claim.payer_telegram_id
                and amount is not None
                and Decimal(str(amount)) == claim.amount
            ):
                original_seen = True

            receiver = getattr(item, "receiver", None)
            receiver_user = (
                getattr(receiver, "user", None) if receiver is not None else None
            )
            if (
                receiver is not None
                and getattr(receiver, "type", None) == "user"
                and getattr(receiver_user, "id", None) == claim.payer_telegram_id
            ):
                refund_seen = True

        if refund_seen:
            complete = True
            break
        if not transactions or len(transactions) < page_size:
            complete = True
            break

        offset += len(transactions)
        await _heartbeat(session, claim)

    return RefundHistory(
        complete=complete,
        original_payment_seen=original_seen,
        refund_seen=refund_seen,
        pages_read=pages_read,
    )


async def _set_job_state(
    session: AsyncSession,
    claim: RefundClaim,
    *,
    status: str,
    error_code: str | None = None,
    delay_seconds: int = 0,
    clear_request_started: bool = False,
    provider_refund_seen_at: datetime | None = None,
    now: datetime | None = None,
) -> bool:
    current_time = now or datetime.now(UTC)
    async with session.begin():
        job = await session.scalar(
            select(PaymentRefundJob)
            .where(
                PaymentRefundJob.id == claim.job_id,
                PaymentRefundJob.status == "processing",
                PaymentRefundJob.claim_token == claim.claim_token,
            )
            .with_for_update()
        )
        if job is None:
            return False
        job.status = status
        job.claim_token = None
        job.lease_expires_at = None
        job.next_attempt_at = current_time + timedelta(seconds=max(0, delay_seconds))
        job.last_error_code = error_code
        if clear_request_started:
            job.request_started_at = None
        if provider_refund_seen_at is not None:
            job.provider_refund_seen_at = provider_refund_seen_at
        return True


async def _mark_request_started(
    session: AsyncSession, claim: RefundClaim, *, now: datetime | None = None
) -> None:
    current_time = now or datetime.now(UTC)
    async with session.begin():
        job = await session.scalar(
            select(PaymentRefundJob)
            .where(
                PaymentRefundJob.id == claim.job_id,
                PaymentRefundJob.status == "processing",
                PaymentRefundJob.claim_token == claim.claim_token,
            )
            .with_for_update()
        )
        if job is None:
            raise RefundLeaseLost("Refund job lease was lost before provider request")
        job.request_started_at = current_time


async def _mark_refunded(
    session: AsyncSession, claim: RefundClaim, *, now: datetime | None = None
) -> bool:
    current_time = now or datetime.now(UTC)
    # This durable transaction update is idempotent. If the process crashes
    # before the job row is finalized, the next pass recovers from Telegram history.
    await record_stars_refund_result(
        session,
        transaction_id=claim.transaction_id,
        provider_event_id=f"refund-history:{claim.transaction_id}",
        succeeded=True,
        now=current_time,
    )

    return await _set_job_state(
        session,
        claim,
        status="succeeded",
        provider_refund_seen_at=current_time,
        now=current_time,
    )


async def _defer(
    session: AsyncSession,
    claim: RefundClaim,
    *,
    error_code: str,
    uncertain_provider_result: bool,
    retry_after_seconds: int | None = None,
    now: datetime | None = None,
) -> tuple[bool, bool]:
    """Return (deferred, manual_review). Never blindly resend an uncertain refund."""

    settings = get_settings()
    current_time = now or datetime.now(UTC)
    if claim.attempt_count >= settings.telegram_stars_refund_max_attempts:
        changed = await _set_job_state(
            session,
            claim,
            status="manual_review",
            error_code=error_code,
            now=current_time,
        )
        return False, changed

    status = "reconciling" if uncertain_provider_result else "pending"
    changed = await _set_job_state(
        session,
        claim,
        status=status,
        error_code=error_code,
        delay_seconds=(
            retry_after_seconds
            if retry_after_seconds is not None
            else _retry_delay(claim.attempt_count)
        ),
        clear_request_started=not uncertain_provider_result,
        now=current_time,
    )
    return changed, False


async def _process_claim(
    session: AsyncSession,
    provider: RefundProvider,
    claim: RefundClaim,
    *,
    now: datetime | None = None,
) -> str:
    current_time = now or datetime.now(UTC)

    if claim.transaction_status == "refunded":
        return (
            "refunded"
            if await _set_job_state(
                session, claim, status="succeeded", now=current_time
            )
            else "lease_lost"
        )
    if (
        claim.transaction_status != "refund_pending"
        or claim.currency != "XTR"
        or claim.provider != "telegram_stars"
        or not claim.telegram_payment_charge_id
        or claim.payer_telegram_id <= 0
        or claim.amount <= 0
        or claim.amount != claim.amount.to_integral_value()
    ):
        changed = await _set_job_state(
            session,
            claim,
            status="manual_review",
            error_code="transaction_not_refundable",
            now=current_time,
        )
        return "manual_review" if changed else "lease_lost"

    try:
        history = await _scan_provider_history(session, provider, claim)
    except RefundLeaseLost:
        return "lease_lost"
    except Exception:
        logger.exception(
            "Could not reconcile Telegram Stars history for refund job %s",
            claim.job_id,
        )
        uncertain = claim.request_started_at is not None
        deferred, manual = await _defer(
            session,
            claim,
            error_code="history_unavailable",
            uncertain_provider_result=uncertain,
            now=current_time,
        )
        return "manual_review" if manual else "deferred" if deferred else "lease_lost"

    if history.refund_seen:
        try:
            return (
                "refunded"
                if await _mark_refunded(session, claim, now=current_time)
                else "lease_lost"
            )
        except PaymentConflict:
            logger.exception(
                "Persisted refund evidence conflicts for transaction %s",
                claim.transaction_id,
            )
            changed = await _set_job_state(
                session,
                claim,
                status="manual_review",
                error_code="refund_evidence_conflict",
                now=current_time,
            )
            return "manual_review" if changed else "lease_lost"

    if not history.complete:
        deferred, manual = await _defer(
            session,
            claim,
            error_code="history_scan_incomplete",
            uncertain_provider_result=claim.request_started_at is not None,
            now=current_time,
        )
        return "manual_review" if manual else "deferred" if deferred else "lease_lost"

    if not history.original_payment_seen:
        deferred, manual = await _defer(
            session,
            claim,
            error_code="original_charge_not_found_in_history",
            uncertain_provider_result=claim.request_started_at is not None,
            now=current_time,
        )
        return "manual_review" if manual else "deferred" if deferred else "lease_lost"

    # A previous API request may have succeeded even if the caller timed out or
    # crashed. History has been checked, but a missing row can be eventual consistency.
    # Keep reconciling; never issue a second refund request for an uncertain attempt.
    if claim.request_started_at is not None:
        deferred, manual = await _defer(
            session,
            claim,
            error_code="refund_request_outcome_uncertain",
            uncertain_provider_result=True,
            now=current_time,
        )
        return "manual_review" if manual else "deferred" if deferred else "lease_lost"

    try:
        await _mark_request_started(session, claim, now=current_time)
        result = await provider.refund_star_payment(
            user_id=claim.payer_telegram_id,
            telegram_payment_charge_id=claim.telegram_payment_charge_id,
        )
        if result is not True:
            deferred, manual = await _defer(
                session,
                claim,
                error_code="provider_did_not_confirm_refund",
                uncertain_provider_result=True,
                now=current_time,
            )
            return "manual_review" if manual else "deferred" if deferred else "lease_lost"
        return (
            "refunded"
            if await _mark_refunded(session, claim, now=current_time)
            else "lease_lost"
        )
    except RefundLeaseLost:
        return "lease_lost"
    except TelegramRetryAfter as exc:
        deferred, manual = await _defer(
            session,
            claim,
            error_code="telegram_rate_limited",
            uncertain_provider_result=False,
            retry_after_seconds=max(1, int(exc.retry_after)),
            now=current_time,
        )
        return "manual_review" if manual else "deferred" if deferred else "lease_lost"
    except TelegramBadRequest as exc:
        message = str(exc).casefold()
        if "already refunded" in message or "charge_already_refunded" in message:
            # Do not trust an error string as proof: verify the exact outgoing row.
            try:
                history_after_error = await _scan_provider_history(session, provider, claim)
            except Exception:
                logger.exception(
                    "Could not verify already-refunded charge %s",
                    claim.telegram_payment_charge_id,
                )
                history_after_error = RefundHistory(False, False, False, 0)
            if history_after_error.refund_seen:
                return (
                    "refunded"
                    if await _mark_refunded(session, claim, now=current_time)
                    else "lease_lost"
                )
        changed = await _set_job_state(
            session,
            claim,
            status="manual_review",
            error_code="telegram_rejected_refund_request",
            now=current_time,
        )
        return "manual_review" if changed else "lease_lost"
    except Exception:
        # The request may have reached Telegram before the connection failed.
        # Reconciliation only; the next pass will not invoke refundStarPayment again.
        logger.exception(
            "Telegram Stars refund result is uncertain for transaction %s",
            claim.transaction_id,
        )
        deferred, manual = await _defer(
            session,
            claim,
            error_code="provider_result_uncertain",
            uncertain_provider_result=True,
            now=current_time,
        )
        return "manual_review" if manual else "deferred" if deferred else "lease_lost"


async def run_refund_worker_pass(
    session_factory: async_sessionmaker[AsyncSession],
    provider: RefundProvider,
    *,
    now: datetime | None = None,
    limit: int | None = None,
) -> RefundWorkerResult:
    """Run one bounded refund batch using independent short DB transactions."""

    settings = get_settings()
    if not settings.telegram_stars_refund_worker_enabled:
        raise PaymentConflict("Telegram Stars refund worker is disabled")
    if not settings.telegram_stars_test_enabled:
        raise PaymentConflict("Telegram Stars test payments are disabled")
    if settings.environment.lower() not in {"local", "development", "test"}:
        raise PaymentConflict(
            "Telegram Stars refund worker is unavailable outside test environments"
        )
    if settings.telegram_stars_test_bot_token is None:
        raise PaymentConflict("A dedicated Telegram Stars test bot token is required")

    current_time = now or datetime.now(UTC)
    async with session_factory() as session:
        claims = await claim_due_refund_jobs(session, now=current_time, limit=limit)

    refunded = deferred = manual_review = lease_lost = 0
    for claim in claims:
        async with session_factory() as session:
            outcome = await _process_claim(session, provider, claim, now=current_time)
        refunded += int(outcome == "refunded")
        deferred += int(outcome == "deferred")
        manual_review += int(outcome == "manual_review")
        lease_lost += int(outcome == "lease_lost")

    return RefundWorkerResult(
        claimed=len(claims),
        refunded=refunded,
        reconciled=refunded,
        deferred=deferred,
        manual_review=manual_review,
        lease_lost=lease_lost,
    )
