from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserResponse, UserUpdate

router = APIRouter()


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
) -> UserResponse:
    """
    Retrieve profile details of the currently authenticated user.
    Uses the get_current_user dependency helper.
    """
    return current_user  # type: ignore[return-value]


@router.put("/me", response_model=UserResponse)
def update_user_profile(
    user_in: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Update profile details of the authenticated user.
    Supports password updating and hashing.
    """
    user_repo = UserRepository(db)

    update_data = user_in.model_dump(exclude_unset=True)
    if "password" in update_data and update_data["password"]:
        from app.core.security import get_password_hash

        update_data["hashed_password"] = get_password_hash(update_data.pop("password"))
    elif "password" in update_data:
        update_data.pop("password")

    return user_repo.update(current_user, update_data)  # type: ignore[return-value]
