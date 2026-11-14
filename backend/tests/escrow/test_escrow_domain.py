from __future__ import annotations

import pytest

from app.escrow.domain import (
    DealEvidenceSnapshot,
    EscrowChainEventType,
    EscrowDealStatus,
    EscrowDomainError,
    NormalizedEventEvidence,
    transition_for_verified_event,
    validate_event_against_deal,
)


@pytest.fixture
def deal() -> DealEvidenceSnapshot:
    return DealEvidenceSnapshot(
        network="testnet",
        contract_address="0:" + "a" * 64,
        item_address="0:" + "b" * 64,
        seller_address="0:" + "c" * 64,
        buyer_address="0:" + "d" * 64,
        principal_nanotons=2_500_000_000,
    )


def evidence(
    *, event_type: EscrowChainEventType = EscrowChainEventType.NFT_DEPOSITED, **overrides: object
) -> NormalizedEventEvidence:
    values: dict[str, object] = {
        "network": "testnet",
        "contract_address": "0:" + "a" * 64,
        "event_type": event_type,
        "source_address": "0:" + "c" * 64,
        "destination_address": "0:" + "a" * 64,
        "item_address": "0:" + "b" * 64,
        "amount_nanotons": None,
        "masterchain_seqno": 123,
        "finalized": True,
    }
    values.update(overrides)
    return NormalizedEventEvidence(**values)  # type: ignore[arg-type]


def test_state_machine_accepts_only_the_defined_onchain_path() -> None:
    state = transition_for_verified_event(
        EscrowDealStatus.INTENT_CREATED, EscrowChainEventType.CONTRACT_ACTIVATED
    )
    assert state is EscrowDealStatus.AWAITING_NFT
    state = transition_for_verified_event(state, EscrowChainEventType.NFT_DEPOSITED)
    assert state is EscrowDealStatus.AWAITING_BUYER_FUNDS
    state = transition_for_verified_event(state, EscrowChainEventType.BUYER_PAYMENT_CONFIRMED)
    assert state is EscrowDealStatus.FUNDED_REVIEW
    state = transition_for_verified_event(state, EscrowChainEventType.NFT_RELEASE_STARTED)
    assert state is EscrowDealStatus.NFT_RELEASE_PENDING
    state = transition_for_verified_event(state, EscrowChainEventType.NFT_TRANSFER_CONFIRMED)
    assert state is EscrowDealStatus.DELIVERED_DISPUTE_WINDOW
    state = transition_for_verified_event(state, EscrowChainEventType.SELLER_PAYOUT_STARTED)
    assert state is EscrowDealStatus.SELLER_PAYOUT_PENDING
    state = transition_for_verified_event(state, EscrowChainEventType.SELLER_PAYOUT_CONFIRMED)
    assert state is EscrowDealStatus.SETTLED


def test_replay_or_out_of_order_event_cannot_advance_state() -> None:
    with pytest.raises(EscrowDomainError):
        transition_for_verified_event(
            EscrowDealStatus.FUNDED_REVIEW, EscrowChainEventType.NFT_DEPOSITED
        )
    with pytest.raises(EscrowDomainError):
        transition_for_verified_event(
            EscrowDealStatus.SETTLED, EscrowChainEventType.SELLER_PAYOUT_CONFIRMED
        )


def test_exact_nft_deposit_evidence_is_accepted(deal: DealEvidenceSnapshot) -> None:
    validate_event_against_deal(evidence(), deal)


@pytest.mark.parametrize(
    "overrides",
    [
        {"item_address": "0:" + "e" * 64},
        {"source_address": "0:" + "f" * 64},
        {"contract_address": "0:" + "e" * 64},
        {"network": "mainnet"},
        {"finalized": False},
        {"masterchain_seqno": 0},
    ],
)
def test_bad_or_nonfinal_nft_deposit_is_rejected(
    deal: DealEvidenceSnapshot, overrides: dict[str, object]
) -> None:
    with pytest.raises(EscrowDomainError):
        validate_event_against_deal(evidence(**overrides), deal)


def test_payment_requires_exact_buyer_and_principal(deal: DealEvidenceSnapshot) -> None:
    correct = evidence(
        event_type=EscrowChainEventType.BUYER_PAYMENT_CONFIRMED,
        source_address=deal.buyer_address,
        item_address=None,
        amount_nanotons=deal.principal_nanotons,
    )
    validate_event_against_deal(correct, deal)
    with pytest.raises(EscrowDomainError):
        validate_event_against_deal(
            evidence(
                event_type=EscrowChainEventType.BUYER_PAYMENT_CONFIRMED,
                source_address=deal.buyer_address,
                amount_nanotons=deal.principal_nanotons - 1,
                item_address=None,
            ),
            deal,
        )
    with pytest.raises(EscrowDomainError):
        validate_event_against_deal(
            evidence(
                event_type=EscrowChainEventType.BUYER_PAYMENT_CONFIRMED,
                source_address=deal.seller_address,
                amount_nanotons=deal.principal_nanotons,
                item_address=None,
            ),
            deal,
        )


def test_client_cannot_invent_a_chain_transition() -> None:
    with pytest.raises(EscrowDomainError):
        transition_for_verified_event(EscrowDealStatus.INTENT_CREATED, "client_paid")


def test_missing_contract_binding_fails_closed(deal: DealEvidenceSnapshot) -> None:
    unbound = DealEvidenceSnapshot(
        network=deal.network,
        contract_address=None,
        item_address=deal.item_address,
        seller_address=deal.seller_address,
        buyer_address=deal.buyer_address,
        principal_nanotons=deal.principal_nanotons,
    )
    with pytest.raises(EscrowDomainError):
        validate_event_against_deal(evidence(), unbound)



def test_refund_requires_finalized_nft_return_then_exact_refund(
    deal: DealEvidenceSnapshot,
) -> None:
    state = transition_for_verified_event(
        EscrowDealStatus.FUNDED_REVIEW, EscrowChainEventType.NFT_RETURN_STARTED
    )
    assert state is EscrowDealStatus.NFT_RETURN_PENDING
    state = transition_for_verified_event(state, EscrowChainEventType.NFT_RETURN_CONFIRMED)
    assert state is EscrowDealStatus.BUYER_REFUND_PENDING
    state = transition_for_verified_event(state, EscrowChainEventType.BUYER_REFUND_STARTED)
    assert state is EscrowDealStatus.BUYER_REFUND_PENDING
    state = transition_for_verified_event(state, EscrowChainEventType.BUYER_REFUND_CONFIRMED)
    assert state is EscrowDealStatus.REFUNDED

    valid_refund = evidence(
        event_type=EscrowChainEventType.BUYER_REFUND_CONFIRMED,
        source_address=deal.contract_address,
        destination_address=deal.buyer_address,
        item_address=None,
        amount_nanotons=deal.principal_nanotons,
    )
    validate_event_against_deal(valid_refund, deal)
    with pytest.raises(EscrowDomainError):
        validate_event_against_deal(
            evidence(
                event_type=EscrowChainEventType.BUYER_REFUND_CONFIRMED,
                source_address=deal.seller_address,
                destination_address=deal.buyer_address,
                item_address=None,
                amount_nanotons=deal.principal_nanotons,
            ),
            deal,
        )


def test_postdelivery_buyer_return_requires_exact_direction(deal: DealEvidenceSnapshot) -> None:
    returned = evidence(
        event_type=EscrowChainEventType.NFT_RETURN_TO_ESCROW_CONFIRMED,
        source_address=deal.buyer_address,
        destination_address=deal.contract_address,
    )
    validate_event_against_deal(returned, deal)
    with pytest.raises(EscrowDomainError):
        validate_event_against_deal(
            evidence(
                event_type=EscrowChainEventType.NFT_RETURN_TO_ESCROW_CONFIRMED,
                source_address=deal.seller_address,
                destination_address=deal.contract_address,
            ),
            deal,
        )

    state = transition_for_verified_event(
        EscrowDealStatus.DISPUTED, EscrowChainEventType.NFT_RETURN_TO_ESCROW_CONFIRMED
    )
    assert state is EscrowDealStatus.NFT_RETURN_PENDING
