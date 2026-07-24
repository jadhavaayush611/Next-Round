from fastapi import status
from fastapi.testclient import TestClient


def get_auth_token(client: TestClient, email: str, name: str) -> str:
    user_data = {
        "email": email,
        "password": "Password123!",
        "name": name,
    }
    client.post("/api/v1/auth/register", json=user_data)
    login_data: dict[str, str] = {"username": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/login", data=login_data)
    token: str = res.json()["access_token"]
    return token


def test_get_me_success(client: TestClient) -> None:
    token = get_auth_token(client, "get_me@nextround.in", "Get Me User")
    headers = {"Authorization": f"Bearer {token}"}
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["email"] == "get_me@nextround.in"
    assert data["name"] == "Get Me User"
    assert "hashed_password" not in data
    assert "password" not in data
    assert data["role"] == "user"
    assert data["is_active"] is True
    assert "created_at" in data
    assert "updated_at" in data


def test_patch_me_success(client: TestClient) -> None:
    token = get_auth_token(client, "patch_me@nextround.in", "Patch Me User")
    headers = {"Authorization": f"Bearer {token}"}
    payload = {
        "full_name": "Updated Patch Name",
        "username": "patch_user_1",
    }
    response = client.patch("/api/v1/users/me", headers=headers, json=payload)
    assert response.status_code == status.HTTP_200_OK
    data = response.json()
    assert data["name"] == "Updated Patch Name"
    assert data["full_name"] == "Updated Patch Name"
    assert data["username"] == "patch_user_1"


def test_patch_me_username_conflict(client: TestClient) -> None:
    token1 = get_auth_token(client, "user_a@nextround.in", "User A")
    token2 = get_auth_token(client, "user_b@nextround.in", "User B")

    headers1 = {"Authorization": f"Bearer {token1}"}
    headers2 = {"Authorization": f"Bearer {token2}"}

    client.patch(
        "/api/v1/users/me", headers=headers1, json={"username": "unique_handle"}
    )

    response = client.patch(
        "/api/v1/users/me", headers=headers2, json={"username": "unique_handle"}
    )
    assert response.status_code == status.HTTP_409_CONFLICT
    assert "Username already exists" in response.json()["detail"]
