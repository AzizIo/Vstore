import re
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ProofDomain(BaseModel):
    model_config = ConfigDict(populate_by_name=True, extra="forbid")

    length_bytes: int = Field(alias="lengthBytes", ge=0, le=128)
    value: str = Field(min_length=1, max_length=128)


class TonConnectProof(BaseModel):
    model_config = ConfigDict(extra="forbid")

    timestamp: int = Field(ge=0, le=2**64 - 1)
    domain: ProofDomain
    signature: str = Field(min_length=1, max_length=128)
    payload: str = Field(min_length=1, max_length=128)
    state_init: str = Field(min_length=1, max_length=16_384)

    @field_validator("timestamp", mode="before")
    @classmethod
    def parse_timestamp(cls, value: object) -> int:
        if isinstance(value, int) and not isinstance(value, bool):
            return value
        if isinstance(value, str) and re.fullmatch(r"[0-9]+", value):
            return int(value)
        raise ValueError("Timestamp must be an unsigned integer")


class VerifyWalletProofRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    address: str = Field(min_length=3, max_length=128)
    network: str = Field(pattern=r"^-?[0-9]+$", max_length=12)
    public_key: str | None = Field(default=None, pattern=r"^[0-9a-fA-F]{64}$")
    proof: TonConnectProof


class WalletProofChallengeResponse(BaseModel):
    payload: str
    expires_at: str


class WalletResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    address: str
    network: str
    is_verified: bool
    is_primary: bool
