import base64
import uuid

import httpx
import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.endpoints.evidence_sources import get_github_client
from app.config.settings import settings
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    AccessMode,
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.user import User
from app.models.verification_result import VerificationResult
from app.services.github_client import (
    GitHubClient,
    GitHubMalformedResponseError,
    GitHubNetworkError,
    GitHubOversizedResponseError,
    GitHubRateLimitError,
    GitHubResourceNotFoundError,
    GitHubSecurityError,
    GitHubServerError,
    extract_github_owner_and_repo,
)
from app.services.github_evidence_collector import GitHubEvidenceCollectorService
from main import app


def create_test_user(db: Session, prefix: str = "gh_user") -> User:
    """Helper to persist a test candidate User."""
    unique_id = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{unique_id}@nextround.in",
        name=f"GitHub Candidate {unique_id}",
        hashed_password="hashed_pw_test",
        is_active=True,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_source(
    db: Session,
    user: User,
    source_uri: str = "https://github.com/octocat/Hello-World",
    source_type: EvidenceSourceType = EvidenceSourceType.GITHUB_REPOSITORY,
    access_mode: AccessMode = AccessMode.PUBLIC,
    access_status: EvidenceSourceStatus = EvidenceSourceStatus.NOT_CHECKED,
) -> EvidenceSource:
    """Helper to persist a test EvidenceSource."""
    source = EvidenceSource(
        user_id=user.id,
        source_type=source_type,
        source_uri=source_uri,
        access_mode=access_mode,
        access_status=access_status,
        last_checked_at=None,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


def get_auth_headers(client: TestClient, email: str) -> dict[str, str]:
    """Register and login candidate, returning Authorization Bearer headers."""
    register_payload = {
        "email": email,
        "password": "Password123!",
        "name": "API Candidate",
    }
    client.post("/api/v1/auth/register", json=register_payload)

    login_res = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": "Password123!"},
    )
    assert login_res.status_code == status.HTTP_200_OK
    token = login_res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# 1. URL Extraction & Security Invariant Tests
# =============================================================================


def test_extract_github_owner_and_repo_valid() -> None:
    """Verify owner and repo extraction from valid canonical and .git URLs."""
    owner, repo = extract_github_owner_and_repo("https://github.com/torvalds/linux")
    assert owner == "torvalds"
    assert repo == "linux"

    owner, repo = extract_github_owner_and_repo(
        "https://github.com/fastapi/fastapi.git"
    )
    assert owner == "fastapi"
    assert repo == "fastapi"


def test_extract_github_owner_and_repo_invalid_host() -> None:
    """Verify non-github.com hosts are rejected."""
    with pytest.raises(GitHubSecurityError) as exc_info:
        extract_github_owner_and_repo("https://gitlab.com/owner/repo")
    assert "Only official github.com is supported" in str(exc_info.value)


def test_extract_github_owner_and_repo_path_traversal() -> None:
    """Verify path traversal sequences and invalid segment counts are rejected."""
    with pytest.raises(GitHubSecurityError):
        extract_github_owner_and_repo("https://github.com/owner/../repo")

    with pytest.raises(GitHubSecurityError):
        extract_github_owner_and_repo("https://github.com/single_segment")

    with pytest.raises(GitHubSecurityError):
        extract_github_owner_and_repo("https://github.com/owner/repo/subpath")


def test_extract_github_owner_and_repo_invalid_characters() -> None:
    """Verify illegal characters in owner or repository name are rejected."""
    with pytest.raises(GitHubSecurityError):
        extract_github_owner_and_repo("https://github.com/invalid$owner/repo")

    with pytest.raises(GitHubSecurityError):
        extract_github_owner_and_repo("https://github.com/owner/repo?bad=query")


# =============================================================================
# 2. GitHubClient HTTP Transport Unit Tests
# =============================================================================


def test_github_client_successful_repo_metadata() -> None:
    """Verify GitHubClient parses valid repository metadata JSON."""
    mock_payload = {
        "full_name": "octocat/Hello-World",
        "description": "My first repository on GitHub!",
        "language": "Python",
        "topics": ["test", "octocat"],
        "default_branch": "main",
        "created_at": "2011-01-26T19:01:12Z",
        "updated_at": "2026-01-01T00:00:00Z",
        "pushed_at": "2026-01-02T12:00:00Z",
        "license": {"key": "mit", "name": "MIT License", "spdx_id": "MIT"},
        "fork": False,
        "archived": False,
        "size": 108,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octocat/Hello-World"
        assert request.headers.get("Accept") == "application/vnd.github+json"
        return httpx.Response(200, json=mock_payload)

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = client.get_repository("octocat", "Hello-World")
    assert result["full_name"] == "octocat/Hello-World"
    assert result["language"] == "Python"
    assert result["license"]["spdx_id"] == "MIT"


def test_github_client_successful_readme() -> None:
    """Verify GitHubClient fetches and returns README payload."""
    raw_markdown = "# Hello World\nWelcome to our open source project."
    b64_content = base64.b64encode(raw_markdown.encode("utf-8")).decode("utf-8")
    mock_payload = {
        "name": "README.md",
        "path": "README.md",
        "sha": "4e38e88849b29cb1f185",
        "size": len(raw_markdown),
        "encoding": "base64",
        "content": b64_content,
    }

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/repos/octocat/Hello-World/readme"
        return httpx.Response(200, json=mock_payload)

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = client.get_readme("octocat", "Hello-World")
    assert result is not None
    assert result["name"] == "README.md"
    assert result["sha"] == "4e38e88849b29cb1f185"


def test_github_client_missing_readme_returns_none() -> None:
    """Verify 404 on README endpoint returns None without raising an exception."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    result = client.get_readme("octocat", "Hello-World")
    assert result is None


def test_github_client_404_repo_not_found() -> None:
    """Verify 404 on repository endpoint raises GitHubResourceNotFoundError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GitHubResourceNotFoundError):
        client.get_repository("nonexistent", "repo")


def test_github_client_rate_limited_403_and_429() -> None:
    """Verify 403/429 responses raise GitHubRateLimitError."""

    def handler_403(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "API rate limit exceeded"})

    def handler_429(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, json={"message": "Too Many Requests"})

    client_403 = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler_403))
    )
    with pytest.raises(GitHubRateLimitError):
        client_403.get_repository("octocat", "Hello-World")

    client_429 = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler_429))
    )
    with pytest.raises(GitHubRateLimitError):
        client_429.get_repository("octocat", "Hello-World")


def test_github_client_server_error_500() -> None:
    """Verify 500 status raises GitHubServerError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GitHubServerError):
        client.get_repository("octocat", "Hello-World")


def test_github_client_network_timeout() -> None:
    """Verify connection timeout raises GitHubNetworkError."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectTimeout("Connection timed out")

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GitHubNetworkError):
        client.get_repository("octocat", "Hello-World")


def test_github_client_malformed_json() -> None:
    """Verify non-JSON response raises GitHubMalformedResponseError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text="<html><body>Gateway Error</body></html>")

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GitHubMalformedResponseError):
        client.get_repository("octocat", "Hello-World")


def test_github_client_oversized_response() -> None:
    """Verify oversized response exceeding bounded limits raises GitHubOversizedResponseError."""
    # Configure tiny 50-byte max limit to test enforcement
    oversized_data = {"data": "A" * 100}

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=oversized_data)

    client = GitHubClient(
        max_response_bytes=50,
        http_client=httpx.Client(transport=httpx.MockTransport(handler)),
    )
    with pytest.raises(GitHubOversizedResponseError):
        client.get_repository("octocat", "Hello-World")


def test_github_client_disallows_cross_host_redirect() -> None:
    """Verify redirect to an unauthorized host raises GitHubSecurityError."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            301, headers={"Location": "https://malicious.evil.com/leak"}
        )

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GitHubSecurityError):
        client.get_repository("octocat", "Hello-World")


# =============================================================================
# 3. Collector Service Domain & Idempotency Tests
# =============================================================================


def test_collector_successful_metadata_and_readme(db: Session) -> None:
    """Verify successful collection of repository metadata and README documentation."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    readme_text = "# Test Repo\nComprehensive documentation."
    b64_content = base64.b64encode(readme_text.encode("utf-8")).decode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={
                    "full_name": "octocat/Hello-World",
                    "description": "Public test repository",
                    "language": "Python",
                    "topics": ["fastapi", "sqlalchemy"],
                    "default_branch": "main",
                    "created_at": "2020-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "pushed_at": "2026-01-02T00:00:00Z",
                    "license": {"spdx_id": "Apache-2.0", "name": "Apache 2.0"},
                    "fork": False,
                    "archived": False,
                    "size": 512,
                },
            )
        if request.url.path == "/repos/octocat/Hello-World/readme":
            return httpx.Response(
                200,
                json={
                    "name": "README.md",
                    "path": "README.md",
                    "sha": "blob_sha_123456",
                    "size": len(readme_text),
                    "encoding": "base64",
                    "content": b64_content,
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    response = collector.collect_repository_evidence(user, source.id)

    assert response.evidence_source_id == source.id
    assert response.access_status == EvidenceSourceStatus.AVAILABLE
    assert response.items_collected == 2
    assert response.items_retained == 0
    assert response.total_items == 2
    assert len(response.item_ids) == 2

    # Verify database state
    db.refresh(source)
    assert source.access_status == EvidenceSourceStatus.AVAILABLE
    assert source.last_checked_at is not None

    items = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.evidence_source_id == source.id)
        .all()
    )
    assert len(items) == 2

    meta_item = next(
        i for i in items if i.evidence_type == EvidenceType.REPOSITORY_METADATA
    )
    assert meta_item.observed_data is not None
    assert meta_item.observed_data["primary_language"] == "Python"
    assert meta_item.observed_data["license_spdx_id"] == "Apache-2.0"
    assert meta_item.source_locator == "repository_metadata"

    doc_item = next(i for i in items if i.evidence_type == EvidenceType.DOCUMENTATION)
    assert doc_item.observed_data is not None
    assert doc_item.observed_data["sha"] == "blob_sha_123456"
    assert "# Test Repo" in doc_item.observed_data["content"]
    assert doc_item.source_locator == "README.md"


def test_collector_successful_metadata_without_readme(db: Session) -> None:
    """Verify collection succeeds with 1 item when repository has no README."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={
                    "full_name": "octocat/Hello-World",
                    "description": "Repo without readme",
                    "language": "Go",
                    "topics": [],
                    "default_branch": "master",
                    "created_at": "2021-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "pushed_at": "2026-01-02T00:00:00Z",
                    "license": None,
                },
            )
        # README returns 404
        return httpx.Response(404, json={"message": "Not Found"})

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    response = collector.collect_repository_evidence(user, source.id)

    assert response.items_collected == 1
    assert response.items_retained == 0
    assert response.total_items == 1
    assert response.access_status == EvidenceSourceStatus.AVAILABLE

    db.refresh(source)
    assert source.access_status == EvidenceSourceStatus.AVAILABLE


def test_collector_idempotence_no_duplicates_when_unchanged(db: Session) -> None:
    """Verify repeated collection on an unchanged repository retains existing items without duplicating."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    readme_b64 = base64.b64encode(b"Unchanged README").decode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={
                    "full_name": "octocat/Hello-World",
                    "description": "Stable repo",
                    "language": "Rust",
                    "topics": ["systems"],
                    "default_branch": "main",
                    "created_at": "2022-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "pushed_at": "2026-01-01T00:00:00Z",
                    "license": {"spdx_id": "MIT"},
                },
            )
        if request.url.path == "/repos/octocat/Hello-World/readme":
            return httpx.Response(
                200,
                json={
                    "name": "README.md",
                    "path": "README.md",
                    "sha": "static_sha_abc",
                    "size": 16,
                    "encoding": "base64",
                    "content": readme_b64,
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    # 1. First collection
    first_res = collector.collect_repository_evidence(user, source.id)
    assert first_res.items_collected == 2
    assert first_res.items_retained == 0
    assert first_res.total_items == 2

    # 2. Second collection without repo changes
    second_res = collector.collect_repository_evidence(user, source.id)
    assert second_res.items_collected == 0
    assert second_res.items_retained == 2
    assert second_res.total_items == 2
    assert second_res.item_ids == first_res.item_ids

    # Confirm table row count remained 2
    total_db_items = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.evidence_source_id == source.id)
        .count()
    )
    assert total_db_items == 2


def test_collector_historical_observation_added_on_content_change(db: Session) -> None:
    """Verify updating README creates a new observation while preserving the historical observation."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    current_sha = "initial_sha_111"
    readme_text = "Initial documentation"

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={
                    "full_name": "octocat/Hello-World",
                    "description": "Evolving repo",
                    "language": "TypeScript",
                    "topics": [],
                    "default_branch": "main",
                    "created_at": "2022-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "pushed_at": "2026-01-01T00:00:00Z",
                    "license": None,
                },
            )
        if request.url.path == "/repos/octocat/Hello-World/readme":
            return httpx.Response(
                200,
                json={
                    "name": "README.md",
                    "path": "README.md",
                    "sha": current_sha,
                    "size": len(readme_text),
                    "encoding": "base64",
                    "content": base64.b64encode(readme_text.encode("utf-8")).decode(
                        "utf-8"
                    ),
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    # First collection
    res1 = collector.collect_repository_evidence(user, source.id)
    assert res1.items_collected == 2
    assert res1.total_items == 2

    # Simulate candidate pushing an updated README with a new git blob sha
    current_sha = "updated_sha_222"
    readme_text = "Updated and expanded documentation"

    res2 = collector.collect_repository_evidence(user, source.id)
    assert res2.items_collected == 1  # 1 new README observation
    assert res2.items_retained == 1  # Metadata unchanged
    assert res2.total_items == 3  # Total: initial meta + initial doc + updated doc

    doc_items = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.evidence_source_id == source.id,
            EvidenceItem.evidence_type == EvidenceType.DOCUMENTATION,
        )
        .all()
    )
    assert len(doc_items) == 2
    assert all(d.observed_data is not None for d in doc_items)
    shas = {d.observed_data["sha"] for d in doc_items if d.observed_data is not None}
    assert shas == {"initial_sha_111", "updated_sha_222"}


def test_collector_inaccessible_repo_marks_source_inaccessible(db: Session) -> None:
    """Verify GitHub 404 marks EvidenceSource as INACCESSIBLE, updates last_checked_at, and raises 502."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(404, json={"message": "Not Found"})

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    with pytest.raises(HTTPException) as exc_info:
        collector.collect_repository_evidence(user, source.id)

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert "not found or is private" in exc_info.value.detail

    db.refresh(source)
    assert source.access_status == EvidenceSourceStatus.INACCESSIBLE
    assert source.last_checked_at is not None


def test_collector_rate_limit_updates_last_checked_and_raises_429(db: Session) -> None:
    """Verify rate limit (403/429) records last_checked_at and returns 429."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403, json={"message": "API rate limit exceeded"})

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    with pytest.raises(HTTPException) as exc_info:
        collector.collect_repository_evidence(user, source.id)

    assert exc_info.value.status_code == status.HTTP_429_TOO_MANY_REQUESTS
    assert "rate limit exceeded" in exc_info.value.detail

    db.refresh(source)
    assert source.last_checked_at is not None


def test_collector_server_and_network_error_marks_source_error(db: Session) -> None:
    """Verify server errors and network timeouts mark source as ERROR."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    def handler_500(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="Internal Server Error")

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler_500))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    with pytest.raises(HTTPException) as exc_info:
        collector.collect_repository_evidence(user, source.id)
    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY

    db.refresh(source)
    assert source.access_status == EvidenceSourceStatus.ERROR


def test_collector_unowned_source_rejected_404(db: Session) -> None:
    """Verify attempting to collect for another candidate's source raises 404."""
    user1 = create_test_user(db, prefix="owner")
    user2 = create_test_user(db, prefix="attacker")
    source1 = create_test_source(db, user1)

    collector = GitHubEvidenceCollectorService(db)
    with pytest.raises(HTTPException) as exc_info:
        collector.collect_repository_evidence(user2, source1.id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_collector_non_github_source_rejected_400(db: Session) -> None:
    """Verify non-GITHUB_REPOSITORY sources are rejected."""
    user = create_test_user(db)
    source = create_test_source(
        db,
        user,
        source_uri="https://linkedin.com/in/test-candidate",
        source_type=EvidenceSourceType.LINKEDIN_PROFILE,
    )

    collector = GitHubEvidenceCollectorService(db)
    with pytest.raises(HTTPException) as exc_info:
        collector.collect_repository_evidence(user, source.id)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "only supported for GITHUB_REPOSITORY" in exc_info.value.detail


def test_collector_revoked_source_rejected_400(db: Session) -> None:
    """Verify collection on a REVOKED source is rejected."""
    user = create_test_user(db)
    source = create_test_source(
        db,
        user,
        access_status=EvidenceSourceStatus.REVOKED,
    )

    collector = GitHubEvidenceCollectorService(db)
    with pytest.raises(HTTPException) as exc_info:
        collector.collect_repository_evidence(user, source.id)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "revoked" in exc_info.value.detail


def test_collector_readme_bounded_size(db: Session) -> None:
    """Verify massive README files are safely truncated to configured limits."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    # Generate a 100 KB README (exceeds default 32 KB bound)
    massive_text = "A" * (100 * 1024)
    b64_content = base64.b64encode(massive_text.encode("utf-8")).decode("utf-8")

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={
                    "full_name": "octocat/Hello-World",
                    "description": "Massive doc repo",
                    "language": "Markdown",
                    "topics": [],
                    "default_branch": "main",
                    "created_at": "2022-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "pushed_at": "2026-01-01T00:00:00Z",
                    "license": None,
                },
            )
        if request.url.path == "/repos/octocat/Hello-World/readme":
            return httpx.Response(
                200,
                json={
                    "name": "README.md",
                    "path": "README.md",
                    "sha": "massive_sha_999",
                    "size": len(massive_text),
                    "encoding": "base64",
                    "content": b64_content,
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    response = collector.collect_repository_evidence(user, source.id)
    assert response.items_collected == 2

    doc_item = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.evidence_source_id == source.id,
            EvidenceItem.evidence_type == EvidenceType.DOCUMENTATION,
        )
        .one()
    )
    assert doc_item.observed_data is not None
    assert doc_item.observed_data["truncated"] is True
    assert len(doc_item.observed_data["content"]) == settings.GITHUB_MAX_README_BYTES
    assert doc_item.observed_data["size_bytes"] == len(massive_text)


def test_collector_zero_verification_results_created(db: Session) -> None:
    """Verify evidence collection strictly gathers observations and generates ZERO verification results."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    vr_count_before = db.query(VerificationResult).count()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={
                    "full_name": "octocat/Hello-World",
                    "description": "Check zero VR",
                    "language": "C++",
                    "topics": [],
                    "default_branch": "main",
                    "created_at": "2022-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "pushed_at": "2026-01-01T00:00:00Z",
                    "license": None,
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    collector.collect_repository_evidence(user, source.id)

    vr_count_after = db.query(VerificationResult).count()
    assert vr_count_before == vr_count_after == 0


# =============================================================================
# 4. API Endpoints Integration Tests
# =============================================================================


def test_api_collect_unauthenticated_rejected_401(client: TestClient) -> None:
    """Verify unauthenticated POST /api/v1/evidence-sources/{id}/collect returns 401."""
    random_id = uuid.uuid4()
    res = client.post(f"/api/v1/evidence-sources/{random_id}/collect")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_collect_successful_workflow(client: TestClient, db: Session) -> None:
    """Verify authenticated POST /api/v1/evidence-sources/{id}/collect executes collection workflow."""
    email = f"gh_api_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)

    user = db.query(User).filter(User.email == email).one()
    source = create_test_source(
        db, user, source_uri="https://github.com/octocat/Spoon-Knife"
    )

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Spoon-Knife":
            return httpx.Response(
                200,
                json={
                    "full_name": "octocat/Spoon-Knife",
                    "description": "API test repo",
                    "language": "HTML",
                    "topics": [],
                    "default_branch": "main",
                    "created_at": "2022-01-01T00:00:00Z",
                    "updated_at": "2026-01-01T00:00:00Z",
                    "pushed_at": "2026-01-01T00:00:00Z",
                    "license": {"spdx_id": "MIT"},
                },
            )
        if request.url.path == "/repos/octocat/Spoon-Knife/readme":
            return httpx.Response(
                200,
                json={
                    "name": "README.md",
                    "path": "README.md",
                    "sha": "spoon_knife_sha",
                    "size": 18,
                    "encoding": "base64",
                    "content": base64.b64encode(b"Spoon knife readme").decode("utf-8"),
                },
            )
        return httpx.Response(404, json={"message": "Not Found"})

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    app.dependency_overrides[get_github_client] = lambda: mock_client

    try:
        res = client.post(
            f"/api/v1/evidence-sources/{source.id}/collect",
            headers=headers,
        )
        assert res.status_code == status.HTTP_200_OK
        data = res.json()
        assert data["evidence_source_id"] == str(source.id)
        assert data["access_status"] == "AVAILABLE"
        assert data["items_collected"] == 2
        assert data["items_retained"] == 0
        assert data["total_items"] == 2
        assert len(data["item_ids"]) == 2
    finally:
        app.dependency_overrides.pop(get_github_client, None)


def test_api_collect_unowned_source_returns_404(
    client: TestClient, db: Session
) -> None:
    """Verify attempting to collect another candidate's evidence source returns 404."""
    email1 = f"gh_api_{uuid.uuid4().hex[:6]}@nextround.in"
    email2 = f"gh_api_{uuid.uuid4().hex[:6]}@nextround.in"
    _ = get_auth_headers(client, email1)
    headers2 = get_auth_headers(client, email2)

    user1 = db.query(User).filter(User.email == email1).one()
    source1 = create_test_source(db, user1)

    res = client.post(
        f"/api/v1/evidence-sources/{source1.id}/collect",
        headers=headers2,
    )
    assert res.status_code == status.HTTP_404_NOT_FOUND
    assert "Evidence source not found" in res.json()["detail"]


# =============================================================================
# 5. Targeted Correctness Audit Edge-Case Tests
# =============================================================================


def test_extract_github_owner_and_repo_requires_https() -> None:
    """Verify non-HTTPS scheme is rejected by extract_github_owner_and_repo."""
    with pytest.raises(GitHubSecurityError, match="HTTPS"):
        extract_github_owner_and_repo("http://github.com/owner/repo")


def test_github_client_enforces_https_base_url() -> None:
    """Verify GitHubClient rejects non-HTTPS base URL before sending requests."""
    mock_transport = httpx.MockTransport(lambda req: httpx.Response(200, json={}))
    client = GitHubClient(
        base_url="http://api.github.com",
        http_client=httpx.Client(transport=mock_transport),
    )
    with pytest.raises(GitHubSecurityError, match="HTTPS"):
        client.get_repository("owner", "repo")


def test_github_client_safe_relative_redirect() -> None:
    """Verify safe relative redirect on official host is resolved and followed."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/owner/old-name":
            return httpx.Response(
                301,
                headers={"Location": "/repos/owner/new-name"},
            )
        if request.url.path == "/repos/owner/new-name":
            return httpx.Response(200, json={"full_name": "owner/new-name"})
        return httpx.Response(404)

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    data = client.get_repository("owner", "old-name")
    assert data["full_name"] == "owner/new-name"


def test_github_client_rejects_non_https_redirect() -> None:
    """Verify redirect to non-HTTPS scheme on same host is rejected."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            301,
            headers={"Location": "http://api.github.com/repos/owner/new-name"},
        )

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GitHubSecurityError, match="non-HTTPS"):
        client.get_repository("owner", "repo")


def test_github_client_rejects_multiple_redirects() -> None:
    """Verify multiple redirects (redirect chaining) are rejected."""

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/owner/r1":
            return httpx.Response(301, headers={"Location": "/repos/owner/r2"})
        if request.url.path == "/repos/owner/r2":
            return httpx.Response(301, headers={"Location": "/repos/owner/r3"})
        return httpx.Response(200, json={})

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GitHubSecurityError, match="Multiple redirects"):
        client.get_repository("owner", "r1")


def test_github_client_streamed_chunked_oversized_response_without_content_length() -> (
    None
):
    """Verify streaming response exceeding 512 KB without Content-Length is rejected."""
    excess_bytes = b"X" * (settings.GITHUB_MAX_RESPONSE_BYTES + 4096)

    def handler(request: httpx.Request) -> httpx.Response:
        # No Content-Length header provided
        return httpx.Response(200, content=excess_bytes)

    client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    with pytest.raises(GitHubOversizedResponseError):
        client.get_repository("owner", "repo")


def test_collector_readme_corrupted_base64_handled_safely(db: Session) -> None:
    """Verify corrupted base64 in README payload produces empty content without crashing."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={"full_name": "octocat/Hello-World", "language": "Python"},
            )
        if request.url.path == "/repos/octocat/Hello-World/readme":
            return httpx.Response(
                200,
                json={
                    "name": "README.md",
                    "path": "README.md",
                    "sha": "bad_b64_sha",
                    "size": 100,
                    "encoding": "base64",
                    "content": "%%%not-base-64-corrupted%%%",
                },
            )
        return httpx.Response(404)

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)
    res = collector.collect_repository_evidence(user, source.id)

    assert res.items_collected == 2
    doc_item = (
        db.query(EvidenceItem)
        .filter(
            EvidenceItem.evidence_source_id == source.id,
            EvidenceItem.evidence_type == EvidenceType.DOCUMENTATION,
        )
        .one()
    )
    assert doc_item.observed_data is not None
    assert doc_item.observed_data["content"] == ""
    assert doc_item.observed_data["sha"] == "bad_b64_sha"


def test_collector_readme_server_error_marks_source_error_and_raises_502(
    db: Session,
) -> None:
    """Verify upstream 500 error on README retrieval marks source as ERROR and leaves 0 observations."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={"full_name": "octocat/Hello-World", "language": "Python"},
            )
        if request.url.path == "/repos/octocat/Hello-World/readme":
            return httpx.Response(500, json={"message": "Internal Server Error"})
        return httpx.Response(404)

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    with pytest.raises(HTTPException) as exc_info:
        collector.collect_repository_evidence(user, source.id)

    assert exc_info.value.status_code == status.HTTP_502_BAD_GATEWAY
    assert source.access_status == EvidenceSourceStatus.ERROR
    assert source.last_checked_at is not None

    items = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.evidence_source_id == source.id)
        .all()
    )
    assert len(items) == 0


def test_collector_readme_timeout_marks_source_error_and_raises_504(
    db: Session,
) -> None:
    """Verify timeout on README retrieval marks source as ERROR and raises 504."""
    user = create_test_user(db)
    source = create_test_source(db, user)

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={"full_name": "octocat/Hello-World", "language": "Python"},
            )
        if request.url.path == "/repos/octocat/Hello-World/readme":
            raise httpx.ReadTimeout("Read timed out")
        return httpx.Response(404)

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    with pytest.raises(HTTPException) as exc_info:
        collector.collect_repository_evidence(user, source.id)

    assert exc_info.value.status_code == status.HTTP_504_GATEWAY_TIMEOUT
    assert source.access_status == EvidenceSourceStatus.ERROR
    assert source.last_checked_at is not None


def test_collector_persistence_failure_rolls_back_cleanly(db: Session) -> None:
    """Verify persistence failure rolls back session, preserves prior state, and raises 500."""
    user = create_test_user(db)
    source = create_test_source(db, user)
    source_id = source.id
    source.access_status = EvidenceSourceStatus.NOT_CHECKED
    db.commit()

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/repos/octocat/Hello-World":
            return httpx.Response(
                200,
                json={"full_name": "octocat/Hello-World", "language": "Python"},
            )
        return httpx.Response(404)

    mock_client = GitHubClient(
        http_client=httpx.Client(transport=httpx.MockTransport(handler))
    )
    collector = GitHubEvidenceCollectorService(db, github_client=mock_client)

    # Monkeypatch commit to fail on the persistence step
    original_commit = db.commit
    fail_commit = True

    def mock_commit() -> None:
        if fail_commit:
            raise RuntimeError("Simulated DB connection drop on commit")
        original_commit()

    db.commit = mock_commit  # type: ignore[method-assign]
    try:
        with pytest.raises(HTTPException) as exc_info:
            collector.collect_repository_evidence(user, source_id)
        assert exc_info.value.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    finally:
        fail_commit = False
        db.commit = original_commit  # type: ignore[method-assign]

    # Verify database state after rollback
    db.expire_all()
    items = (
        db.query(EvidenceItem)
        .filter(EvidenceItem.evidence_source_id == source_id)
        .all()
    )
    assert len(items) == 0
