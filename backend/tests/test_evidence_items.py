import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    AccessMode,
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.user import User
from app.repositories.evidence_item import EvidenceItemRepository
from app.schemas.evidence_item import EvidenceItemCreate
from app.services.evidence_item_service import EvidenceItemService


def create_test_user(db: Session, prefix: str = "item_user") -> User:
    """Helper to create and persist a test User."""
    unique_id = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{unique_id}@nextround.in",
        name=f"User {unique_id}",
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
    source_type: EvidenceSourceType = EvidenceSourceType.GITHUB_REPOSITORY,
    source_uri: str | None = None,
    access_status: EvidenceSourceStatus = EvidenceSourceStatus.AVAILABLE,
) -> EvidenceSource:
    """Helper to create and persist a test EvidenceSource."""
    if source_uri is None:
        source_uri = f"https://github.com/nextround/{uuid.uuid4().hex[:8]}"
    source = EvidenceSource(
        user_id=user.id,
        source_type=source_type,
        source_uri=source_uri,
        access_mode=AccessMode.PUBLIC,
        access_status=access_status,
    )
    db.add(source)
    db.commit()
    db.refresh(source)
    return source


# =========================================================================
# 1. Internal Repository & Service: Creation and Retrieval
# =========================================================================


def test_create_and_retrieve_evidence_item_service(db: Session) -> None:
    """Verifies creating and retrieving an EvidenceItem with full attributes via internal service."""
    user = create_test_user(db, "service_user")
    source = create_test_source(db, user)
    service = EvidenceItemService(db)

    historical_time = datetime(2026, 9, 15, 10, 30, tzinfo=UTC)
    payload = EvidenceItemCreate(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.REPOSITORY_METADATA,
        description="Repository primary language detected as Python with 95% ratio.",
        observed_data={
            "primary_language": "Python",
            "language_ratio": 0.95,
            "stars": 12,
        },
        source_locator="languages.json",
        observed_at=historical_time,
    )

    created = service.create_evidence_item(payload, user=user)
    assert created.id is not None
    assert created.evidence_source_id == source.id
    assert created.evidence_type == EvidenceType.REPOSITORY_METADATA
    assert created.description == payload.description
    assert created.observed_data == payload.observed_data
    assert created.source_locator == "languages.json"
    # Preserves distinction between observed_at and server-managed created_at
    assert created.observed_at == historical_time
    assert created.created_at is not None
    assert created.created_at != historical_time

    # Retrieve by ID
    fetched = service.get_evidence_item(created.id, user=user)
    assert fetched.id == created.id
    assert fetched.description == created.description
    assert fetched.observed_data == created.observed_data


def test_repository_crud_and_queries(db: Session) -> None:
    """Verifies EvidenceItemRepository direct CRUD, source listing, type filtering, and counting."""
    user = create_test_user(db, "repo_user")
    source = create_test_source(db, user)
    repo = EvidenceItemRepository(db)

    item1 = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Async database session setup in backend/app/db/session.py",
        source_locator="backend/app/db/session.py#L1-L30",
    )
    item2 = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.DOCUMENTATION,
        description="Architecture documentation detailing pipeline and database design",
        source_locator="docs/architecture.md",
    )
    repo.create(item1)
    repo.create(item2)

    # Count
    assert repo.count_by_source(source.id) == 2

    # List all for source
    items = repo.list_by_source(source.id)
    assert len(items) == 2

    # Filter by type
    code_items = repo.list_by_source(
        source.id, evidence_type=EvidenceType.CODE_ARTIFACT
    )
    assert len(code_items) == 1
    assert code_items[0].evidence_type == EvidenceType.CODE_ARTIFACT

    doc_items = repo.list_by_source(source.id, evidence_type=EvidenceType.DOCUMENTATION)
    assert len(doc_items) == 1
    assert doc_items[0].evidence_type == EvidenceType.DOCUMENTATION

    # List by user
    user_items = repo.list_by_user(user.id)
    assert len(user_items) == 2


def test_service_list_items_for_user_across_multiple_sources(db: Session) -> None:
    """Verifies that EvidenceItemService can aggregate all evidence items for a user across multiple sources."""
    user = create_test_user(db, "multi_source_user")
    source1 = create_test_source(db, user, source_uri="https://github.com/cand/repo1")
    source2 = create_test_source(db, user, source_uri="https://github.com/cand/repo2")
    service = EvidenceItemService(db)

    service.create_evidence_item(
        EvidenceItemCreate(
            evidence_source_id=source1.id,
            evidence_type=EvidenceType.CONTRIBUTION_ACTIVITY,
            description="Merged 15 pull requests in Q2 2026",
        ),
        user=user,
    )
    service.create_evidence_item(
        EvidenceItemCreate(
            evidence_source_id=source2.id,
            evidence_type=EvidenceType.CODE_ARTIFACT,
            description="Implemented FastAPI endpoints with dependency injection",
        ),
        user=user,
    )

    all_user_items = service.list_items_for_user(user)
    assert len(all_user_items) == 2

    contribution_items = service.list_items_for_user(
        user, evidence_type=EvidenceType.CONTRIBUTION_ACTIVITY
    )
    assert len(contribution_items) == 1
    assert contribution_items[0].evidence_type == EvidenceType.CONTRIBUTION_ACTIVITY


# =========================================================================
# 2. Schema Validation: Enums, Required Fields, Minimal Observations
# =========================================================================


def test_all_contract_evidence_types_supported() -> None:
    """Verifies that all 6 contract-defined evidence types are valid and accepted."""
    source_id = uuid.uuid4()
    valid_types = [
        EvidenceType.REPOSITORY_METADATA,
        EvidenceType.CODE_ARTIFACT,
        EvidenceType.DOCUMENTATION,
        EvidenceType.CONTRIBUTION_ACTIVITY,
        EvidenceType.ASSESSMENT_RESULT,
        EvidenceType.OTHER,
    ]

    for et in valid_types:
        schema = EvidenceItemCreate(
            evidence_source_id=source_id,
            evidence_type=et,
            description=f"Valid observation for {et.value}",
        )
        assert schema.evidence_type == et


def test_invalid_evidence_type_rejected() -> None:
    """Verifies that undefined enum values are rejected with ValidationError."""
    with pytest.raises(ValidationError):
        EvidenceItemCreate(
            evidence_source_id=uuid.uuid4(),
            evidence_type="INVALID_NON_EXISTENT_TYPE",  # type: ignore[arg-type]
            description="Some observation",
        )


def test_description_required_and_cannot_be_empty() -> None:
    """Verifies that empty or whitespace-only descriptions are rejected."""
    source_id = uuid.uuid4()

    with pytest.raises(ValidationError) as exc_info:
        EvidenceItemCreate(
            evidence_source_id=source_id,
            evidence_type=EvidenceType.OTHER,
            description="   ",
        )
    assert "Description cannot be empty" in str(exc_info.value)

    with pytest.raises(ValidationError):
        EvidenceItemCreate(
            evidence_source_id=source_id,
            evidence_type=EvidenceType.OTHER,
            description="",
        )


def test_structured_data_minimal_invariants() -> None:
    """
    Verifies that structured observations must remain minimal facts
    and reject oversized payloads (e.g., attempting to clone whole repos/profiles).
    """
    source_id = uuid.uuid4()

    # Valid minimal facts
    valid_data = {"key_dependencies": ["fastapi", "pydantic", "sqlalchemy"]}
    item = EvidenceItemCreate(
        evidence_source_id=source_id,
        evidence_type=EvidenceType.REPOSITORY_METADATA,
        description="Dependency manifest inspection",
        observed_data=valid_data,
    )
    assert item.observed_data == valid_data

    # Reject non-serializable objects
    class Unserializable:
        pass

    with pytest.raises(ValidationError) as exc_unserializable:
        EvidenceItemCreate(
            evidence_source_id=source_id,
            evidence_type=EvidenceType.REPOSITORY_METADATA,
            description="Unserializable object test",
            observed_data={"bad": Unserializable()},  # type: ignore[dict-item]
        )
    assert "JSON-serializable" in str(exc_unserializable.value)

    # Reject giant payload (> 64 KB)
    oversized_data = {"repo_files": {"dump": "a" * 70000}}
    with pytest.raises(ValidationError) as exc_oversized:
        EvidenceItemCreate(
            evidence_source_id=source_id,
            evidence_type=EvidenceType.CODE_ARTIFACT,
            description="Attempt to store complete repo contents",
            observed_data=oversized_data,
        )
    assert "exceeds maximum allowed size" in str(exc_oversized.value)


def test_observed_at_timezone_handling() -> None:
    """Verifies that naive datetimes and custom timezone datetimes are safely standardized to UTC."""
    source_id = uuid.uuid4()

    # Naive datetime is converted to UTC
    naive_dt = datetime(2026, 5, 20, 14, 0, 0)
    item_naive = EvidenceItemCreate(
        evidence_source_id=source_id,
        evidence_type=EvidenceType.OTHER,
        description="Observation with naive timestamp",
        observed_at=naive_dt,
    )
    assert item_naive.observed_at.tzinfo == UTC
    assert item_naive.observed_at.hour == 14

    # Default observed_at is current UTC time
    now_before = datetime.now(UTC)
    item_default = EvidenceItemCreate(
        evidence_source_id=source_id,
        evidence_type=EvidenceType.OTHER,
        description="Observation with default timestamp",
    )
    now_after = datetime.now(UTC)
    assert item_default.observed_at.tzinfo == UTC
    assert now_before <= item_default.observed_at <= now_after


# =========================================================================
# 3. Source Foreign-Key Integrity and Deletion Restrictions
# =========================================================================


def test_create_item_with_nonexistent_source_fails(db: Session) -> None:
    """Verifies that service rejects creating evidence item for a non-existent source."""
    service = EvidenceItemService(db)
    random_id = uuid.uuid4()

    payload = EvidenceItemCreate(
        evidence_source_id=random_id,
        evidence_type=EvidenceType.OTHER,
        description="Orphaned observation",
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_evidence_item(payload)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Referenced evidence source does not exist" in exc_info.value.detail


def test_deleting_source_blocked_by_restrict_constraint(db: Session) -> None:
    """
    Verifies that ON DELETE RESTRICT on evidence_source_id prevents deleting an
    EvidenceSource while dependent EvidenceItem records exist, guaranteeing observations
    cannot be silently erased.
    """
    db.execute(text("PRAGMA foreign_keys = ON"))
    user = create_test_user(db, "restrict_user")
    source = create_test_source(db, user)

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.REPOSITORY_METADATA,
        description="Dependency inspection observation",
    )
    db.add(item)
    db.commit()

    source_id = source.id
    item_id = item.id

    # Attempting to delete the EvidenceSource must fail due to ON DELETE RESTRICT
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.delete(source)

    # Verify source and item both remain intact in database
    db.expire_all()
    preserved_source = db.get(EvidenceSource, source_id)
    assert preserved_source is not None
    preserved_item = db.get(EvidenceItem, item_id)
    assert preserved_item is not None
    assert preserved_item.evidence_source_id == source_id


# =========================================================================
# 4. Evidence Preservation After Source Revocation
# =========================================================================


def test_evidence_preserved_after_source_revocation(db: Session) -> None:
    """
    Verifies that revoking access to an evidence source:
    1. Does NOT delete its existing evidence items.
    2. Allows historical evidence items to still be queried for verification audit.
    3. Rejects new observations against the revoked source unless explicitly allowed.
    """
    user = create_test_user(db, "revoke_preserve_user")
    source = create_test_source(db, user)
    service = EvidenceItemService(db)

    # 1. Record an observation before revocation
    item_in = EvidenceItemCreate(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Verified implementation of OAuth token refresh",
        source_locator="src/auth/token.ts",
    )
    created_item = service.create_evidence_item(item_in, user=user)

    # 2. Revoke the source
    source.access_status = EvidenceSourceStatus.REVOKED
    db.add(source)
    db.commit()
    db.refresh(source)
    assert source.access_status == EvidenceSourceStatus.REVOKED

    # 3. Existing evidence items remain completely accessible
    fetched = service.get_evidence_item(created_item.id, user=user)
    assert fetched.id == created_item.id
    assert fetched.description == "Verified implementation of OAuth token refresh"

    source_items = service.list_items_for_source(source.id, user=user)
    assert len(source_items) == 1
    assert source_items[0].id == created_item.id

    # 4. Attempting to record NEW evidence items against the revoked source is rejected
    new_item_payload = EvidenceItemCreate(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.OTHER,
        description="New observation attempt on revoked source",
    )
    with pytest.raises(HTTPException) as exc_info:
        service.create_evidence_item(new_item_payload, user=user)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        "Cannot record evidence items for a revoked evidence source"
        in exc_info.value.detail
    )


# =========================================================================
# 5. Candidate Ownership & Authorization Boundaries
# =========================================================================


def test_evidence_service_enforces_candidate_authorization(db: Session) -> None:
    """
    Verifies that Candidate A cannot create, read, or list observations
    belonging to Candidate B's evidence sources when candidate scope is provided.
    """
    candidate_a = create_test_user(db, "cand_a")
    candidate_b = create_test_user(db, "cand_b")

    source_a = create_test_source(
        db, candidate_a, source_uri="https://github.com/cand-a/repo"
    )
    source_b = create_test_source(
        db, candidate_b, source_uri="https://github.com/cand-b/repo"
    )

    service = EvidenceItemService(db)

    # Candidate A creates an observation on source A
    item_a = service.create_evidence_item(
        EvidenceItemCreate(
            evidence_source_id=source_a.id,
            evidence_type=EvidenceType.REPOSITORY_METADATA,
            description="Candidate A's project metrics",
        ),
        user=candidate_a,
    )

    # Candidate B attempts to record an observation on Candidate A's source -> 404
    with pytest.raises(HTTPException) as exc_create:
        service.create_evidence_item(
            EvidenceItemCreate(
                evidence_source_id=source_a.id,
                evidence_type=EvidenceType.REPOSITORY_METADATA,
                description="Malicious injection attempt",
            ),
            user=candidate_b,
        )
    assert exc_create.value.status_code == status.HTTP_404_NOT_FOUND

    # Candidate B attempts to read Candidate A's evidence item -> 404
    with pytest.raises(HTTPException) as exc_read:
        service.get_evidence_item(item_a.id, user=candidate_b)
    assert exc_read.value.status_code == status.HTTP_404_NOT_FOUND

    # Candidate B attempts to list Candidate A's evidence items for source A -> 404
    with pytest.raises(HTTPException) as exc_list:
        service.list_items_for_source(source_a.id, user=candidate_b)
    assert exc_list.value.status_code == status.HTTP_404_NOT_FOUND

    # Candidate B attempts to count items on Candidate A's source -> 404
    with pytest.raises(HTTPException) as exc_count:
        service.count_items_for_source(source_a.id, user=candidate_b)
    assert exc_count.value.status_code == status.HTTP_404_NOT_FOUND

    # Candidate A attempts to list items on Candidate B's source -> 404
    with pytest.raises(HTTPException) as exc_cand_a_source_b:
        service.list_items_for_source(source_b.id, user=candidate_a)
    assert exc_cand_a_source_b.value.status_code == status.HTTP_404_NOT_FOUND


# =========================================================================
# 6. Absence of Public / Candidate-Facing Evidence Creation Endpoints
# =========================================================================


def test_no_candidate_facing_evidence_item_endpoints_exposed(
    client: TestClient, db: Session
) -> None:
    """
    Verifies the architectural constraint that no candidate-facing API endpoints
    exist for creating, updating, or deleting EvidenceItem observations.
    All write requests to candidate-facing URLs must return 404 Not Found.
    """
    random_item_id = uuid.uuid4()
    random_source_id = uuid.uuid4()

    dummy_payload = {
        "evidence_source_id": str(random_source_id),
        "evidence_type": "REPOSITORY_METADATA",
        "description": "User attempting arbitrary self-asserted evidence",
    }

    # 1. Direct evidence-items endpoints must not exist
    res_post = client.post("/api/v1/evidence-items", json=dummy_payload)
    assert res_post.status_code == status.HTTP_404_NOT_FOUND

    res_get = client.get(f"/api/v1/evidence-items/{random_item_id}")
    assert res_get.status_code == status.HTTP_404_NOT_FOUND

    res_put = client.put(f"/api/v1/evidence-items/{random_item_id}", json=dummy_payload)
    assert res_put.status_code == status.HTTP_404_NOT_FOUND

    res_delete = client.delete(f"/api/v1/evidence-items/{random_item_id}")
    assert res_delete.status_code == status.HTTP_404_NOT_FOUND

    # 2. Nested evidence-sources items endpoints must not exist
    res_nested_post = client.post(
        f"/api/v1/evidence-sources/{random_source_id}/items", json=dummy_payload
    )
    assert res_nested_post.status_code == status.HTTP_404_NOT_FOUND

    res_nested_delete = client.delete(
        f"/api/v1/evidence-sources/{random_source_id}/items/{random_item_id}"
    )
    assert res_nested_delete.status_code == status.HTTP_404_NOT_FOUND


# =========================================================================
# 7. Immutability Enforcements & Provenance Restrictions
# =========================================================================


def test_created_at_cannot_be_supplied_in_evidence_item_create() -> None:
    """Verifies that callers cannot supply or overwrite created_at; extra fields are strictly forbidden."""
    with pytest.raises(ValidationError) as exc_info:
        EvidenceItemCreate(  # type: ignore[call-arg]
            evidence_source_id=uuid.uuid4(),
            evidence_type=EvidenceType.OTHER,
            description="Attempting to forge created_at",
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)


def test_repository_update_and_remove_blocked_for_immutability(
    db: Session,
) -> None:
    """Verifies that EvidenceItem records are immutable and cannot be updated or deleted via repository methods."""
    user = create_test_user(db, "immutable_user")
    source = create_test_source(db, user)
    repo = EvidenceItemRepository(db)

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Immutable code observation",
    )
    repo.create(item)

    # Direct repository update must raise NotImplementedError
    with pytest.raises(NotImplementedError) as exc_update:
        repo.update(item, {"description": "Mutated description"})
    assert "immutable audit observations and cannot be modified" in str(
        exc_update.value
    )

    # Direct repository remove must raise NotImplementedError
    with pytest.raises(NotImplementedError) as exc_remove:
        repo.remove(item.id)
    assert "immutable audit observations and cannot be deleted" in str(exc_remove.value)


def test_service_allow_revoked_parameter_for_internal_collectors(
    db: Session,
) -> None:
    """
    Verifies that trusted internal collectors can supply allow_revoked=True for historical
    replay or backfill, while default allow_revoked=False strictly rejects new collections.
    """
    user = create_test_user(db, "replay_user")
    source = create_test_source(db, user, access_status=EvidenceSourceStatus.REVOKED)
    service = EvidenceItemService(db)

    payload = EvidenceItemCreate(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.REPOSITORY_METADATA,
        description="Historical backfill observation prior to revocation",
    )

    # Default rejects with 400
    with pytest.raises(HTTPException) as exc_default:
        service.create_evidence_item(payload, user=user)
    assert exc_default.value.status_code == status.HTTP_400_BAD_REQUEST

    # Explicit allow_revoked=True succeeds for internal backfill
    replayed = service.create_evidence_item(payload, user=user, allow_revoked=True)
    assert replayed.id is not None
    assert replayed.description == "Historical backfill observation prior to revocation"


def test_service_user_none_allows_internal_collector_when_source_exists(
    db: Session,
) -> None:
    """
    Verifies that user=None allows background / trusted collector processes
    to record evidence without an active HTTP user context, while still validating source existence.
    """
    user = create_test_user(db, "collector_user")
    source = create_test_source(db, user)
    service = EvidenceItemService(db)

    payload = EvidenceItemCreate(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Asynchronous collector worker observation",
    )

    # user=None succeeds for existing source
    created = service.create_evidence_item(payload, user=None)
    assert created.id is not None

    # user=None with non-existent source still raises 404
    missing_source_payload = EvidenceItemCreate(
        evidence_source_id=uuid.uuid4(),
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description="Collector referencing non-existent source",
    )
    with pytest.raises(HTTPException) as exc_missing:
        service.create_evidence_item(missing_source_payload, user=None)
    assert exc_missing.value.status_code == status.HTTP_404_NOT_FOUND
