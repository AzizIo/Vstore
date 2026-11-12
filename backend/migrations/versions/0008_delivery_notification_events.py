"""Allow transactional outbox notifications for NFT delivery lifecycle events."""

from collections.abc import Sequence

from alembic import op

revision: str = "0008_delivery_notification_events"
down_revision: str | None = "0007_delivery_prepare_key"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Keep the existing reservation events valid while adding explicit delivery
    # lifecycle events. Existing rows are untouched and remain retryable.
    op.drop_constraint(
        "ck_telegram_notification_outbox_event_type",
        "telegram_notification_outbox",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_notification_outbox_event_type",
        "telegram_notification_outbox",
        "event_type IN ('order_created', 'order_cancelled', 'order_expired', "
        "'delivery_prepared', 'delivery_submitted', 'delivery_confirmed', "
        "'delivery_manual_review')",
    )


def downgrade() -> None:
    bind = op.get_bind()
    delivery_rows = bind.exec_driver_sql(
        "SELECT count(*) FROM telegram_notification_outbox "
        "WHERE event_type IN ('delivery_prepared', 'delivery_submitted', "
        "'delivery_confirmed', 'delivery_manual_review')"
    ).scalar_one()
    if delivery_rows:
        raise RuntimeError(
            "Cannot downgrade while delivery notification outbox rows exist"
        )
    op.drop_constraint(
        "ck_telegram_notification_outbox_event_type",
        "telegram_notification_outbox",
        type_="check",
    )
    op.create_check_constraint(
        "ck_telegram_notification_outbox_event_type",
        "telegram_notification_outbox",
        "event_type IN ('order_created', 'order_cancelled', 'order_expired')",
    )
