from fastapi import APIRouter, Depends, status
from fastapi.security import OAuth2PasswordRequestForm
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.schemas.token import Token
from app.schemas.user import UserCreate, UserResponse
from app.services.user import UserService

router = APIRouter()


@router.post(
    "/register", response_model=UserResponse, status_code=status.HTTP_201_CREATED
)
def register(user_in: UserCreate, db: Session = Depends(get_db)) -> UserResponse:
    """
    Register a new student account.
    Validates input and issues a new user record.
    """
    user_service = UserService(db)
    user = user_service.register_user(user_in)
    return UserResponse.model_validate(user)


@router.post("/login", response_model=Token)
def login(
    form_data: OAuth2PasswordRequestForm = Depends(), db: Session = Depends(get_db)
) -> Token:
    """
    Standard OAuth2 password flow login.
    Validates credentials and returns a Bearer access token.
    """
    user_service = UserService(db)
    return user_service.authenticate_user(form_data.username, form_data.password)
