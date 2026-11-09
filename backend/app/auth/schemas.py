from pydantic import BaseModel, Field


class TelegramAuthRequest(BaseModel):
    init_data: str = Field(min_length=1, max_length=16_384)


class AuthenticatedUser(BaseModel):
    id: str
    telegram_id: int
    username: str | None
    first_name: str
    last_name: str | None


class TelegramAuthResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in: int
    user: AuthenticatedUser
