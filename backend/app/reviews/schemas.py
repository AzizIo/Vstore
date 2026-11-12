from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator

MAX_COMMENT_LENGTH = 2000


class ReviewItem(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    rating: int
    comment: str | None
    created_at: datetime


class ReviewPageResponse(BaseModel):
    seller_id: UUID
    average_rating: float
    review_count: int
    rating_distribution: dict[str, int]
    items: list[ReviewItem]
    limit: int
    offset: int
    has_more: bool


class EligibilityResponse(BaseModel):
    order_id: UUID
    eligible: bool
    already_reviewed: bool


class ReviewCreateRequest(BaseModel):
    order_id: UUID
    rating: int = Field(ge=1, le=5)
    comment: str | None = Field(default=None, max_length=MAX_COMMENT_LENGTH)

    @field_validator("comment")
    @classmethod
    def normalize_comment(cls, value: str | None) -> str | None:
        if value is None:
            return None
        normalized = " ".join(value.split())
        return normalized or None


class ReviewCreateResponse(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: UUID
    order_id: UUID
    rating: int
    comment: str | None
    created_at: datetime
