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
        collection_address="0:" + "f" * 64,
        item_address="0:" + "b" * 64,
        seller_address="0:" + "c" * 64,
        buyer_address="0:" + "d" * 64,
        principal_nanotons=2_500_000_000,
        execution_reserve_nanotons=500_000_000,
    )


def evidence(
    *, event_type: EscrowChainEventType = EscrowChainEventType.NFT_DEPOSIT_ACCEPTED,
    **overrides: object,
) -> NormalizedEventEvidence:
    values: dict[str, object] = {
        "network": "testnet",
        "contract_address": "0:" + "a" * 64,
        "event_type": event_type,
        "source_address": "0:" + "c" * 64,
        "destination_address": "0:" + "a" * 64,
        "item_address": "0:" + "b" * 64,
        "collection_address": "0:" + "f" * 64,
        "amount_nanotons": None,
        "masterchain_seqno": 123,
        "finalized": True,
        "message_hash": "msg-1",
        "trace_id": "trace-1",
        "phase": "transaction",
        "attempt_id": "attempt-1",
        "deal_salt": "d" * 64,
    }
    values.update(overrides)
    return NormalizedEventEvidence(**values)  # type: ignore[arg-type]


def test_state_machine_requires_buyer_acceptance_before_delivery() -> None:
    state = transition_for_verified_event(
        EscrowDealStatus.INTENT_CREATED, EscrowChainEventType.CONTRACT_ACTIVATED
    )
    assert state is EscrowDealStatus.AWAITING_NFT
    state = transition_for_verified_event(state, EscrowChainEventType.NFT_DEPOSIT_ACCEPTED)
    assert state is EscrowDealStatus.AWAITING_BUYER_FUNDS
    state = transition_for_verified_event(state, EscrowChainEventType.BUYER_PAYMENT_ACCEPTED)
    assert state is EscrowDealStatus.FUNDED_REVIEW
    state = transition_for_verified_event(state, EscrowChainEventType.BUYER_ACCEPTANCE_RECORDED)
    assert state is EscrowDealStatus.NFT_RELEASE_PENDING
    state = transition_for_verified_event(
        state,
        EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED,
        EscrowDealStatus.DELIVERED_DISPUTE_WINDOW.value,
    )
    assert state is EscrowDealStatus.DELIVERED_DISPUTE_WINDOW


def test_raw_nft_transfer_observation_cannot_advance_deal_state(
    deal: DealEvidenceSnapshot,
) -> None:
    for event_type in (
        EscrowChainEventType.NFT_TRANSFER_CONFIRMED,
        EscrowChainEventType.NFT_DELIVERY_EVIDENCE_OBSERVED,
    ):
        with pytest.raises(EscrowDomainError):
            transition_for_verified_event(EscrowDealStatus.NFT_RELEASE_PENDING, event_type)
        with pytest.raises(EscrowDomainError):
            validate_event_against_deal(evidence(event_type=event_type), deal)


def test_replay_or_out_of_order_event_cannot_advance_state() -> None:
    with pytest.raises(EscrowDomainError):
        transition_for_verified_event(
            EscrowDealStatus.FUNDED_REVIEW, EscrowChainEventType.NFT_DEPOSIT_ACCEPTED
        )
    with pytest.raises(EscrowDomainError):
        transition_for_verified_event(
            EscrowDealStatus.SETTLED, EscrowChainEventType.SELLER_PAYOUT_RECONCILED
        )


def test_exact_nft_deposit_attestation_is_validated(deal: DealEvidenceSnapshot) -> None:
    validate_event_against_deal(evidence(), deal)


@pytest.mark.parametrize(
    "overrides",
    [
        {"item_address": "0:" + "e" * 64},
        {"collection_address": "0:" + "e" * 64},
        {"source_address": "0:" + "f" * 64},
        {"contract_address": "0:" + "e" * 64},
        {"network": "mainnet"},
        {"finalized": False},
        {"masterchain_seqno": 0},
    ],
)
def test_bad_or_nonfinal_deposit_is_rejected(
    deal: DealEvidenceSnapshot, overrides: dict[str, object]
) -> None:
    with pytest.raises(EscrowDomainError):
        validate_event_against_deal(evidence(**overrides), deal)


def test_payment_requires_exact_buyer_and_principal(deal: DealEvidenceSnapshot) -> None:
    correct = evidence(
        event_type=EscrowChainEventType.BUYER_PAYMENT_ACCEPTED,
        source_address=deal.buyer_address,
        item_address=None,
        amount_nanotons=deal.principal_nanotons + int(deal.execution_reserve_nanotons or 0),
    )
    validate_event_against_deal(correct, deal)
    for changes in (
        {
            "amount_nanotons": deal.principal_nanotons
            + int(deal.execution_reserve_nanotons or 0)
            - 1
        },
        {"source_address": deal.seller_address},
        {"destination_address": deal.buyer_address},
    ):
        with pytest.raises(EscrowDomainError):
            validate_event_against_deal(
                evidence(event_type=EscrowChainEventType.BUYER_PAYMENT_ACCEPTED, **{
                    "source_address": deal.buyer_address,
                    "destination_address": deal.contract_address,
                    "item_address": None,
                    "amount_nanotons": deal.principal_nanotons,
                    **changes,
                }),
                deal,
            )


def test_delivery_requires_accepted_attestation_and_reconciled_getter(
    deal: DealEvidenceSnapshot,
) -> None:
    good = evidence(
        event_type=EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED,
        source_address=deal.contract_address,
        destination_address=deal.buyer_address,
        attestation_accepted=True,
        contract_state_reconciled=True,
        observed_contract_state=EscrowDealStatus.DELIVERED_DISPUTE_WINDOW.value,
    )
    validate_event_against_deal(good, deal)
    for changes in (
        {"attestation_accepted": False},
        {"contract_state_reconciled": False},
        {"observed_contract_state": EscrowDealStatus.NFT_RELEASE_PENDING.value},
        {"trace_id": None},
        {"attempt_id": None},
    ):
        with pytest.raises(EscrowDomainError):
            validate_event_against_deal(
                evidence(event_type=EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED, **{
                    "source_address": deal.contract_address,
                    "destination_address": deal.buyer_address,
                    "attestation_accepted": True,
                    "contract_state_reconciled": True,
                    "observed_contract_state": EscrowDealStatus.DELIVERED_DISPUTE_WINDOW.value,
                    **changes,
                }),
                deal,
            )


def test_client_cannot_invent_a_chain_transition() -> None:
    with pytest.raises(EscrowDomainError):
        transition_for_verified_event(EscrowDealStatus.INTENT_CREATED, "client_paid")


def test_missing_contract_binding_fails_closed(deal: DealEvidenceSnapshot) -> None:
    unbound = DealEvidenceSnapshot(
        network=deal.network,
        contract_address=None,
        collection_address=deal.collection_address,
        item_address=deal.item_address,
        seller_address=deal.seller_address,
        buyer_address=deal.buyer_address,
        principal_nanotons=deal.principal_nanotons,
    )
    with pytest.raises(EscrowDomainError):
        validate_event_against_deal(evidence(), unbound)


def test_payout_and_refund_only_settle_after_reconciliation() -> None:
    state = transition_for_verified_event(
        EscrowDealStatus.DELIVERED_DISPUTE_WINDOW,
        EscrowChainEventType.SELLER_PAYOUT_INITIATED,
    )
    assert state is EscrowDealStatus.SELLER_PAYOUT_PENDING
    state = transition_for_verified_event(
        state, EscrowChainEventType.SELLER_PAYOUT_RECONCILED, EscrowDealStatus.SETTLED.value
    )
    assert state is EscrowDealStatus.SETTLED

    state = transition_for_verified_event(
        EscrowDealStatus.DISPUTED,
        EscrowChainEventType.DISPUTE_RESOLUTION_ACCEPTED,
        EscrowDealStatus.NFT_RETURN_PENDING.value,
    )
    assert state is EscrowDealStatus.NFT_RETURN_PENDING
    state = transition_for_verified_event(
        state,
        EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED,
        EscrowDealStatus.BUYER_REFUND_PENDING.value,
    )
    assert state is EscrowDealStatus.BUYER_REFUND_PENDING
    state = transition_for_verified_event(
        state,
        EscrowChainEventType.BUYER_REFUND_RECONCILED,
        EscrowDealStatus.REFUNDED.value,
    )
    assert state is EscrowDealStatus.REFUNDED


@pytest.mark.parametrize(
    ("event_type", "state", "expected"),
    [
        (
            EscrowChainEventType.DEAL_TIMEOUT_ACCEPTED,
            EscrowDealStatus.NFT_RETURN_PENDING.value,
            EscrowDealStatus.NFT_RETURN_PENDING,
        ),
        (
            EscrowChainEventType.DEAL_TIMEOUT_ACCEPTED,
            EscrowDealStatus.SELLER_PAYOUT_PENDING.value,
            EscrowDealStatus.SELLER_PAYOUT_PENDING,
        ),
        (
            EscrowChainEventType.DEAL_TIMEOUT_ACCEPTED,
            EscrowDealStatus.EXPIRED.value,
            EscrowDealStatus.EXPIRED,
        ),
        (
            EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED,
            EscrowDealStatus.SELLER_PAYOUT_PENDING.value,
            EscrowDealStatus.SELLER_PAYOUT_PENDING,
        ),
        (
            EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED,
            EscrowDealStatus.EXPIRED.value,
            EscrowDealStatus.EXPIRED,
        ),
    ],
)
def test_multi_outcome_contract_events_require_proof_read_state(
    event_type: EscrowChainEventType,
    state: str,
    expected: EscrowDealStatus,
) -> None:
    current = (
        EscrowDealStatus.DELIVERED_DISPUTE_WINDOW
        if event_type is EscrowChainEventType.DEAL_TIMEOUT_ACCEPTED
        and state == EscrowDealStatus.SELLER_PAYOUT_PENDING.value
        else EscrowDealStatus.NFT_RETURN_PENDING
        if event_type is EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED
        else EscrowDealStatus.NFT_RELEASE_PENDING
        if event_type is EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED
        else EscrowDealStatus.AWAITING_BUYER_FUNDS
        if state == EscrowDealStatus.EXPIRED.value
        else EscrowDealStatus.FUNDED_REVIEW
    )
    assert transition_for_verified_event(current, event_type, state) is expected
    with pytest.raises(EscrowDomainError):
        transition_for_verified_event(current, event_type, None)


def test_unknown_nft_recovery_never_implicitly_releases_listing() -> None:
    state = transition_for_verified_event(
        EscrowDealStatus.MANUAL_REVIEW,
        EscrowChainEventType.RECOVERY_NFT_RETURN_STARTED,
        EscrowDealStatus.NFT_RETURN_PENDING.value,
    )
    assert state is EscrowDealStatus.NFT_RETURN_PENDING
    state = transition_for_verified_event(
        state,
        EscrowChainEventType.MANUAL_REVIEW_REQUIRED,
    )
    assert state is EscrowDealStatus.MANUAL_REVIEW


def test_nft_return_attestation_requires_contract_to_seller_route(
    deal: DealEvidenceSnapshot,
) -> None:
    expected = evidence(
        event_type=EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED,
        source_address=deal.contract_address,
        destination_address=deal.seller_address,
        amount_nanotons=0,
        attestation_accepted=True,
        contract_state_reconciled=True,
        observed_contract_state=EscrowDealStatus.BUYER_REFUND_PENDING.value,
    )
    validate_event_against_deal(expected, deal)
    for changes in (
        {"source_address": deal.buyer_address},
        {"destination_address": deal.contract_address},
        {"amount_nanotons": 1},
        {"attestation_accepted": False},
        {"contract_state_reconciled": False},
    ):
        payload: dict[str, object] = {
            "source_address": deal.contract_address,
            "destination_address": deal.seller_address,
            "amount_nanotons": 0,
            "attestation_accepted": True,
            "contract_state_reconciled": True,
            "observed_contract_state": EscrowDealStatus.BUYER_REFUND_PENDING.value,
        }
        payload.update(changes)
        with pytest.raises(EscrowDomainError):
            validate_event_against_deal(
                evidence(
                    event_type=EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED,
                    **payload,
                ),
                deal,
            )


def test_buyer_acceptance_attestation_requires_the_bound_buyer(
    deal: DealEvidenceSnapshot,
) -> None:
    accepted = evidence(
        event_type=EscrowChainEventType.BUYER_ACCEPTANCE_RECORDED,
        source_address=deal.buyer_address,
        destination_address=deal.contract_address,
        item_address=None,
    )
    validate_event_against_deal(accepted, deal)

    with pytest.raises(EscrowDomainError):
        validate_event_against_deal(
            evidence(
                event_type=EscrowChainEventType.BUYER_ACCEPTANCE_RECORDED,
                source_address=deal.seller_address,
                destination_address=deal.contract_address,
                item_address=None,
            ),
            deal,
        )



def test_outbound_bounce_state_machine_preserves_terminal_and_noncritical_states(
    deal: DealEvidenceSnapshot,
) -> None:
    matched = evidence(
        event_type=EscrowChainEventType.OUTBOUND_ACTION_BOUNCED,
        source_address=deal.contract_address,
        phase="bounce",
        observed_contract_state=EscrowDealStatus.MANUAL_REVIEW.value,
        contract_state_reconciled=True,
    )
    validate_event_against_deal(matched, deal)
    assert transition_for_verified_event(
        EscrowDealStatus.NFT_RELEASE_PENDING,
        EscrowChainEventType.OUTBOUND_ACTION_BOUNCED,
        EscrowDealStatus.MANUAL_REVIEW.value,
    ) is EscrowDealStatus.MANUAL_REVIEW

    assert transition_for_verified_event(
        EscrowDealStatus.EXPIRED,
        EscrowChainEventType.OUTBOUND_ACTION_BOUNCED,
        EscrowDealStatus.EXPIRED.value,
    ) is EscrowDealStatus.EXPIRED

    with pytest.raises(EscrowDomainError, match="terminal deal"):
        transition_for_verified_event(
            EscrowDealStatus.SETTLED,
            EscrowChainEventType.OUTBOUND_ACTION_BOUNCED,
            EscrowDealStatus.MANUAL_REVIEW.value,
        )


def test_unmatched_outbound_bounce_cannot_transition_a_deal() -> None:
    with pytest.raises(EscrowDomainError, match="unmatched bounce"):
        transition_for_verified_event(
            EscrowDealStatus.NFT_RELEASE_PENDING,
            EscrowChainEventType.OUTBOUND_BOUNCE_UNMATCHED,
            EscrowDealStatus.MANUAL_REVIEW.value,
        )


@pytest.mark.parametrize(
    ("event_type", "target"),
    [
        (
            EscrowChainEventType.ORACLE_DELIVERY_ATTESTATION_ACCEPTED,
            EscrowDealStatus.DELIVERED_DISPUTE_WINDOW,
        ),
        (
            EscrowChainEventType.ORACLE_NFT_RETURN_ATTESTATION_ACCEPTED,
            EscrowDealStatus.BUYER_REFUND_PENDING,
        ),
        (
            EscrowChainEventType.SELLER_PAYOUT_RECONCILED,
            EscrowDealStatus.SETTLED,
        ),
        (
            EscrowChainEventType.BUYER_REFUND_RECONCILED,
            EscrowDealStatus.REFUNDED,
        ),
    ],
)
def test_late_proof_verified_outbound_finality_can_resume_manual_review(
    event_type: EscrowChainEventType,
    target: EscrowDealStatus,
) -> None:
    # Timeout/manual review is a safety hold, not a terminal settlement. A later
    # finalized contract-accepted attestation may resume only its getter-proved
    # target state; event labels alone cannot select or invent that transition.
    assert transition_for_verified_event(
        EscrowDealStatus.MANUAL_REVIEW,
        event_type,
        target.value,
    ) is target
    with pytest.raises(EscrowDomainError):
        transition_for_verified_event(
            EscrowDealStatus.MANUAL_REVIEW,
            event_type,
            EscrowDealStatus.MANUAL_REVIEW.value,
        )


@pytest.mark.parametrize(
    ("event_type", "target", "source", "destination", "amount"),
    [
        (
            EscrowChainEventType.SELLER_PAYOUT_RECONCILED,
            EscrowDealStatus.SETTLED,
            "seller",
            "seller",
            2_500_000_000,
        ),
        (
            EscrowChainEventType.BUYER_REFUND_RECONCILED,
            EscrowDealStatus.REFUNDED,
            "buyer",
            "buyer",
            2_500_000_000,
        ),
    ],
)
def test_principal_settlement_requires_accepted_attestation_and_getter(
    deal: DealEvidenceSnapshot,
    event_type: EscrowChainEventType,
    target: EscrowDealStatus,
    source: str,
    destination: str,
    amount: int,
) -> None:
    good = evidence(
        event_type=event_type,
        source_address=deal.contract_address,
        destination_address=(
            deal.seller_address if destination == "seller" else deal.buyer_address
        ),
        amount_nanotons=amount,
        attestation_accepted=True,
        contract_state_reconciled=True,
        observed_contract_state=target.value,
    )
    validate_event_against_deal(good, deal)

    for changes in (
        {"attestation_accepted": False},
        {"contract_state_reconciled": False},
        {"observed_contract_state": EscrowDealStatus.MANUAL_REVIEW.value},
    ):
        payload: dict[str, object] = {
            "source_address": deal.contract_address,
            "destination_address": (
                deal.seller_address if destination == "seller" else deal.buyer_address
            ),
            "amount_nanotons": amount,
            "attestation_accepted": True,
            "contract_state_reconciled": True,
            "observed_contract_state": target.value,
        }
        payload.update(changes)
        with pytest.raises(EscrowDomainError):
            validate_event_against_deal(evidence(event_type=event_type, **payload), deal)
