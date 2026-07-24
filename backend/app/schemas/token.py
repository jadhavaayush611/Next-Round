import uuid
from typing import Any

from pydantic import BaseModel, field_validator


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class TokenPayload(BaseModel):
    sub: uuid.UUID | None = None

    @field_validator("sub", mode="before")
    @classmethod
    def parse_sub(cls, v: Any) -> uuid.UUID | None:
        if isinstance(v, str):
            try:
                return uuid.UUID(v)
            except ValueError:
                return None
        if isinstance(v, uuid.UUID):
            return v
        return None
