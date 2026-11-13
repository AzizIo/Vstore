"""Add explicit pending-review state to listing lifecycle."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0011_listing_pending_review"
down_revision: str | None = "0010_seller_reviews"
branch_labels: str | Sequence[str] | None = None
depends_on: str | None = None


def upgrade() -> None:
    # A pending submission reserves the NFT against duplicate listings, but
    # remains excluded from the public catalogue and order creation.
    op.drop_index("uq_listings_open_asset", table_name="listings")
    op.create_index(
        "uq_listings_open_asset",
        "listings",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text(
            "status IN ('active', 'reserved', 'pending_review')"
        ),
    )


def downgrade() -> None:
    bind = op.get_bind()
    pending = bind.execute(
        sa.text("SELECT count(*) FROM listings WHERE status = 'pending_review'")
    ).scalar_one()
    if pending:
        raise RuntimeError(
            "Cannot downgrade while pending-review listings exist; resolve them first."
        )
    op.drop_index("uq_listings_open_asset", table_name="listings")
    op.create_index(
        "uq_listings_open_asset",
        "listings",
        ["asset_id"],
        unique=True,
        postgresql_where=sa.text("status IN ('active', 'reserved')"),
    )
