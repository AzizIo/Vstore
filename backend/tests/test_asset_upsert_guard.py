from __future__ import annotations

import re

from sqlalchemy.dialects import postgresql
from sqlalchemy.dialects.postgresql import insert as pg_insert

from app.api.assets import _open_listing_exists
from app.db.models import AssetType, NFTAsset


def test_open_listing_guard_correlates_to_upsert_target() -> None:
    statement = (
        pg_insert(NFTAsset)
        .values(
            asset_type=AssetType.TON_NFT,
            network="mainnet",
            external_id="correlation-test-nft",
        )
        .on_conflict_do_update(
            index_elements=["asset_type", "network", "external_id"],
            set_={"name": "refreshed"},
            where=~_open_listing_exists(),
        )
        .returning(NFTAsset.id)
    )

    sql = str(statement.compile(dialect=postgresql.dialect()))
    guard_match = re.search(
        r"WHERE NOT \\(EXISTS \\((.*?)\\)\\)\\s+RETURNING",
        sql,
        flags=re.DOTALL,
    )

    assert guard_match is not None, sql
    guard_sql = guard_match.group(1)
    from_match = re.search(r"\\bFROM\\s+(.+?)\\s+WHERE\\b", guard_sql, flags=re.DOTALL)

    assert from_match is not None, guard_sql
    assert from_match.group(1).strip() == "listings", guard_sql
    assert "WHERE listings.asset_id = nft_assets.id" in guard_sql
