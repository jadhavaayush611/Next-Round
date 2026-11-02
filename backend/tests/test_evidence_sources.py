import uuid

from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.evidence_source import (
    EvidenceSource,
    EvidenceSourceType,
)
from app.models.user import User


def register_user(
    client: TestClient, email: str, name: str = "Test User"
) -> tuple[str, dict[str, str]]:
    """Helper to register, login, and obtain authorization headers and user data."""
    user_data = {
        "email": email,
        "password": "Password123!",
        "name": name,
    }
    client.post("/api/v1/auth/register", json=user_data)
    login_data = {"username": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/login", data=login_data)
    token = res.json()["access_token"]
    headers = {"Authorization": f"Bearer {token}"}
    return token, headers


def test_register_evidence_source_github_repo_success(
    client: TestClient, db: Session
) -> None:
    """Verifies successful registration and normalization of a GitHub repository evidence source."""
    _, headers = register_user(client, "gh_user@nextround.in", "GitHub Candidate")

    payload = {
        "source_type": "GITHUB_REPOSITORY",
        "source_uri": "https://www.github.com/torvalds/linux.git/",
        "access_mode": "PUBLIC",
    }
    response = client.post("/api/v1/evidence-sources", headers=headers, json=payload)
    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()

    assert data["source_type"] == "GITHUB_REPOSITORY"
    # Normalization stripped www, trailing slash, and .git
    assert data["source_uri"] == "https://github.com/torvalds/linux"
    assert data["access_mode"] == "PUBLIC"
    # Verification status defaults to NOT_CHECKED; last_checked_at is None
    assert data["access_status"] == "NOT_CHECKED"
    assert data["last_checked_at"] is None
    assert "id" in data
    assert "created_at" in data


def test_register_evidence_source_all_supported_types(
    client: TestClient, db: Session
) -> None:
    """Verifies that all supported source types can be registered with valid URLs."""
    _, headers = register_user(client, "multi_type@nextround.in", "Multi Dev")

    sources = [
        (
            "GITHUB_PROFILE",
            "https://github.com/torvalds",
            "https://github.com/torvalds",
        ),
        (
            "LINKEDIN_PROFILE",
            "https://www.linkedin.com/in/linustorvalds/",
            "https://www.linkedin.com/in/linustorvalds",
        ),
        (
            "PORTFOLIO",
            "https://linustorvalds.dev/projects",
            "https://linustorvalds.dev/projects",
        ),
        (
            "ASSESSMENT",
            "https://assessments.internal.net/test/123",
            "https://assessments.internal.net/test/123",
        ),
        (
            "OTHER",
            "https://gitlab.com/group/subgroup/project",
            "https://gitlab.com/group/subgroup/project",
        ),
    ]

    for source_type, raw_uri, expected_normalized in sources:
        res = client.post(
            "/api/v1/evidence-sources",
            headers=headers,
            json={"source_type": source_type, "source_uri": raw_uri},
        )
        assert res.status_code == status.HTTP_201_CREATED
        body = res.json()
        assert body["source_type"] == source_type
        assert body["source_uri"] == expected_normalized
        assert body["access_status"] == "NOT_CHECKED"


def test_url_normalization_rules(client: TestClient, db: Session) -> None:
    """Verifies default port removal, fragment stripping, and scheme/host lowercasing."""
    _, headers = register_user(client, "norm_rules@nextround.in", "Norm Candidate")

    # 1. Strips fragment (#readme)
    res1 = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/pallets/flask#readme",
        },
    )
    assert res1.status_code == status.HTTP_201_CREATED
    assert res1.json()["source_uri"] == "https://github.com/pallets/flask"

    # 2. Strips default port 443
    res2 = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "PORTFOLIO",
            "source_uri": "https://candidate.portfolio.org:443/showcase/",
        },
    )
    assert res2.status_code == status.HTTP_201_CREATED
    assert res2.json()["source_uri"] == "https://candidate.portfolio.org/showcase"

    # 3. Lowercases scheme and domain while preserving path casing
    res3 = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "HTTPS://GITHUB.COM/FastAPI/FastAPI",
        },
    )
    assert res3.status_code == status.HTTP_201_CREATED
    assert res3.json()["source_uri"] == "https://github.com/FastAPI/FastAPI"

    # 4. Resolves dot segments in paths (normpath)
    res4 = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "PORTFOLIO",
            "source_uri": "https://candidate.portfolio.org/a/b/../showcase/",
        },
    )
    assert res4.status_code == status.HTTP_201_CREATED
    assert res4.json()["source_uri"] == "https://candidate.portfolio.org/a/showcase"


def test_reject_invalid_and_unsafe_urls(client: TestClient, db: Session) -> None:
    """Verifies that malformed, unsupported, credentialed, and unsafe URLs are rejected with HTTP 422."""
    _, headers = register_user(client, "unsafe_urls@nextround.in", "Unsafe Tester")

    bad_payloads = [
        # Embedded credentials (userinfo)
        {
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://user:password@github.com/owner/repo",
        },
        # Unsupported schemes
        {
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "ftp://github.com/owner/repo",
        },
        {
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "file:///etc/passwd",
        },
        {
            "source_type": "OTHER",
            "source_uri": "javascript:alert(1)",
        },
        # Localhost / loopback / private IP SSRF-risk addresses
        {
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://localhost/owner/repo",
        },
        {
            "source_type": "PORTFOLIO",
            "source_uri": "https://127.0.0.1/portfolio",
        },
        {
            "source_type": "PORTFOLIO",
            "source_uri": "https://192.168.1.1/portfolio",
        },
        {
            "source_type": "PORTFOLIO",
            "source_uri": "https://10.0.0.1/portfolio",
        },
        # Unusual IP formats and bracketed IPv6 loopbacks
        {
            "source_type": "PORTFOLIO",
            "source_uri": "https://[::1]/portfolio",
        },
        {
            "source_type": "PORTFOLIO",
            "source_uri": "https://[::ffff:127.0.0.1]/portfolio",
        },
        {
            "source_type": "PORTFOLIO",
            "source_uri": "https://0177.0.0.1/portfolio",
        },
        {
            "source_type": "PORTFOLIO",
            "source_uri": "https://2130706433/portfolio",
        },
        # Malformed URLs
        {
            "source_type": "PORTFOLIO",
            "source_uri": "not_a_valid_url",
        },
        {
            "source_type": "PORTFOLIO",
            "source_uri": "https://",
        },
        # Mismatched domain for GITHUB_REPOSITORY
        {
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://gitlab.com/owner/repo",
        },
        # Incomplete repo path for GITHUB_REPOSITORY
        {
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/onlyowner",
        },
        {
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/",
        },
        # Reserved path for GITHUB_PROFILE
        {
            "source_type": "GITHUB_PROFILE",
            "source_uri": "https://github.com/features",
        },
        # Mismatched domain for LINKEDIN_PROFILE
        {
            "source_type": "LINKEDIN_PROFILE",
            "source_uri": "https://twitter.com/in/johndoe",
        },
    ]

    for payload in bad_payloads:
        res = client.post("/api/v1/evidence-sources", headers=headers, json=payload)
        assert (
            res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        ), f"Expected 422 for payload {payload}, got {res.status_code}: {res.text}"


def test_cannot_forge_verification_status_on_creation(
    client: TestClient, db: Session
) -> None:
    """Verifies that candidates cannot pass access_status or last_checked_at to assert verification."""
    _, headers = register_user(client, "anti_forge@nextround.in", "Honest Dev")

    # Attempt to inject access_status=AVAILABLE and last_checked_at
    payload = {
        "source_type": "GITHUB_REPOSITORY",
        "source_uri": "https://github.com/psf/black",
        "access_status": "AVAILABLE",
        "last_checked_at": "2026-10-12T10:00:00Z",
    }
    res = client.post("/api/v1/evidence-sources", headers=headers, json=payload)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    # Server manages status and timestamps: strictly NOT_CHECKED and None
    assert data["access_status"] == "NOT_CHECKED"
    assert data["last_checked_at"] is None


def test_revoke_evidence_source(client: TestClient, db: Session) -> None:
    """Verifies that a candidate can revoke an evidence source via dedicated endpoint or PATCH."""
    _, headers = register_user(client, "revoke_user@nextround.in", "Revoke User")

    # 1. Register source
    create_res = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/django/django",
        },
    )
    assert create_res.status_code == status.HTTP_201_CREATED
    source_id = create_res.json()["id"]

    # 2. Revoke via dedicated endpoint
    revoke_res = client.patch(
        f"/api/v1/evidence-sources/{source_id}/revoke", headers=headers
    )
    assert revoke_res.status_code == status.HTTP_200_OK
    assert revoke_res.json()["access_status"] == "REVOKED"

    # 3. Register second source and revoke via PATCH body
    create_res2 = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "GITHUB_PROFILE",
            "source_uri": "https://github.com/octocat",
        },
    )
    source_id2 = create_res2.json()["id"]

    patch_res = client.patch(
        f"/api/v1/evidence-sources/{source_id2}",
        headers=headers,
        json={"access_status": "REVOKED"},
    )
    assert patch_res.status_code == status.HTTP_200_OK
    assert patch_res.json()["access_status"] == "REVOKED"


def test_reject_unauthorized_status_updates(client: TestClient, db: Session) -> None:
    """Verifies that candidates cannot update access_status to AVAILABLE, ERROR, or INACCESSIBLE."""
    _, headers = register_user(client, "status_cheat@nextround.in", "Cheater User")

    create_res = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/numpy/numpy",
        },
    )
    source_id = create_res.json()["id"]

    for forbidden_status in ["AVAILABLE", "INACCESSIBLE", "ERROR", "NOT_CHECKED"]:
        res = client.patch(
            f"/api/v1/evidence-sources/{source_id}",
            headers=headers,
            json={"access_status": forbidden_status},
        )
        assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
        assert "only revoke access" in res.text


def test_ownership_enforcement_and_cross_user_isolation(
    client: TestClient, db: Session
) -> None:
    """Verifies that candidates cannot view or revoke evidence sources owned by other users."""
    _, headers1 = register_user(client, "victim@nextround.in", "Victim User")
    _, headers2 = register_user(client, "attacker@nextround.in", "Attacker User")

    # User 1 registers a source
    res1 = client.post(
        "/api/v1/evidence-sources",
        headers=headers1,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/pandas-dev/pandas",
        },
    )
    assert res1.status_code == status.HTTP_201_CREATED
    source_id = res1.json()["id"]

    # User 2 attempts to retrieve User 1's source -> 404
    get_res = client.get(f"/api/v1/evidence-sources/{source_id}", headers=headers2)
    assert get_res.status_code == status.HTTP_404_NOT_FOUND

    # User 2 attempts to revoke User 1's source -> 404
    revoke_res = client.patch(
        f"/api/v1/evidence-sources/{source_id}/revoke", headers=headers2
    )
    assert revoke_res.status_code == status.HTTP_404_NOT_FOUND

    # User 2 listing does not include User 1's source
    list_res = client.get("/api/v1/evidence-sources", headers=headers2)
    assert list_res.status_code == status.HTTP_200_OK
    assert len(list_res.json()) == 0


def test_duplicate_registration_handling(client: TestClient, db: Session) -> None:
    """Verifies that duplicate registrations for the same candidate are rejected with HTTP 409."""
    _, headers1 = register_user(client, "dup_user1@nextround.in", "User One")
    _, headers2 = register_user(client, "dup_user2@nextround.in", "User Two")

    # 1. User 1 registers a source
    res1 = client.post(
        "/api/v1/evidence-sources",
        headers=headers1,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/scikit-learn/scikit-learn",
        },
    )
    assert res1.status_code == status.HTTP_201_CREATED

    # 2. User 1 registers the same URL with different formatting -> 409 Conflict
    dup_res = client.post(
        "/api/v1/evidence-sources",
        headers=headers1,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://www.github.com/scikit-learn/scikit-learn.git/",
        },
    )
    assert dup_res.status_code == status.HTTP_409_CONFLICT
    assert "already registered" in dup_res.json()["detail"]

    # 3. User 2 registers the exact same public repository -> 201 Created (allowed for different users)
    other_user_res = client.post(
        "/api/v1/evidence-sources",
        headers=headers2,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/scikit-learn/scikit-learn",
        },
    )
    assert other_user_res.status_code == status.HTTP_201_CREATED

    # 4. User 1 revokes the source, then re-registers -> re-activated to NOT_CHECKED
    source_id1 = res1.json()["id"]
    client.patch(f"/api/v1/evidence-sources/{source_id1}/revoke", headers=headers1)

    re_register_res = client.post(
        "/api/v1/evidence-sources",
        headers=headers1,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/scikit-learn/scikit-learn",
        },
    )
    assert re_register_res.status_code == status.HTTP_201_CREATED
    assert re_register_res.json()["access_status"] == "NOT_CHECKED"


def test_list_and_filter_evidence_sources(client: TestClient, db: Session) -> None:
    """Verifies listing evidence sources and filtering by source_type and access_status."""
    _, headers = register_user(client, "filter_user@nextround.in", "Filter Dev")

    # Create 3 sources
    res_repo = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/pytest-dev/pytest",
        },
    )
    assert res_repo.status_code == status.HTTP_201_CREATED

    res_prof = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "GITHUB_PROFILE",
            "source_uri": "https://github.com/holoviews",
        },
    )
    assert res_prof.status_code == status.HTTP_201_CREATED
    res_port = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "PORTFOLIO",
            "source_uri": "https://myportfolio.io",
        },
    )

    # Revoke the portfolio
    port_id = res_port.json()["id"]
    client.patch(f"/api/v1/evidence-sources/{port_id}/revoke", headers=headers)

    # List all
    all_res = client.get("/api/v1/evidence-sources", headers=headers)
    assert all_res.status_code == status.HTTP_200_OK
    assert len(all_res.json()) == 3

    # Filter by source_type=GITHUB_REPOSITORY
    repo_res = client.get(
        "/api/v1/evidence-sources?source_type=GITHUB_REPOSITORY", headers=headers
    )
    assert repo_res.status_code == status.HTTP_200_OK
    assert len(repo_res.json()) == 1
    assert repo_res.json()[0]["source_type"] == "GITHUB_REPOSITORY"

    # Filter by access_status=REVOKED
    revoked_res = client.get(
        "/api/v1/evidence-sources?access_status=REVOKED", headers=headers
    )
    assert revoked_res.status_code == status.HTTP_200_OK
    assert len(revoked_res.json()) == 1
    assert revoked_res.json()[0]["access_status"] == "REVOKED"

    # Filter by access_status=NOT_CHECKED
    not_checked_res = client.get(
        "/api/v1/evidence-sources?access_status=NOT_CHECKED", headers=headers
    )
    assert not_checked_res.status_code == status.HTTP_200_OK
    assert len(not_checked_res.json()) == 2


def test_no_hard_delete_endpoint(client: TestClient, db: Session) -> None:
    """Verifies that DELETE is not allowed on evidence sources, preserving historical records."""
    _, headers = register_user(client, "nodelete@nextround.in", "Preserve Dev")

    res = client.post(
        "/api/v1/evidence-sources",
        headers=headers,
        json={
            "source_type": "GITHUB_REPOSITORY",
            "source_uri": "https://github.com/curl/curl",
        },
    )
    source_id = res.json()["id"]

    # DELETE must return 405 Method Not Allowed
    del_res = client.delete(f"/api/v1/evidence-sources/{source_id}", headers=headers)
    assert del_res.status_code == status.HTTP_405_METHOD_NOT_ALLOWED


def test_unauthenticated_requests_rejected(client: TestClient) -> None:
    """Verifies that all evidence source endpoints require authentication."""
    dummy_id = uuid.uuid4()
    assert (
        client.get("/api/v1/evidence-sources").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.post(
            "/api/v1/evidence-sources",
            json={
                "source_type": "GITHUB_REPOSITORY",
                "source_uri": "https://github.com/foo/bar",
            },
        ).status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.get(f"/api/v1/evidence-sources/{dummy_id}").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.patch(f"/api/v1/evidence-sources/{dummy_id}/revoke").status_code
        == status.HTTP_401_UNAUTHORIZED
    )


def test_database_cascade_on_user_deletion(db: Session) -> None:
    """Verifies that deleting a user from the database cascades to their evidence sources."""
    user = User(
        email=f"cascade_user_{uuid.uuid4().hex[:6]}@nextround.in",
        name="Cascade User",
        hashed_password="pw",
    )
    db.add(user)
    db.commit()

    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri="https://github.com/git/git",
    )
    db.add(source)
    db.commit()

    source_id = source.id

    # Verify source exists
    assert db.get(EvidenceSource, source_id) is not None

    # Delete user
    db.delete(user)
    db.commit()

    # Verify source was cascade-deleted
    assert db.get(EvidenceSource, source_id) is None
