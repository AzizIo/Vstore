"""Escrow domain rules independent of the database and TON contract ABI.

Only accepted contract state, reconciled against finalized chain evidence, may
advance canonical deal states. Off-chain provider observations are never state
transitions. Client requests are intents, not proof of chain activity.
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
    # Layer A: off-chain evidence observations. These never move a Deal.
    NFT_DEPOSIT_EVIDENCE_OBSERVED = "nft_deposit_evidence_observed"
    BUYER_PAYMENT_EVIDENCE_OBSERVED = "buyer_payment_evidence_observed"
    NFT_DELIVERY_EVIDENCE_OBSERVED = "nft_delivery_evidence_observed"
    NFT_RETURN_EVIDENCE_OBSERVED = "nft_return_evidence_observed"
    SELLER_PAYOUT_EVIDENCE_OBSERVED = "seller_payout_evidence_observed"
    BUYER_REFUND_EVIDENCE_OBSERVED = "buyer_refund_evidence_observed"

    # Layer B: contract-accepted facts; observer still verifies finality/getter state.
    CONTRACT_ACTIVATED = "contract_activated"
    NFT_DEPOSIT_ACCEPTED = "nft_deposit_accepted"
    BUYER_PAYMENT_ACCEPTED = "buyer_payment_accepted"
    BUYER_ACCEPTANCE_RECORDED = "buyer_acceptance_recorded"
    ORACLE_DELIVERY_ATTESTATION_ACCEPTED = "oracle_delivery_attestation_accepted"
    DISPUTE_OPENED_ONCHAIN = "dispute_opened_onchain"
    DISPUTE_RESOLUTION_ACCEPTED = "dispute_resolution_accepted"
    ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED = "oracle_nft_return_attestation_accepted"
    SELLER_PAYOUT_INITIATED = "seller_payout_initiated"
    SELLER_PAYOUT_RECONCILED = "seller_payout_reconciled"
    BUYER_REFUND_INITIATED = "buyer_refund_initiated"
    BUYER_REFUND_RECONCILED = "buyer_refund_reconciled"
    DEAL_EXPIRED = "deal_expired"
    MANUAL_REVIEW_REQUIRED = "manual_review_required"
    DEAL_TIMEOUT_ACCEPTED = "deal_timeout_accepted"
    RECOVERY_NFT_RETURN_STARTED = "recovery_nft_return_started"

    # Legacy event names are parseable for forensic/history purposes only.
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


class EscrowDomainError(ValueError):
    """A proposed escrow operation violates a domain invariant."""


RAW_EVIDENCE_EVENTS = frozenset({
    EscrowChainEventType.NFT_DEPOSIT_EVIDENCE_OBSERVED,
    EscrowChainEventType.BUYER_PAYMENT_EVIDENCE_OBSERVED,
    EscrowChainEventType.NFT_DELIVERY_EVIDENCE_OBSERVED,
    EscrowChainEventType.NFT_RETURN_EVIDENCE_OBSERVED,
    EscrowChainEventType.SELLER_PAYOUT_EVIDENCE_OBSERVED,
    EscrowChainEventType.BUYER_REFUND_EVIDENCE_OBSERVED,
    EscrowChainEventType.NFT_DEPOSITED,
    EscrowChainEventType.BUYER_PAYMENT_CONFIRMED,
    EscrowChainEventType.NFT_TRANSFER_CONFIRMED,
    EscrowChainEventType.NFT_RETURN_TO_ESCROW_CONFIRMED,
    EscrowChainEventType.NFT_RETURN_CONFIRMED,
    EscrowChainEventType.SELLER_PAYOUT_CONFIRMED,
    EscrowChainEventType.BUYER_REFUND_CONFIRMED,
})

TERMINAL_DEAL_STATES = frozenset({
    EscrowDealStatus.SETTLED, EscrowDealStatus.REFUNDED, EscrowDealStatus.EXPIRED,
})

_CHAIN_TRANSITIONS: dict[tuple[EscrowDealStatus, EscrowChainEventType], EscrowDealStatus] = {
    (
        EscrowDealStatus.INTENT_CREATED,
        EscrowChainEventType.CONTRACT_ACTIVATED,
    ): EscrowDealStatus.AWAITING_NFT,
    (
        EscrowDealStatus.AWAITING_NFT,
        EscrowChainEventType.NFT_DEPOSIT_ACCEPTED,
    ): EscrowDealStatus.AWAITING_BUYER_FUNDS,
    (
        EscrowDealStatus.AWAITING_BUYER_FUNDS,
        EscrowChainEventType.BUYER_PAYMENT_ACCEPTED,
    ): EscrowDealStatus.FUNDED_REVIEW,
    (
        EscrowDealStatus.FUNDED_REVIEW,
        EscrowChainEventType.BUYER_ACCEPTANCE_RECORDED,
    ): EscrowDealStatus.NFT_RELEASE_PENDING,
    (
        EscrowDealStatus.NFT_RELEASE_PENDING,
        EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED,
    ): EscrowDealStatus.DELIVERED_DISPUTE_WINDOW,
    (
        EscrowDealStatus.DELIVERED_DISPUTE_WINDOW,
        EscrowChainEventType.DISPUTE_OPENED_ONCHAIN,
    ): EscrowDealStatus.DISPUTED,
    (
        EscrowDealStatus.DISPUTED,
        EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED,
    ): EscrowDealStatus.NFT_RETURN_PENDING,
    (
        EscrowDealStatus.DELIVERED_DISPUTE_WINDOW,
        EscrowChainEventType.SELLER_PAYOUT_INITIATED,
    ): EscrowDealStatus.SELLER_PAYOUT_PENDING,
    (
        EscrowDealStatus.SELLER_PAYOUT_PENDING,
        EscrowChainEventType.SELLER_PAYOUT_RECONCILED,
    ): EscrowDealStatus.SETTLED,
    (
        EscrowDealStatus.NFT_RETURN_PENDING,
        EscrowChainEventType.BUYER_REFUND_INITIATED,
    ): EscrowDealStatus.BUYER_REFUND_PENDING,
    (
        EscrowDealStatus.BUYER_REFUND_PENDING,
        EscrowChainEventType.BUYER_REFUND_RECONCILED,
    ): EscrowDealStatus.REFUNDED,
    (
        EscrowDealStatus.INTENT_CREATED,
        EscrowChainEventType.DEAL_EXPIRED,
    ): EscrowDealStatus.EXPIRED,
    (
        EscrowDealStatus.AWAITING_NFT,
        EscrowChainEventType.DEAL_EXPIRED,
    ): EscrowDealStatus.EXPIRED,
    (
        EscrowDealStatus.AWAITING_BUYER_FUNDS,
        EscrowChainEventType.DEAL_EXPIRED,
    ): EscrowDealStatus.EXPIRED,
}


def is_raw_evidence_event(event_type: EscrowChainEventType | str) -> bool:
    try:
        return EscrowChainEventType(event_type) in RAW_EVIDENCE_EVENTS
    except ValueError:
        return False


def transition_for_verified_event(
    current: EscrowDealStatus | str,
    event_type: EscrowChainEventType | str,
    observed_contract_state: str | None = None,
) -> EscrowDealStatus:
    try:
        source, event = EscrowDealStatus(current), EscrowChainEventType(event_type)
    except ValueError as exc:
        raise EscrowDomainError("Unknown escrow state or chain event") from exc
    if event in RAW_EVIDENCE_EVENTS:
        raise EscrowDomainError("Raw off-chain evidence cannot advance a canonical deal state")
    if event is EscrowChainEventType.MANUAL_REVIEW_REQUIRED:
        if source in TERMINAL_DEAL_STATES:
            raise EscrowDomainError("A terminal deal cannot be silently reopened")
        return EscrowDealStatus.MANUAL_REVIEW

    # Several DealEscrow v1 messages have more than one legitimate result. The
    # proof-verified contract storage state selects the transition; event labels
    # alone are insufficient (e.g. timeout can return, expire or initiate payout).
    dynamic_targets = {
        EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED: {
            "delivered_dispute_window": EscrowDealStatus.DELIVERED_DISPUTE_WINDOW,
            "seller_payout_pending": EscrowDealStatus.SELLER_PAYOUT_PENDING,
        },
        EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED: {
            "buyer_refund_pending": EscrowDealStatus.BUYER_REFUND_PENDING,
            "expired": EscrowDealStatus.EXPIRED,
        },
        EscrowChainEventType.DISPUTE_RESOLUTION_ACCEPTED: {
            "nft_release_pending": EscrowDealStatus.NFT_RELEASE_PENDING,
            "nft_return_pending": EscrowDealStatus.NFT_RETURN_PENDING,
        },
        EscrowChainEventType.DEAL_TIMEOUT_ACCEPTED: {
            "nft_return_pending": EscrowDealStatus.NFT_RETURN_PENDING,
            "seller_payout_pending": EscrowDealStatus.SELLER_PAYOUT_PENDING,
            "expired": EscrowDealStatus.EXPIRED,
            "manual_review": EscrowDealStatus.MANUAL_REVIEW,
        },
        EscrowChainEventType.RECOVERY_NFT_RETURN_STARTED: {
            "nft_return_pending": EscrowDealStatus.NFT_RETURN_PENDING,
        },
    }
    if event in dynamic_targets:
        if not observed_contract_state or observed_contract_state not in dynamic_targets[event]:
            raise EscrowDomainError(
                f"Event {event.value} has no allowed proof-verified contract-state target"
            )
        target = dynamic_targets[event][observed_contract_state]
        allowed_sources = {
            EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED: {
                EscrowDealStatus.NFT_RELEASE_PENDING,
            },
            EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED: {
                EscrowDealStatus.NFT_RETURN_PENDING,
            },
            EscrowChainEventType.DISPUTE_RESOLUTION_ACCEPTED: {
                EscrowDealStatus.DISPUTED,
            },
            EscrowChainEventType.DEAL_TIMEOUT_ACCEPTED: {
                EscrowDealStatus.INTENT_CREATED,
                EscrowDealStatus.AWAITING_NFT,
                EscrowDealStatus.AWAITING_BUYER_FUNDS,
                EscrowDealStatus.FUNDED_REVIEW,
                EscrowDealStatus.NFT_RELEASE_PENDING,
                EscrowDealStatus.DELIVERED_DISPUTE_WINDOW,
                EscrowDealStatus.DISPUTED,
                EscrowDealStatus.NFT_RETURN_PENDING,
                EscrowDealStatus.BUYER_REFUND_PENDING,
            },
            EscrowChainEventType.RECOVERY_NFT_RETURN_STARTED: {
                EscrowDealStatus.MANUAL_REVIEW,
            },
        }[event]
        if source not in allowed_sources:
            raise EscrowDomainError(
                f"Event {event.value} is not allowed from {source.value}"
            )
        return target

    target = _CHAIN_TRANSITIONS.get((source, event))
    if target is None:
        raise EscrowDomainError(f"Event {event.value} is not allowed from {source.value}")
    return target


@dataclass(frozen=True, slots=True)
class DealEvidenceSnapshot:
    network: str
    contract_address: str | None
    collection_address: str
    item_address: str
    seller_address: str
    buyer_address: str
    principal_nanotons: int
    execution_reserve_nanotons: int | None = None


@dataclass(frozen=True, slots=True)
class NormalizedEventEvidence:
    network: str
    contract_address: str
    event_type: EscrowChainEventType
    source_address: str | None
    destination_address: str | None
    item_address: str | None
    collection_address: str | None
    amount_nanotons: int | None
    masterchain_seqno: int
    finalized: bool
    logical_time: int | None = None
    message_hash: str | None = None
    trace_id: str | None = None
    phase: str | None = None
    attempt_id: str | None = None
    query_id: str | None = None
    deal_salt: str | None = None
    observed_contract_state: str | None = None
    attestation_accepted: bool = False
    contract_state_reconciled: bool = False


def validate_event_against_deal(event: NormalizedEventEvidence, deal: DealEvidenceSnapshot) -> None:
    if event.network != "testnet" or deal.network != "testnet":
        raise EscrowDomainError("Escrow backend only accepts TON testnet evidence")
    if not event.finalized or event.masterchain_seqno <= 0:
        raise EscrowDomainError("Chain evidence is not finalized")
    if event.event_type in RAW_EVIDENCE_EVENTS:
        raise EscrowDomainError("Raw observations are evidence only, not accepted contract state")
    if not deal.contract_address or event.contract_address != deal.contract_address:
        raise EscrowDomainError("Event does not belong to the configured deal contract")

    if event.event_type is EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED:
        if (
            not event.attestation_accepted
            or not event.contract_state_reconciled
            or event.observed_contract_state not in {
                EscrowDealStatus.DELIVERED_DISPUTE_WINDOW.value,
                EscrowDealStatus.SELLER_PAYOUT_PENDING.value,
            }
            or not event.message_hash or not event.trace_id or not event.attempt_id
        ):
            raise EscrowDomainError(
                "Delivery attestation lacks finalized contract-state reconciliation"
            )

    nft_related = {
        EscrowChainEventType.NFT_DEPOSIT_ACCEPTED,
        EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED,
        EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED,
    }
    if event.event_type in nft_related and (
        not deal.collection_address
        or event.item_address != deal.item_address
        or event.collection_address != deal.collection_address
    ):
        raise EscrowDomainError("NFT collection or item does not match the deal snapshot")

    if event.event_type is EscrowChainEventType.NFT_DEPOSIT_ACCEPTED and (
        event.source_address != deal.seller_address
        or event.destination_address != deal.contract_address
    ):
        raise EscrowDomainError(
            "NFT deposit sender or escrow recipient does not match the deal"
        )
    if event.event_type is EscrowChainEventType.BUYER_PAYMENT_ACCEPTED and (
        event.source_address != deal.buyer_address
        or event.destination_address != deal.contract_address
        or deal.execution_reserve_nanotons is None
        or event.amount_nanotons
            != deal.principal_nanotons + deal.execution_reserve_nanotons
    ):
        raise EscrowDomainError(
            "Payment sender, escrow recipient or exact principal does not match the deal"
        )
    if event.event_type is EscrowChainEventType.BUYER_ACCEPTANCE_RECORDED and (
        event.source_address != deal.buyer_address
        or event.destination_address != deal.contract_address
    ):
        raise EscrowDomainError(
            "Buyer acceptance must originate from the bound buyer wallet"
        )
    if event.event_type is EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED and (
        event.source_address != deal.contract_address
        or event.destination_address != deal.buyer_address
    ):
        raise EscrowDomainError("NFT source or destination does not match the deal")
    if event.event_type is EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED and (
        not event.attestation_accepted
        or not event.contract_state_reconciled
        or event.observed_contract_state not in {
            EscrowDealStatus.BUYER_REFUND_PENDING.value,
            EscrowDealStatus.EXPIRED.value,
        }
        or event.source_address != deal.contract_address
        or event.destination_address != deal.seller_address
        or event.amount_nanotons != 0
    ):
        raise EscrowDomainError(
            "Oracle return attestation must prove the escrow-to-seller route and state"
        )
    if event.event_type is EscrowChainEventType.SELLER_PAYOUT_RECONCILED and (
        event.source_address != deal.contract_address
        or event.destination_address != deal.seller_address
        or event.amount_nanotons != deal.principal_nanotons
    ):
        raise EscrowDomainError(
            "Seller payout does not match contract, fixed recipient and principal"
        )
    if event.event_type is EscrowChainEventType.BUYER_REFUND_RECONCILED and (
        event.source_address != deal.contract_address
        or event.destination_address != deal.buyer_address
        or event.amount_nanotons != deal.principal_nanotons
    ):
        raise EscrowDomainError(
            "Buyer refund does not match contract, fixed recipient and principal"
        )
