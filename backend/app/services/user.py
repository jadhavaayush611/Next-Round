import uuid
from datetime import UTC, datetime

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.core.security import create_access_token, get_password_hash, verify_password
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserUpdate


class UserService:
    def __init__(self, db: Session):
        self.user_repo = UserRepository(db)

    def get_user_by_id(self, user_id: uuid.UUID) -> User:
        """Fetch user by ID or raise 404 Not Found."""
        user = self.user_repo.get(user_id)
        if not user:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail="User not found.",
            )
        return user

    def get_current_user_profile(self, user: User) -> User:
        """Retrieve current user profile from database."""
        return self.get_user_by_id(user.id)

    def validate_username_uniqueness(
        self, username: str, current_user_id: uuid.UUID
    ) -> None:
        """Validate that username is unique across all users."""
        existing_user = self.user_repo.get_by_username(username)
        if existing_user and existing_user.id != current_user_id:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="Username already exists.",
            )

    def register_user(self, user_in: UserCreate) -> User:
        """Register a new user, verifying email uniqueness and hashing the password."""
        existing_user = self.user_repo.get_by_email(user_in.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already registered.",
            )

        if user_in.username:
            existing_username = self.user_repo.get_by_username(user_in.username)
            if existing_username:
                raise HTTPException(
                    status_code=status.HTTP_409_CONFLICT,
                    detail="Username already exists.",
                )

        hashed_password = get_password_hash(user_in.password)
        db_user = User(
            email=user_in.email,
            hashed_password=hashed_password,
            name=user_in.name,
            username=user_in.username,
        )
        return self.user_repo.create(db_user)

    def authenticate_user(self, email: str, plain_password: str) -> Token:
        """Authenticate user using email and password, returning a JWT access token."""
        user = self.user_repo.get_by_email(email)
        if not user or not verify_password(plain_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = create_access_token(subject=user.id)
        return Token(access_token=token, token_type="bearer")

    def update_user_profile(self, user: User, user_in: UserUpdate) -> User:
        """Update editable profile fields of the authenticated user."""
        update_data = user_in.model_dump(exclude_unset=True)

        if "full_name" in update_data and update_data["full_name"] is not None:
            update_data["name"] = update_data.pop("full_name")
        elif "full_name" in update_data:
            update_data.pop("full_name")

        if "username" in update_data and update_data["username"] is not None:
            self.validate_username_uniqueness(update_data["username"], user.id)

        update_data["updated_at"] = datetime.now(UTC)
        return self.user_repo.update(user, update_data)
