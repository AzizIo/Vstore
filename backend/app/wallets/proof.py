import base64
import binascii
import hashlib
import re
import time
from collections.abc import Collection
from dataclasses import dataclass
from typing import cast

from nacl.exceptions import BadSignatureError
from nacl.signing import VerifyKey
from pytoniq.contract.wallets.wallet import (
    WALLET_V3_R1_CODE,
    WALLET_V3_R2_CODE,
    WALLET_V4_R2_CODE,
)
from pytoniq.contract.wallets.wallet_v5 import WALLET_V5_R1_CODE
from pytoniq_core.boc.address import Address
from pytoniq_core.boc.cell import Cell, CellError
from pytoniq_core.boc.deserialize import BocError
from pytoniq_core.boc.slice import Slice
from pytoniq_core.tlb.account import StateInit
from pytoniq_core.tlb.custom.wallet import WalletV3Data, WalletV4Data, WalletV5R1Data
from pytoniq_core.tlb.tlb import TlbError

from app.wallets.schemas import TonConnectProof, VerifyWalletProofRequest

CHALLENGE_TTL_SECONDS = 300
MAX_PROOF_AGE_SECONDS = 300
MAX_FUTURE_SKEW_SECONDS = 30

_RAW_ADDRESS_PATTERN = re.compile(r"^(?P<workchain>-?[0-9]+):(?P<hash>[0-9a-fA-F]{64})$")
_NETWORK_CHAIN_IDS = {"mainnet": "-239", "testnet": "-3"}


class WalletProofError(Exception):
    pass


class WalletProofConfigurationError(Exception):
    pass


@dataclass(frozen=True)
class VerifiedWalletProof:
    address: str
    network: str


def _is_valid_domain(domain: str) -> bool:
    labels = domain.split(".")
    return len(labels) >= 2 and all(
        0 < len(label) <= 63
        and label[0].isascii()
        and label[0].isalnum()
        and label[-1].isascii()
        and label[-1].isalnum()
        and all(
            character.isascii() and (character.isalnum() or character == "-")
            for character in label
        )
        for label in labels
    )


def validate_proof_configuration(
    allowed_domains: Collection[str], expected_network: str
) -> None:
    if expected_network not in _NETWORK_CHAIN_IDS:
        raise WalletProofConfigurationError("Unsupported TON network configuration")
    if not allowed_domains or any(not _is_valid_domain(domain) for domain in allowed_domains):
        raise WalletProofConfigurationError("TON Connect domain allowlist is not configured")


def _decode_base64(value: str) -> bytes:
    try:
        return base64.b64decode(value, altchars=b"-_", validate=True)
    except (binascii.Error, ValueError) as exc:
        raise WalletProofError("Invalid base64 value") from exc


def _public_key_from_state_init(state_init: StateInit) -> bytes:
    if state_init.code is None or state_init.data is None:
        raise WalletProofError("Wallet state init is incomplete")

    code_hash = state_init.code.hash
    if code_hash in (WALLET_V3_R1_CODE.hash, WALLET_V3_R2_CODE.hash):
        public_key = WalletV3Data.deserialize(_begin_parse(state_init.data)).public_key
    elif code_hash == WALLET_V4_R2_CODE.hash:
        public_key = WalletV4Data.deserialize(_begin_parse(state_init.data)).public_key
    elif code_hash == WALLET_V5_R1_CODE.hash:
        public_key = WalletV5R1Data.deserialize(_begin_parse(state_init.data)).public_key
    else:
        raise WalletProofError("Unsupported TON wallet contract")

    public_key = cast(bytes, public_key)
    if len(public_key) != 32:
        raise WalletProofError("Invalid wallet public key")
    return public_key


def _begin_parse(cell: Cell) -> Slice:
    # pytoniq-core currently omits a return annotation for begin_parse().
    return cast(Slice, cell.begin_parse())  # type: ignore[no-untyped-call]


def _parse_and_validate_account(
    request: VerifyWalletProofRequest,
) -> tuple[Address, bytes]:
    match = _RAW_ADDRESS_PATTERN.fullmatch(request.address)
    if match is None or match.group("workchain") != "0":
        raise WalletProofError("Wallet address must use raw TON format")

    address = Address((0, bytes.fromhex(match.group("hash"))))

    try:
        state_init_root = Cell.one_from_boc(_decode_base64(request.proof.state_init))
        state_init = StateInit.deserialize(_begin_parse(state_init_root))
        if state_init.serialize().hash != state_init_root.hash:
            raise WalletProofError("Invalid wallet state init")
        if state_init_root.hash != address.hash_part:
            raise WalletProofError("Wallet address does not match state init")
        public_key = _public_key_from_state_init(state_init)
    except WalletProofError:
        raise
    except (
        BocError,
        CellError,
        TlbError,
        ValueError,
        TypeError,
        IndexError,
        OverflowError,
    ) as exc:
        raise WalletProofError("Invalid wallet state init") from exc

    if request.public_key is not None and bytes.fromhex(request.public_key) != public_key:
        raise WalletProofError("Wallet public key does not match state init")
    return address, public_key


def _signature_message(
    address: Address,
    proof: TonConnectProof,
) -> bytes:
    domain_bytes = proof.domain.value.encode("utf-8")
    payload_bytes = proof.payload.encode("utf-8")
    if proof.domain.length_bytes != len(domain_bytes):
        raise WalletProofError("TON Connect domain byte length is incorrect")
    if (
        len(domain_bytes) > 128
        or len(payload_bytes) > 128
        or len(domain_bytes) + len(payload_bytes) > 222
    ):
        raise WalletProofError("TON Connect proof fields exceed protocol limits")
    if not _is_valid_domain(proof.domain.value):
        raise WalletProofError("Invalid TON Connect domain")

    message = (
        b"ton-proof-item-v2/"
        + address.wc.to_bytes(4, "big", signed=True)
        + address.hash_part
        + len(domain_bytes).to_bytes(4, "little")
        + domain_bytes
        + proof.timestamp.to_bytes(8, "little")
        + payload_bytes
    )
    return hashlib.sha256(b"\xff\xffton-connect" + hashlib.sha256(message).digest()).digest()


def verify_wallet_proof(
    request: VerifyWalletProofRequest,
    *,
    allowed_domains: Collection[str],
    expected_network: str,
    now: int | None = None,
) -> VerifiedWalletProof:
    validate_proof_configuration(allowed_domains, expected_network)

    if request.network != _NETWORK_CHAIN_IDS[expected_network]:
        raise WalletProofError("Wallet network does not match the configured network")
    if request.proof.domain.value not in allowed_domains:
        raise WalletProofError("TON Connect domain is not allowed")

    current_time = int(time.time()) if now is None else now
    if request.proof.timestamp < current_time - MAX_PROOF_AGE_SECONDS:
        raise WalletProofError("TON Connect proof has expired")
    if request.proof.timestamp > current_time + MAX_FUTURE_SKEW_SECONDS:
        raise WalletProofError("TON Connect proof timestamp is in the future")

    address, public_key = _parse_and_validate_account(request)
    signature = _decode_base64(request.proof.signature)
    if len(signature) != 64:
        raise WalletProofError("Invalid TON Connect signature")

    try:
        VerifyKey(public_key).verify(_signature_message(address, request.proof), signature)
    except (BadSignatureError, ValueError) as exc:
        raise WalletProofError("Invalid TON Connect signature") from exc

    normalized_address = f"{address.wc}:{address.hash_part.hex()}"
    return VerifiedWalletProof(address=normalized_address, network=expected_network)
