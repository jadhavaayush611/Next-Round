from fastapi import status
from fastapi.testclient import TestClient


def test_healthcheck(client: TestClient) -> None:
    """Test health check route returns operational status code and message."""
    response = client.get("/")
    assert response.status_code == status.HTTP_200_OK
    assert response.json()["status"] == "ok"
