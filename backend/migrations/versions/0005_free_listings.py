"""Remove legacy listing and order price snapshots from the free MVP."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0005_free_listings"
down_revision: str | None = "0004_tg_notif_outbox"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # Historical values were display-only fields, not payments or a financial ledger.
    op.drop_constraint("ck_orders_price_positive", "orders", type_="check")
    op.drop_column("orders", "price_currency")
    op.drop_column("orders", "price_amount")

    op.drop_constraint("ck_listings_price_positive", "listings", type_="check")
    op.drop_column("listings", "price_currency")
    op.drop_column("listings", "price_amount")


def downgrade() -> None:
    # A downgrade restores nullable legacy columns but cannot recreate the old display values.
    op.add_column(
        "listings",
        sa.Column("price_amount", sa.Numeric(precision=24, scale=9), nullable=True),
    )
    op.add_column(
        "listings",
        sa.Column("price_currency", sa.String(length=32), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("price_amount", sa.Numeric(precision=24, scale=9), nullable=True),
    )
    op.add_column(
        "orders",
        sa.Column("price_currency", sa.String(length=32), nullable=True),
    )
