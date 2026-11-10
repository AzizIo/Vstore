"""Scope NFT assets and their external IDs by TON network."""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0002_asset_network_scope"
down_revision: str | None = "0001_initial_marketplace"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "nft_assets",
        sa.Column("network", sa.String(length=16), server_default="mainnet", nullable=False),
    )
    op.drop_constraint("uq_nft_assets_type_external_id", "nft_assets", type_="unique")
    op.create_unique_constraint(
        "uq_nft_assets_type_network_external_id",
        "nft_assets",
        ["asset_type", "network", "external_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_nft_assets_type_network_external_id", "nft_assets", type_="unique"
    )
    op.create_unique_constraint(
        "uq_nft_assets_type_external_id",
        "nft_assets",
        ["asset_type", "external_id"],
    )
    op.drop_column("nft_assets", "network")