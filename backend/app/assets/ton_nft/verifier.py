"""TEP-62 NFT item and current-owner verifier."""

from __future__ import annotations

from app.assets.ton_nft.address import AddressError, normalize_address
from app.assets.ton_nft.errors import InvalidProviderData, ProviderUnavailable, UnsupportedAsset
from app.assets.ton_nft.models import NFTItemSnapshot, VerificationResult, VerificationStatus
from app.assets.ton_nft.provider import NFTDataProvider

class TONNFTVerifier:
    """Verify an NFT item against an expected seller wallet, without writes."""

    def __init__(self, provider: NFTDataProvider) -> None:
        self.provider = provider

    async def verify(self, item_address: str, expected_owner_address: str) -> VerificationResult:
        try:
            item = normalize_address(item_address)
            expected_owner = normalize_address(expected_owner_address)
        except AddressError as exc:
            return VerificationResult(VerificationStatus.INVALID_DATA, str(item_address), reason=str(exc))
        try:
            snapshot = await self.provider.get_item(item)
            if snapshot is None:
                return VerificationResult(VerificationStatus.NOT_FOUND, item, expected_owner_address=expected_owner,
                                          reason="NFT item was not found by the configured provider")
            if snapshot.address != item:
                raise InvalidProviderData("Provider returned a mismatched item address")
            if not snapshot.initialized:
                return self._result(VerificationStatus.INVALID_DATA, item, snapshot, expected_owner,
                                    "NFT item contract is not initialized")
            if snapshot.collection_address is not None:
                resolved = await self.provider.get_item_address_by_index(snapshot.collection_address, snapshot.index)
                if resolved is None or normalize_address(resolved) != item:
                    return self._result(VerificationStatus.INVALID_DATA, item, snapshot, expected_owner,
                                        "Collection index does not resolve to this NFT item")
            if snapshot.owner_address != expected_owner:
                return self._result(VerificationStatus.OWNER_MISMATCH, item, snapshot, expected_owner,
                                    "Current NFT owner does not match the expected seller")
            return self._result(VerificationStatus.VERIFIED, item, snapshot, expected_owner)
        except UnsupportedAsset as exc:
            return VerificationResult(VerificationStatus.UNSUPPORTED, item, expected_owner_address=expected_owner,
                                      reason=str(exc))
        except ProviderUnavailable as exc:
            return VerificationResult(VerificationStatus.PROVIDER_UNAVAILABLE, item,
                                      expected_owner_address=expected_owner, reason=str(exc))
        except (InvalidProviderData, AddressError, TypeError, ValueError) as exc:
            return VerificationResult(VerificationStatus.INVALID_DATA, item,
                                      expected_owner_address=expected_owner, reason=str(exc))

    @staticmethod
    def _result(status: VerificationStatus, item_address: str, snapshot: NFTItemSnapshot,
                expected_owner: str, reason: str | None = None) -> VerificationResult:
        return VerificationResult(status, item_address, snapshot.owner_address, snapshot.collection_address,
                                  snapshot.index, expected_owner, snapshot.metadata, reason)
