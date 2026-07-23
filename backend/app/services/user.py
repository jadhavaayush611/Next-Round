from sqlalchemy.orm import Session
from app.core.security import get_password_hash, verify_password, create_access_token
from app.models.user import User
from app.repositories.user import UserRepository
from app.schemas.user import UserCreate
from app.schemas.token import Token
from fastapi import HTTPException, status


class UserService:
    def __init__(self, db: Session):
        self.user_repo = UserRepository(db)

    def register_user(self, user_in: UserCreate) -> User:
        """Register a new user, verifying email uniqueness and hashing the password."""
        existing_user = self.user_repo.get_by_email(user_in.email)
        if existing_user:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Email is already registered.",
            )

        hashed_password = get_password_hash(user_in.password)
        db_user = User(
            email=user_in.email,
            hashed_password=hashed_password,
            name=user_in.name,
            college=user_in.college,
            graduation_year=user_in.graduation_year,
            branch=user_in.branch,
            cgpa=user_in.cgpa,
            target_role=user_in.target_role,
        )
        return self.user_repo.create(db_user)

    def authenticate_user(self, email: str, plain_password: str) -> Token:
        """Authenticate a user using email and password, returning a JWT access token."""
        user = self.user_repo.get_by_email(email)
        if not user or not verify_password(plain_password, user.hashed_password):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Incorrect email or password.",
                headers={"WWW-Authenticate": "Bearer"},
            )

        token = create_access_token(subject=user.id)
        return Token(access_token=token, token_type="bearer")
