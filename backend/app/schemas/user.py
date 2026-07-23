import uuid
from datetime import datetime

from pydantic import BaseModel, ConfigDict, EmailStr


class UserBase(BaseModel):
    email: EmailStr
    name: str
    college: str | None = None
    graduation_year: int | None = None
    branch: str | None = None
    cgpa: float | None = None
    target_role: str | None = None


class UserCreate(UserBase):
    password: str


class UserUpdate(BaseModel):
    email: EmailStr | None = None
    name: str | None = None
    password: str | None = None
    college: str | None = None
    graduation_year: int | None = None
    branch: str | None = None
    cgpa: float | None = None
    target_role: str | None = None


class UserResponse(UserBase):
    model_config = ConfigDict(from_attributes=True)

    id: uuid.UUID
    created_at: datetime
