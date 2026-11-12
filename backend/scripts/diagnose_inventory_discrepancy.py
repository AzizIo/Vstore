"""Read-only TON NFT inventory diagnostic for Issue #44.

Run from backend/ with the application's normal .env. This script does not call
GET /api/assets/me or POST /api/assets/me/sync because the GET route can upsert
rows and sync mutates inventory. It queries TON Center directly and reads the DB.
"""
from __future__ import annotations

import argparse
import asyncio
import json
from datetime import UTC, datetime
from uuid import UUID

from sqlalchemy import or_, select

from app.assets.ton_nft.address import normalize_address
from app.assets.ton_nft.dependencies import build_ton_nft_verifier
from app.assets.ton_nft.models import VerificationStatus
from app.db.models import (
    AssetType,
    AssetVerificationStatus,
    Listing,
    ListingStatus,
    NFTAsset,
    Wallet,
)
from app.db.session import async_session_factory


def suffix(address: str | None) -> str | None:
    if not address:
        return None
    try:
        normalized = normalize_address(address)
    except (TypeError, ValueError):
        normalized = address
    return normalized[-8:]


async def run(wallet_id: UUID, limit: int, offset: int) -> dict[str, object]:
    verifier = build_ton_nft_verifier()
    try:
        async with async_session_factory() as session:
            wallet = await session.scalar(
                select(Wallet).where(
                    Wallet.id == wallet_id,
                    Wallet.is_verified.is_(True),
                )
            )
            if wallet is None:
                raise SystemExit(
                    "Selected verified wallet was not found; no addresses printed."
                )
            if wallet.network != verifier.network:
                raise SystemExit(
                    f"Network mismatch: wallet={wallet.network}, provider={verifier.network}; "
                    "no inventory scan performed."
                )

            started_at = datetime.now(UTC).isoformat()
            page = await verifier.provider.get_items_by_owner(
                wallet.address, limit=limit, offset=offset
            )
            candidates: list[dict[str, object]] = []
            for candidate in page.items:
                result = await verifier.verify(candidate.address, wallet.address)
                rows = (
                    await session.scalars(
                        select(NFTAsset).where(
                            NFTAsset.asset_type == AssetType.TON_NFT,
                            NFTAsset.network == wallet.network,
                            or_(
                                NFTAsset.external_id == candidate.address,
                                NFTAsset.item_address == candidate.address,
                            ),
                        )
                    )
                ).all()
                db_rows: list[dict[str, object]] = []
                for asset in rows:
                    listings = (
                        await session.scalars(
                            select(Listing).where(
                                Listing.asset_id == asset.id,
                                Listing.status.in_(
                                    [ListingStatus.ACTIVE, ListingStatus.RESERVED]
                                ),
                            )
                        )
                    ).all()
                    db_rows.append(
                        {
                            "asset_id": str(asset.id),
                            "owner_matches_selected_user": asset.owner_id == wallet.user_id,
                            "verification_status": (
                                asset.verification_status.value
                                if isinstance(asset.verification_status, AssetVerificationStatus)
                                else str(asset.verification_status)
                            ),
                            "open_listing_statuses": sorted(
                                listing.status.value
                                if isinstance(listing.status, ListingStatus)
                                else str(listing.status)
                                for listing in listings
                            ),
                        }
                    )
                candidates.append(
                    {
                        "item_suffix": suffix(candidate.address),
                        "page_owner_suffix": suffix(candidate.owner_address),
                        "provider_index": candidate.index,
                        "verifier_status": (
                            result.status.value
                            if isinstance(result.status, VerificationStatus)
                            else str(result.status)
                        ),
                        "verifier_owner_suffix": suffix(result.owner_address),
                        "verifier_owner_matches_selected_wallet": (
                            normalize_address(result.owner_address)
                            == normalize_address(wallet.address)
                            if result.owner_address
                            else None
                        ),
                        "verifier_expected_owner_matches_selected_wallet": (
                            normalize_address(result.expected_owner_address)
                            == normalize_address(wallet.address)
                            if result.expected_owner_address
                            else None
                        ),
                        "db_rows": db_rows,
                        "upsert": "not_executed_read_only",
                    }
                )

            return {
                "captured_at_utc": started_at,
                "finished_at_utc": datetime.now(UTC).isoformat(),
                "mode": "read_only_provider_and_database; no API request; no writes",
                "wallet_id": str(wallet.id),
                "network": wallet.network,
                "provider_network": verifier.network,
                "wallet_address": "[REDACTED]",
                "provider_page": {
                    "offset": offset,
                    "limit": limit,
                    "candidate_count": len(page.items),
                    "next_offset": page.next_offset,
                    "has_more": page.has_more,
                },
                "verified_candidate_count": sum(
                    1
                    for item in candidates
                    if item["verifier_status"] == VerificationStatus.VERIFIED.value
                ),
                "candidates": candidates,
                "notes": [
                    "This is an indexed-provider observation, not a blockchain snapshot.",
                    "Provider read and DB reads are not transactionally atomic.",
                    "No upsert was attempted; open-listing status is shown as a potential guard only.",
                    (
                        "Capture the UI/API response separately with timestamp and query "
                        "params; the GET route may persist verified rows."
                    ),
                ],
            }
    finally:
        await verifier.provider.aclose()


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--wallet-id", required=True, type=UUID, help="Verified wallet UUID")
    parser.add_argument("--limit", type=int, default=24)
    parser.add_argument("--offset", type=int, default=0)
    args = parser.parse_args()
    if not 1 <= args.limit <= 100 or args.offset < 0:
        parser.error("--limit must be 1..100 and --offset must be >= 0")
    print(json.dumps(asyncio.run(run(args.wallet_id, args.limit, args.offset)), indent=2))


if __name__ == "__main__":
    main()
