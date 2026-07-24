from fastapi import status
from fastapi.testclient import TestClient


def test_get_me_unauthorized_no_header(client: TestClient) -> None:
    response = client.get("/api/v1/users/me")
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_get_me_unauthorized_invalid_token(client: TestClient) -> None:
    headers = {"Authorization": "Bearer invalid_token_123"}
    response = client.get("/api/v1/users/me", headers=headers)
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_patch_me_unauthorized_no_header(client: TestClient) -> None:
    response = client.patch("/api/v1/users/me", json={"full_name": "New Name"})
    assert response.status_code == status.HTTP_401_UNAUTHORIZED


def test_patch_me_unauthorized_invalid_token(client: TestClient) -> None:
    headers = {"Authorization": "Bearer invalid_token_123"}
    response = client.patch(
        "/api/v1/users/me", headers=headers, json={"full_name": "New Name"}
    )
    assert response.status_code == status.HTTP_401_UNAUTHORIZED
