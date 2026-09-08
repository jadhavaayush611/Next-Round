import uuid
from datetime import timedelta

from fastapi import status
from fastapi.testclient import TestClient
from jose import jwt
from sqlalchemy.orm import Session

from app.core.security import create_access_token
from app.models.user import User


def test_get_me_unauthorized_no_header(client: TestClient) -> None:
    response = client.get("/api/v1/users/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_me_unauthorized_invalid_token(client: TestClient) -> None:
    headers = {"Authorization": "Bearer invalid_token_123"}
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_me_unauthorized_expired_token(client: TestClient) -> None:
    expired_token = create_access_token(
        subject=uuid.uuid4(), expires_delta=timedelta(minutes=-10)
    )
    headers = {"Authorization": f"Bearer {expired_token}"}
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
    assert response.json()["detail"] == "Could not validate credentials"


def test_get_me_unauthorized_invalid_signature(client: TestClient) -> None:
    token_wrong_sig = jwt.encode(
        {"sub": str(uuid.uuid4())}, "wrong_secret_key_12345", algorithm="HS256"
    )
    headers = {"Authorization": f"Bearer {token_wrong_sig}"}
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_me_unauthorized_invalid_subject_not_uuid(client: TestClient) -> None:
    token_bad_sub = create_access_token(subject="not-a-valid-uuid-string")
    headers = {"Authorization": f"Bearer {token_bad_sub}"}
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_me_unauthorized_nonexistent_user_id(client: TestClient) -> None:
    random_user_id = uuid.uuid4()
    token = create_access_token(subject=random_user_id)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_me_unauthorized_inactive_user(client: TestClient, db: Session) -> None:
    # Register user and then set is_active to False
    user_data = {
        "email": "inactive_auth@nextround.in",
        "password": "Password123!",
        "name": "Inactive User",
    }
    client.post("/api/v1/auth/register", json=user_data)
    user = db.query(User).filter(User.email == user_data["email"]).first()
    assert user is not None
    user.is_active = False
    db.commit()

    token = create_access_token(subject=user.id)
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED

    # Also verify inactive user cannot login
    login_res = client.post(
        "/api/v1/auth/login",
        data={"username": user_data["email"], "password": user_data["password"]},
    )
    assert login_res.status_code == status.HTTP_401_UNAUTHORIZED


def test_patch_me_unauthorized_no_header(client: TestClient) -> None:
    response = client.patch("/api/v1/users/me", json={"full_name": "New Name"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_patch_me_unauthorized_invalid_token(client: TestClient) -> None:
    headers = {"Authorization": "Bearer invalid_token_123"}
    response = client.patch(
        "/api/v1/users/me", headers=headers, json={"full_name": "New Name"}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
