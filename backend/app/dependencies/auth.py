from fastapi import Depends, HTTPException, status
from fastapi.security import OAuth2PasswordBearer
from jose import JWTError, jwt
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.db.session import get_db
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.token import TokenPayload

oauth2_scheme = OAuth2PasswordBearer(tokenUrl=f"{settings.API_V1_STR}/auth/login")


def get_current_user(
    token: str = Depends(oauth2_scheme), db: Session = Depends(get_db)
) -> User:
    """
    Dependency to validate JWT tokens and fetch the corresponding User model.
    Raises 401 Unauthorized for invalid/expired tokens.
    """
    credentials_exception = HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail="Could not validate credentials",
        headers={"WWW-Authenticate": "Bearer"},
    )
    try:
        payload = jwt.decode(
            token, settings.JWT_SECRET, algorithms=[settings.JWT_ALGORITHM]
        )
        user_id = payload.get("sub")
        if user_id is None:
            raise credentials_exception
        token_payload = TokenPayload(sub=user_id)
        if token_payload.sub is None:
            raise credentials_exception
    except JWTError:
        raise credentials_exception from None

    user_repo = UserRepository(db)
    user = user_repo.get(token_payload.sub)
    if user is None:
        raise credentials_exception
    return user
