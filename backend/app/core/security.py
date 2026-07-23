from datetime import UTC, datetime, timedelta
from typing import Any

import bcrypt
from jose import jwt
from passlib.context import CryptContext

from app.config.settings import settings

# Fix passlib compatibility with bcrypt 4.x/5.x
if not hasattr(bcrypt, "__about__"):
    ver = getattr(bcrypt, "__version__", "5.0.0")
    bcrypt.__about__ = type("about", (), {"__version__": ver})  # type: ignore[attr-defined]

_orig_hashpw = bcrypt.hashpw


def _patched_hashpw(password: bytes, salt: bytes) -> bytes:
    if len(password) > 72:
        password = password[:72]
    return _orig_hashpw(password, salt)


bcrypt.hashpw = _patched_hashpw

# Setup password context
pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def verify_password(plain_password: str, hashed_password: str) -> bool:
    """Verify a plain password against its hash."""
    return bool(pwd_context.verify(plain_password[:72], hashed_password))


def get_password_hash(password: str) -> str:
    """Hash a password using bcrypt."""
    return str(pwd_context.hash(password[:72]))


def create_access_token(
    subject: str | Any, expires_delta: timedelta | None = None
) -> str:
    """Create a JWT access token for a subject (usually user ID)."""
    if expires_delta:
        expire = datetime.now(UTC) + expires_delta
    else:
        expire = datetime.now(UTC) + timedelta(
            minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES
        )
    to_encode = {"exp": expire, "sub": str(subject)}
    encoded_jwt = jwt.encode(
        to_encode, settings.JWT_SECRET, algorithm=settings.JWT_ALGORITHM
    )
    return str(encoded_jwt)
