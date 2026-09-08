from fastapi import status
from fastapi.testclient import TestClient


def get_auth_token(client: TestClient, email: str) -> str:
    user_data = {
        "email": email,
        "password": "Password123!",
        "name": "Validation User",
    }
    client.post("/api/v1/auth/register", json=user_data)
    login_data: dict[str, str] = {"username": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/login", data=login_data)
    token: str = res.json()["access_token"]
    return token


def test_reject_empty_update_payload(client: TestClient) -> None:
    token = get_auth_token(client, "empty_val@nextround.in")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch("/api/v1/users/me", headers=headers, json={})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_reject_immutable_email(client: TestClient) -> None:
    token = get_auth_token(client, "immutable_email@nextround.in")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch(
        "/api/v1/users/me", headers=headers, json={"email": "new_email@nextround.in"}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_reject_immutable_password_hash(client: TestClient) -> None:
    token = get_auth_token(client, "immutable_pwd@nextround.in")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch(
        "/api/v1/users/me", headers=headers, json={"password_hash": "newhash"}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_reject_immutable_role(client: TestClient) -> None:
    token = get_auth_token(client, "immutable_role@nextround.in")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch("/api/v1/users/me", headers=headers, json={"role": "admin"})
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_reject_immutable_is_active(client: TestClient) -> None:
    token = get_auth_token(client, "immutable_active@nextround.in")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch(
        "/api/v1/users/me", headers=headers, json={"is_active": False}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_reject_immutable_created_at(client: TestClient) -> None:
    token = get_auth_token(client, "immutable_created@nextround.in")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"created_at": "2020-01-01T00:00:00"},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_reject_placement_profile_fields_on_user(client: TestClient) -> None:
    token = get_auth_token(client, "placement_fields@nextround.in")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch(
        "/api/v1/users/me",
        headers=headers,
        json={"college": "BITS Pilani", "cgpa": 9.5},
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_validate_empty_name(client: TestClient) -> None:
    token = get_auth_token(client, "empty_name@nextround.in")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch(
        "/api/v1/users/me", headers=headers, json={"full_name": "   "}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_validate_invalid_username_format(client: TestClient) -> None:
    token = get_auth_token(client, "bad_username@nextround.in")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.patch(
        "/api/v1/users/me", headers=headers, json={"username": "ab"}
    )
    assert response.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
