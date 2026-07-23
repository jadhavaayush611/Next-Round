from fastapi import status
from fastapi.testclient import TestClient


def test_user_auth_flow(client: TestClient) -> None:
    """Tests the entire user sign-up, log-in, and authorization flow."""
    user_data = {
        "email": "test@nextround.in",
        "password": "strongpassword123",
        "name": "Test Candidate",
        "college": "IIT Bombay",
        "graduation_year": 2027,
        "branch": "Computer Science",
        "cgpa": 9.2,
        "target_role": "Backend Developer",
    }

    # 1. Registration
    reg_response = client.post("/api/v1/auth/register", json=user_data)
    assert reg_response.status_code == status.HTTP_201_CREATED
    assert reg_response.json()["email"] == user_data["email"]
    assert reg_response.json()["name"] == user_data["name"]
    assert "id" in reg_response.json()

    # 2. Duplicate email prevention
    dup_response = client.post("/api/v1/auth/register", json=user_data)
    assert dup_response.status_code == status.HTTP_400_BAD_REQUEST

    # 3. Accessing /me without JWT token
    fail_response = client.get("/api/v1/users/me")
    assert fail_response.status_code == status.HTTP_401_UNAUTHORIZED

    # 4. Login to acquire JWT access token
    login_data = {"username": user_data["email"], "password": user_data["password"]}
    login_response = client.post("/api/v1/auth/login", data=login_data)
    assert login_response.status_code == status.HTTP_200_OK
    assert "access_token" in login_response.json()
    token = login_response.json()["access_token"]

    # 5. Accessing /me with active JWT access token
    headers = {"Authorization": f"Bearer {token}"}
    me_response = client.get("/api/v1/users/me", headers=headers)
    assert me_response.status_code == status.HTTP_200_OK
    assert me_response.json()["email"] == user_data["email"]
    assert me_response.json()["target_role"] == "Backend Developer"
