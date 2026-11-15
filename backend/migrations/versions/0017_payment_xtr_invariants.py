"""Enforce the integer-only Telegram Stars transaction contract.

Existing financial evidence is inspected before constraints are added. The
migration refuses to coerce or rewrite any historical amount/provider/currency.
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017_payment_xtr_invariants"
down_revision: str | None = "e20261115_escrow_actions"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    connection = op.get_bind()
    invalid_intents = connection.execute(
        sa.text(
            "SELECT count(*) FROM payment_intents "
            "WHERE amount <> trunc(amount)"
        )
    ).scalar_one()
    invalid_transactions = connection.execute(
        sa.text(
            "SELECT count(*) FROM payment_transactions "
            "WHERE provider <> 'telegram_stars' "
            "OR currency <> 'XTR' "
            "OR amount <> trunc(amount)"
        )
    ).scalar_one()

    if invalid_intents or invalid_transactions:
        raise RuntimeError(
            "Cannot enforce Telegram Stars XTR invariants: "
            f"{invalid_intents} fractional payment intents and "
            f"{invalid_transactions} invalid payment transactions exist. "
            "Reconcile financial evidence explicitly before retrying this migration; "
            "the migration never rewrites or rounds payment records."
        )

    op.create_check_constraint(
        "ck_payment_intents_amount_whole_stars",
        "payment_intents",
        "amount = trunc(amount)",
    )
    op.create_check_constraint(
        "ck_payment_transactions_amount_whole_stars",
        "payment_transactions",
        "amount = trunc(amount)",
    )
    op.create_check_constraint(
        "ck_payment_transactions_provider_stars",
        "payment_transactions",
        "provider = 'telegram_stars'",
    )
    op.create_check_constraint(
        "ck_payment_transactions_currency_stars",
        "payment_transactions",
        "currency = 'XTR'",
    )


def downgrade() -> None:
    # Removing these CHECK constraints weakens future validation. No payment
    # evidence is changed or deleted by this downgrade.
    op.drop_constraint(
        "ck_payment_transactions_currency_stars",
        "payment_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_transactions_provider_stars",
        "payment_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_transactions_amount_whole_stars",
        "payment_transactions",
        type_="check",
    )
    op.drop_constraint(
        "ck_payment_intents_amount_whole_stars",
        "payment_intents",
        type_="check",
    )
