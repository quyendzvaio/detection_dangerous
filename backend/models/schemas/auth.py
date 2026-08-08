from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _normalize_gmail(value: str) -> str:
    gmail = value.strip().lower()
    if not gmail.endswith("@gmail.com") or gmail == "@gmail.com":
        raise ValueError("a valid Gmail address ending in @gmail.com is required")
    return gmail


class UserRegister(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gmail: str = Field(min_length=11, max_length=254)
    password: str = Field(min_length=6, max_length=128)

    @field_validator("gmail")
    @classmethod
    def normalize_gmail(cls, value: str) -> str:
        return _normalize_gmail(value)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        if len(value.encode("utf-8")) > 72:
            raise ValueError("password must be at most 72 UTF-8 bytes")
        return value


class UserLogin(BaseModel):
    model_config = ConfigDict(extra="forbid")

    gmail: str = Field(min_length=11, max_length=254)
    password: str = Field(min_length=1, max_length=128)

    @field_validator("gmail")
    @classmethod
    def normalize_gmail(cls, value: str) -> str:
        return _normalize_gmail(value)

    @field_validator("password")
    @classmethod
    def validate_password_bytes(cls, value: str) -> str:
        return UserRegister.validate_password_bytes(value)


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    gmail: str
    role: str
    is_active: bool
    created_at: datetime
