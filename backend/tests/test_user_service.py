import uuid

import pytest
from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from app.schemas.user import UserCreate, UserUpdate
from app.services.user import UserService


def test_user_service_registration_and_retrieval(db: Session) -> None:
    service = UserService(db)
    user_in = UserCreate(
        email="service_user@nextround.in",
        password="securepassword123",
        name="Service User",
        username="service_user_1",
    )
    user = service.register_user(user_in)
    assert user.email == "service_user@nextround.in"
    assert user.name == "Service User"
    assert user.username == "service_user_1"

    fetched = service.get_user_by_id(user.id)
    assert fetched.id == user.id


def test_user_service_get_not_found(db: Session) -> None:
    service = UserService(db)
    fake_id = uuid.uuid4()
    with pytest.raises(HTTPException) as exc_info:
        service.get_user_by_id(fake_id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_user_service_update_profile(db: Session) -> None:
    service = UserService(db)
    user_in = UserCreate(
        email="update_service@nextround.in",
        password="securepassword123",
        name="Original Name",
    )
    user = service.register_user(user_in)

    update_in = UserUpdate(
        full_name="Updated Name",
        username="updated_user_99",
    )
    updated = service.update_user_profile(user, update_in)
    assert updated.name == "Updated Name"
    assert updated.full_name == "Updated Name"
    assert updated.username == "updated_user_99"


def test_user_service_username_uniqueness_conflict(db: Session) -> None:
    service = UserService(db)
    service.register_user(
        UserCreate(
            email="user1@nextround.in",
            password="password123",
            name="User One",
            username="taken_username",
        )
    )
    user2 = service.register_user(
        UserCreate(
            email="user2@nextround.in",
            password="password123",
            name="User Two",
        )
    )

    update_in = UserUpdate(username="taken_username")
    with pytest.raises(HTTPException) as exc_info:
        service.update_user_profile(user2, update_in)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "Username already exists" in exc_info.value.detail


def test_user_service_update_same_username_allowed(db: Session) -> None:
    service = UserService(db)
    user = service.register_user(
        UserCreate(
            email="same_user@nextround.in",
            password="password123",
            name="Same User",
            username="my_username",
        )
    )
    update_in = UserUpdate(username="my_username", full_name="Same User Updated")
    updated = service.update_user_profile(user, update_in)
    assert updated.username == "my_username"
    assert updated.name == "Same User Updated"


def test_user_service_duplicate_email_conflict(db: Session) -> None:
    service = UserService(db)
    service.register_user(
        UserCreate(
            email="duplicate@nextround.in",
            password="password123",
            name="User Original",
        )
    )
    with pytest.raises(HTTPException) as exc_info:
        service.register_user(
            UserCreate(
                email="duplicate@nextround.in",
                password="password123",
                name="User Duplicate",
            )
        )
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "Email is already registered" in exc_info.value.detail


def test_user_persistence_and_soft_delete(db: Session) -> None:
    """Tests CRUD persistence lifecycle including soft deletion."""
    from app.repositories.user import UserRepository

    repo = UserRepository(db)
    service = UserService(db)

    # 1. Create
    user = service.register_user(
        UserCreate(
            email="persistence@nextround.in",
            password="password123",
            name="Persistence User",
            username="persist_user",
        )
    )
    user_id = user.id
    assert user.is_active is True

    # 2. Lookup by ID, Email, and Username
    assert repo.get(user_id) is not None
    assert repo.get_by_email("persistence@nextround.in") is not None
    assert repo.get_by_username("persist_user") is not None

    # 3. Update
    updated = repo.update(user, {"name": "Updated Persist User"})
    assert updated.name == "Updated Persist User"

    # 4. Soft Delete (is_active = False)
    soft_deleted = repo.update(user, {"is_active": False})
    assert soft_deleted.is_active is False

    # Soft-deleted user record still exists for audit, but is_active is False
    persisted_user = repo.get(user_id)
    assert persisted_user is not None
    assert persisted_user.is_active is False
