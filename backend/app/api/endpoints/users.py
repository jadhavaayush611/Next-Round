from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.dependencies.auth import get_current_user
from app.models.user import User
from app.schemas.user import UserResponse, UserUpdate
from app.services.user import UserService

router = APIRouter()


@router.get("/me", response_model=UserResponse)
def get_current_user_profile(
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """Retrieve profile details of the currently authenticated user."""
    user_service = UserService(db)
    user = user_service.get_current_user_profile(current_user)
    return UserResponse.model_validate(user)


@router.patch("/me", response_model=UserResponse)
def update_user_profile(
    user_in: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    Update editable profile details of the authenticated user.
    Immutable fields (email, password_hash, role, is_active, created_at) are rejected with 422.
    """
    user_service = UserService(db)
    updated_user = user_service.update_user_profile(current_user, user_in)
    return UserResponse.model_validate(updated_user)


@router.put("/me", response_model=UserResponse)
def put_user_profile(
    user_in: UserUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
) -> UserResponse:
    """
    PUT endpoint for modifying user profile (delegates to patch implementation).
    """
    return update_user_profile(user_in=user_in, current_user=current_user, db=db)
