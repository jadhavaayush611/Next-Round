import re
import uuid
from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, EmailStr, field_validator, model_validator

IMMUTABLE_FIELDS = {
    "email",
    "password",
    "password_hash",
    "hashed_password",
    "role",
    "is_active",
    "created_at",
    "updated_at",
    "id",
}


class UserBase(BaseModel):
    email: EmailStr
    name: str
    full_name: str | None = None
    username: str | None = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = None
    full_name: str | None = None
    username: str | None = None

    @model_validator(mode="before")
    @classmethod
    def check_immutable_and_empty(cls, data: Any) -> Any:
        if not isinstance(data, dict):
            raise ValueError("Invalid payload format")

        immutable_found = [f for f in data if f in IMMUTABLE_FIELDS]
        if immutable_found:
            raise ValueError(
                f"Fields {', '.join(sorted(immutable_found))} are immutable and cannot be updated"
            )

        editable_provided = {
            k: v for k, v in data.items() if k in {"name", "full_name", "username"}
        }
        if not editable_provided:
            raise ValueError(
                "Update payload cannot be empty. At least one editable field must be provided."
            )

        return data

    @field_validator("name", "full_name", mode="before")
    @classmethod
    def validate_name(cls, v: Any) -> Any:
        if v is not None:
            if isinstance(v, str):
                v_str = v.strip()
                if not v_str:
                    raise ValueError("Name cannot be empty")
                return v_str
            raise ValueError("Name must be a string")
        return v

    @field_validator("username", mode="before")
    @classmethod
    def validate_username(cls, v: Any) -> Any:
        if v is not None:
            if isinstance(v, str):
                v_str = v.strip()
                if not v_str:
                    raise ValueError("Username cannot be empty")
                if not re.match(r"^[a-zA-Z0-9_-]{3,30}$", v_str):
                    raise ValueError(
                        "Username must be 3-30 characters long and contain only letters, numbers, underscores, or hyphens"
                    )
                return v_str
            raise ValueError("Username must be a string")
        return v


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    role: str = "user"
    is_active: bool = True
    created_at: datetime
    updated_at: datetime
