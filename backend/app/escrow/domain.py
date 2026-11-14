"""Escrow domain rules independent of the database and TON contract ABI.

Only normalized, independently verified chain evidence may advance on-chain deal
states. Client requests are intents, never on-chain state transitions.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class EscrowListingStatus(StrEnum):
    INTENT_ONLY = "intent_only"
    ACTIVE = "active"
    RESERVED = "reserved"
    CANCELLED = "cancelled"
    MANUAL_REVIEW = "manual_review"


class EscrowDealStatus(StrEnum):
    INTENT_CREATED = "intent_created"
    AWAITING_NFT = "awaiting_nft"
    AWAITING_BUYER_FUNDS = "awaiting_buyer_funds"
    FUNDED_REVIEW = "funded_review"
    NFT_RELEASE_PENDING = "nft_release_pending"
    DELIVERED_DISPUTE_WINDOW = "delivered_dispute_window"
    DISPUTED = "disputed"
    NFT_RETURN_PENDING = "nft_return_pending"
    SELLER_PAYOUT_PENDING = "seller_payout_pending"
    BUYER_REFUND_PENDING = "buyer_refund_pending"
    SETTLED = "settled"
    REFUNDED = "refunded"
    EXPIRED = "expired"
    MANUAL_REVIEW = "manual_review"


class EscrowChainEventType(StrEnum):
    CONTRACT_ACTIVATED = "contract_activated"
    NFT_DEPOSITED = "nft_deposited"
    BUYER_PAYMENT_CONFIRMED = "buyer_payment_confirmed"
    NFT_RELEASE_STARTED = "nft_release_started"
    NFT_TRANSFER_CONFIRMED = "nft_transfer_confirmed"
    DISPUTE_CONFIRMED = "dispute_confirmed"
    NFT_RETURN_TO_ESCROW_CONFIRMED = "nft_return_to_escrow_confirmed"
    NFT_RETURN_STARTED = "nft_return_started"
    SELLER_PAYOUT_STARTED = "seller_payout_started"
    SELLER_PAYOUT_CONFIRMED = "seller_payout_confirmed"
    BUYER_REFUND_STARTED = "buyer_refund_started"
    BUYER_REFUND_CONFIRMED = "buyer_refund_confirmed"
    NFT_RETURN_CONFIRMED = "nft_return_confirmed"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"


class EscrowDomainError(ValueError):
    """A proposed escrow operation violates a domain invariant."""


TERMINAL_DEAL_STATES = frozenset(
    {EscrowDealStatus.SETTLED, EscrowDealStatus.REFUNDED, EscrowDealStatus.EXPIRED}
)

# This is intentionally a narrow event state machine. The API never calls this
# function directly; only the observer may apply a provider-verified chain event.
_CHAIN_TRANSITIONS: dict[tuple[EscrowDealStatus, EscrowChainEventType], EscrowDealStatus] = {
    (EscrowDealStatus.INTENT_CREATED, EscrowChainEventType.CONTRACT_ACTIVATED):
        EscrowDealStatus.AWAITING_NFT,
    (EscrowDealStatus.AWAITING_NFT, EscrowChainEventType.NFT_DEPOSITED):
        EscrowDealStatus.AWAITING_BUYER_FUNDS,
    (EscrowDealStatus.AWAITING_BUYER_FUNDS, EscrowChainEventType.BUYER_PAYMENT_CONFIRMED):
        EscrowDealStatus.FUNDED_REVIEW,
    (EscrowDealStatus.FUNDED_REVIEW, EscrowChainEventType.NFT_RELEASE_STARTED):
        EscrowDealStatus.NFT_RELEASE_PENDING,
    (EscrowDealStatus.NFT_RELEASE_PENDING, EscrowChainEventType.NFT_TRANSFER_CONFIRMED):
        EscrowDealStatus.DELIVERED_DISPUTE_WINDOW,
    (EscrowDealStatus.DELIVERED_DISPUTE_WINDOW, EscrowChainEventType.DISPUTE_CONFIRMED):
        EscrowDealStatus.DISPUTED,
    (EscrowDealStatus.DISPUTED, EscrowChainEventType.NFT_RETURN_STARTED):
        EscrowDealStatus.NFT_RETURN_PENDING,
    (EscrowDealStatus.DISPUTED, EscrowChainEventType.NFT_RETURN_TO_ESCROW_CONFIRMED):
        EscrowDealStatus.NFT_RETURN_PENDING,
    (EscrowDealStatus.DELIVERED_DISPUTE_WINDOW, EscrowChainEventType.SELLER_PAYOUT_STARTED):
        EscrowDealStatus.SELLER_PAYOUT_PENDING,
    (EscrowDealStatus.SELLER_PAYOUT_PENDING, EscrowChainEventType.SELLER_PAYOUT_CONFIRMED):
        EscrowDealStatus.SETTLED,
    (EscrowDealStatus.FUNDED_REVIEW, EscrowChainEventType.NFT_RETURN_STARTED):
        EscrowDealStatus.NFT_RETURN_PENDING,
    (EscrowDealStatus.NFT_RETURN_PENDING, EscrowChainEventType.NFT_RETURN_STARTED):
        EscrowDealStatus.NFT_RETURN_PENDING,
    (EscrowDealStatus.NFT_RETURN_PENDING, EscrowChainEventType.NFT_RETURN_CONFIRMED):
        EscrowDealStatus.BUYER_REFUND_PENDING,
    (EscrowDealStatus.BUYER_REFUND_PENDING, EscrowChainEventType.BUYER_REFUND_STARTED):
        EscrowDealStatus.BUYER_REFUND_PENDING,
    (EscrowDealStatus.BUYER_REFUND_PENDING, EscrowChainEventType.BUYER_REFUND_CONFIRMED):
        EscrowDealStatus.REFUNDED,
    (EscrowDealStatus.DISPUTED, EscrowChainEventType.NFT_TRANSFER_CONFIRMED):
        EscrowDealStatus.DELIVERED_DISPUTE_WINDOW,
    (EscrowDealStatus.DISPUTED, EscrowChainEventType.SELLER_PAYOUT_STARTED):
        EscrowDealStatus.SELLER_PAYOUT_PENDING,
}


def transition_for_verified_event(
    current: EscrowDealStatus | str,
    event_type: EscrowChainEventType | str,
) -> EscrowDealStatus:
    """Return the only allowed next state for a verified chain event.

    A caller must verify provider evidence, exact deal facts, network and finality
    before calling this function. Unknown or repeated events fail closed.
    """
    try:
        source = EscrowDealStatus(current)
        event = EscrowChainEventType(event_type)
    except ValueError as exc:
        raise EscrowDomainError("Unknown escrow state or chain event") from exc

    if event is EscrowChainEventType.MANUAL_REVIEW_REQUIRED:
        if source in TERMINAL_DEAL_STATES:
            raise EscrowDomainError("A terminal deal cannot be silently reopened")
        return EscrowDealStatus.MANUAL_REVIEW

    target = _CHAIN_TRANSITIONS.get((source, event))
    if target is None:
        raise EscrowDomainError(f"Event {event.value} is not allowed from {source.value}")
    return target


@dataclass(frozen=True, slots=True)
class DealEvidenceSnapshot:
    """Immutable deal facts used to compare observed chain evidence."""

    network: str
    contract_address: str | None
    item_address: str
    seller_address: str
    buyer_address: str
    principal_nanotons: int


@dataclass(frozen=True, slots=True)
class NormalizedEventEvidence:
    """Provider-normalized event; hashes and addresses are not trusted by themselves."""

    network: str
    contract_address: str
    event_type: EscrowChainEventType
    source_address: str | None
    destination_address: str | None
    item_address: str | None
    amount_nanotons: int | None
    masterchain_seqno: int
    finalized: bool


def validate_event_against_deal(
    event: NormalizedEventEvidence,
    deal: DealEvidenceSnapshot,
) -> None:
    """Raise unless the event is final and matches the exact immutable deal snapshot."""
    if event.network != "testnet" or deal.network != "testnet":
        raise EscrowDomainError("Escrow backend only accepts TON testnet evidence")
    if not event.finalized or event.masterchain_seqno <= 0:
        raise EscrowDomainError("Chain evidence is not finalized")
    if not deal.contract_address or event.contract_address != deal.contract_address:
        raise EscrowDomainError("Event does not belong to the configured deal contract")

    if event.event_type in {
        EscrowChainEventType.NFT_DEPOSITED,
        EscrowChainEventType.NFT_TRANSFER_CONFIRMED,
        EscrowChainEventType.NFT_RETURN_TO_ESCROW_CONFIRMED,
        EscrowChainEventType.NFT_RETURN_STARTED,
        EscrowChainEventType.NFT_RETURN_CONFIRMED,
    }:
        if event.item_address != deal.item_address:
            raise EscrowDomainError("NFT item does not match the deal snapshot")

    if event.event_type is EscrowChainEventType.NFT_DEPOSITED and (
        event.source_address != deal.seller_address
        or event.destination_address != deal.contract_address
    ):
        raise EscrowDomainError("NFT deposit sender or escrow recipient does not match the deal")

    if event.event_type is EscrowChainEventType.BUYER_PAYMENT_CONFIRMED and (
        event.source_address != deal.buyer_address
        or event.destination_address != deal.contract_address
        or event.amount_nanotons != deal.principal_nanotons
    ):
        raise EscrowDomainError(
            "Payment sender, escrow recipient or exact principal does not match the deal"
        )

    if event.event_type is EscrowChainEventType.NFT_TRANSFER_CONFIRMED and (
        event.source_address != deal.contract_address
        or event.destination_address != deal.buyer_address
    ):
        raise EscrowDomainError("NFT source or destination does not match the deal")

    if event.event_type is EscrowChainEventType.NFT_RETURN_TO_ESCROW_CONFIRMED and (
        event.source_address != deal.buyer_address
        or event.destination_address != deal.contract_address
    ):
        raise EscrowDomainError("NFT return must be from buyer to the configured escrow")

    if event.event_type in {
        EscrowChainEventType.NFT_RETURN_STARTED,
        EscrowChainEventType.NFT_RETURN_CONFIRMED,
    } and (
        event.source_address != deal.contract_address
        or event.destination_address != deal.seller_address
    ):
        raise EscrowDomainError("NFT return to seller must use the fixed escrow and seller")

    if event.event_type is EscrowChainEventType.SELLER_PAYOUT_CONFIRMED and (
        event.source_address != deal.contract_address
        or event.destination_address != deal.seller_address
        or event.amount_nanotons != deal.principal_nanotons
    ):
        raise EscrowDomainError(
            "Seller payout does not match the contract, fixed recipient and principal"
        )

    if event.event_type is EscrowChainEventType.BUYER_REFUND_CONFIRMED and (
        event.source_address != deal.contract_address
        or event.destination_address != deal.buyer_address
        or event.amount_nanotons != deal.principal_nanotons
    ):
        raise EscrowDomainError(
            "Buyer refund does not match the contract, fixed recipient and principal"
        )
