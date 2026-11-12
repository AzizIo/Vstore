"""Add immutable order-verified seller reviews."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010_seller_reviews"
down_revision: str | None = "0009_admin_moderation_audit"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "seller_reviews",
        sa.Column("id", sa.Uuid(), nullable=False),
        sa.Column("order_id", sa.Uuid(), nullable=False),
        sa.Column("buyer_id", sa.Uuid(), nullable=False),
        sa.Column("seller_id", sa.Uuid(), nullable=False),
        sa.Column("rating", sa.Integer(), nullable=False),
        sa.Column("comment", sa.String(length=2000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.CheckConstraint("rating BETWEEN 1 AND 5", name="ck_seller_reviews_rating_range"),
        sa.CheckConstraint(
            "comment IS NULL OR length(comment) <= 2000",
            name="ck_seller_reviews_comment_length",
        ),
        sa.CheckConstraint("buyer_id <> seller_id", name="ck_seller_reviews_not_self"),
        sa.ForeignKeyConstraint(["order_id"], ["orders.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["buyer_id"], ["users.id"], ondelete="RESTRICT"),
        sa.ForeignKeyConstraint(["seller_id"], ["users.id"], ondelete="RESTRICT"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("order_id", name="uq_seller_reviews_order"),
    )
    op.create_index(
        "ix_seller_reviews_seller_created",
        "seller_reviews",
        ["seller_id", "created_at", "id"],
    )
    op.create_index(
        "ix_seller_reviews_buyer_order",
        "seller_reviews",
        ["buyer_id", "order_id"],
    )


def downgrade() -> None:
    bind = op.get_bind()
    count = bind.execute(sa.text("SELECT count(*) FROM seller_reviews")).scalar_one()
    if count:
        raise RuntimeError(
            "Cannot downgrade while seller reviews exist; preserve review provenance."
        )
    op.drop_index("ix_seller_reviews_buyer_order", table_name="seller_reviews")
    op.drop_index("ix_seller_reviews_seller_created", table_name="seller_reviews")
    op.drop_table("seller_reviews")
