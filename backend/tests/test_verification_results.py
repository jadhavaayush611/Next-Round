import uuid
from datetime import UTC, datetime

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    AccessMode,
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.user import User
from app.models.verification_result import (
    VerificationEvidence,
    VerificationOutcome,
    VerificationResult,
    VerificationType,
)
from app.repositories.verification_result import VerificationResultRepository
from app.schemas.verification_result import (
    VerificationResultCreate,
)
from app.services.verification_result_service import VerificationResultService


def create_test_user(db: Session, prefix: str = "verif_user") -> User:
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


def create_test_claim(
    db: Session,
    user: User,
    claim_type: ClaimType = ClaimType.SKILL,
    claim_text: str = "Expert in distributed PostgreSQL architecture.",
) -> CandidateClaim:
    """Helper to create and persist a test CandidateClaim."""
    claim = CandidateClaim(
        user_id=user.id,
        claim_type=claim_type,
        claim_text=claim_text,
        origin=ClaimOrigin.USER_DECLARED,
    )
    db.add(claim)
    db.commit()
    db.refresh(claim)
    return claim


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


def create_test_item(
    db: Session,
    source: EvidenceSource,
    evidence_type: EvidenceType = EvidenceType.REPOSITORY_METADATA,
    description: str = "PostgreSQL cluster configuration detected in repository.",
) -> EvidenceItem:
    """Helper to create and persist a test EvidenceItem."""
    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=evidence_type,
        description=description,
        observed_data={"db": "postgresql", "version": "16"},
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return item


# =========================================================================
# 1. Valid Claim-Scoped and Source-Only Results
# =========================================================================


def test_create_and_retrieve_claim_scoped_result(db: Session) -> None:
    """Verifies creating, persisting, and retrieving a claim-scoped verification result."""
    user = create_test_user(db, "claim_verif")
    claim = create_test_claim(db, user)
    source = create_test_source(db, user)
    item = create_test_item(db, source)
    service = VerificationResultService(db)

    custom_checked_at = datetime(2026, 10, 10, 14, 0, tzinfo=UTC)
    payload = VerificationResultCreate(
        candidate_claim_id=claim.id,
        evidence_source_id=source.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1.0.0-git-analysis",
        explanation="Repository commit history confirms hands-on PostgreSQL schema design.",
        checked_at=custom_checked_at,
        evidence_item_ids=[item.id],
    )

    created = service.create_verification_result(payload, user=user)
    assert created.id is not None
    assert created.candidate_claim_id == claim.id
    assert created.evidence_source_id == source.id
    assert created.verification_type == VerificationType.CLAIM_SUPPORT
    assert created.outcome == VerificationOutcome.SUPPORTED
    assert created.method_version == "v1.0.0-git-analysis"
    assert created.explanation == payload.explanation
    assert created.checked_at == custom_checked_at
    assert created.created_at is not None
    assert created.evidence_item_ids == [item.id]
    assert len(created.evidence_items) == 1
    assert created.evidence_items[0].id == item.id

    # Retrieve by ID
    retrieved = service.get_verification_result(created.id, user=user)
    assert retrieved.id == created.id
    assert retrieved.evidence_item_ids == [item.id]

    # List by claim
    claim_results = service.list_results_for_claim(claim.id, user=user)
    assert len(claim_results) == 1
    assert claim_results[0].id == created.id

    # List by source
    source_results = service.list_results_for_source(source.id, user=user)
    assert len(source_results) == 1
    assert source_results[0].id == created.id

    # List by user
    user_results = service.list_results_for_user(user)
    assert len(user_results) == 1
    assert user_results[0].id == created.id

    # Count operations
    assert service.count_results_for_claim(claim.id, user=user) == 1
    assert service.count_results_for_source(source.id, user=user) == 1


def test_create_and_retrieve_source_only_result(db: Session) -> None:
    """Verifies creating, persisting, and querying a source-only check (e.g. SOURCE_EXISTENCE)."""
    user = create_test_user(db, "source_verif")
    source = create_test_source(db, user)
    item = create_test_item(db, source)
    service = VerificationResultService(db)

    payload = VerificationResultCreate(
        candidate_claim_id=None,
        evidence_source_id=source.id,
        verification_type=VerificationType.SOURCE_EXISTENCE,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1.0.0-source-check",
        explanation="Public repository responds with HTTP 200 and valid commit tree.",
        evidence_item_ids=[item.id],
    )

    created = service.create_verification_result(payload, user=user)
    assert created.id is not None
    assert created.candidate_claim_id is None
    assert created.evidence_source_id == source.id
    assert created.verification_type == VerificationType.SOURCE_EXISTENCE
    assert created.outcome == VerificationOutcome.SUPPORTED
    assert created.evidence_item_ids == [item.id]

    # Query by source and user
    source_results = service.list_results_for_source(source.id, user=user)
    assert len(source_results) == 1
    assert source_results[0].id == created.id

    user_results = service.list_results_for_user(user)
    assert len(user_results) == 1
    assert user_results[0].id == created.id


def test_new_check_creates_new_historical_result(db: Session) -> None:
    """Verifies that running subsequent checks against the same target creates new historical records rather than overwriting."""
    user = create_test_user(db, "history_user")
    claim = create_test_claim(db, user)
    service = VerificationResultService(db)

    first_payload = VerificationResultCreate(
        candidate_claim_id=claim.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.INCONCLUSIVE,
        method_version="v1.0.0",
        explanation="Initial check lacked sufficient code evidence.",
    )
    first_res = service.create_verification_result(first_payload, user=user)

    second_payload = VerificationResultCreate(
        candidate_claim_id=claim.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1.1.0",
        explanation="Second check with additional evidence items confirmed support.",
    )
    second_res = service.create_verification_result(second_payload, user=user)

    assert first_res.id != second_res.id
    assert first_res.outcome == VerificationOutcome.INCONCLUSIVE
    assert second_res.outcome == VerificationOutcome.SUPPORTED

    results = service.list_results_for_claim(claim.id, user=user)
    assert len(results) == 2
    assert service.count_results_for_claim(claim.id, user=user) == 2
    # Verify chronological ordering (newest first)
    assert results[0].id == second_res.id
    assert results[1].id == first_res.id


# =========================================================================
# 2. Every Supported Verification Type and Outcome
# =========================================================================


@pytest.mark.parametrize(
    "verif_type",
    [
        VerificationType.SOURCE_EXISTENCE,
        VerificationType.CLAIM_SUPPORT,
        VerificationType.ASSESSMENT,
        VerificationType.OTHER,
    ],
)
@pytest.mark.parametrize(
    "outcome",
    [
        VerificationOutcome.SUPPORTED,
        VerificationOutcome.CONTRADICTED,
        VerificationOutcome.INCONCLUSIVE,
        VerificationOutcome.UNAVAILABLE,
    ],
)
def test_all_verification_types_and_outcomes_supported(
    db: Session,
    verif_type: VerificationType,
    outcome: VerificationOutcome,
) -> None:
    """Verifies that all 4 verification types and all 4 outcomes persist and read correctly."""
    user = create_test_user(db, "matrix_user")
    claim = create_test_claim(db, user)
    source = create_test_source(db, user)
    service = VerificationResultService(db)

    payload = VerificationResultCreate(
        candidate_claim_id=claim.id,
        evidence_source_id=source.id,
        verification_type=verif_type,
        outcome=outcome,
        method_version="matrix-v1",
        explanation=f"Testing verification type {verif_type} with outcome {outcome}.",
    )
    result = service.create_verification_result(payload, user=user)
    assert result.verification_type == verif_type
    assert result.outcome == outcome


# =========================================================================
# 3. Invalid Target Combinations & CLAIM_SUPPORT Without Claim
# =========================================================================


def test_both_claim_and_source_none_rejected() -> None:
    """Verifies that a result without both candidate_claim_id and evidence_source_id is rejected by schema."""
    with pytest.raises(ValidationError) as exc_info:
        VerificationResultCreate(
            candidate_claim_id=None,
            evidence_source_id=None,
            verification_type=VerificationType.OTHER,
            outcome=VerificationOutcome.INCONCLUSIVE,
            method_version="v1",
            explanation="Invalid target attempt",
        )
    assert (
        "must reference at least one candidate_claim_id or evidence_source_id"
        in str(exc_info.value)
    )


def test_claim_support_without_claim_rejected(db: Session) -> None:
    """Verifies that CLAIM_SUPPORT verification requires candidate_claim_id."""
    user = create_test_user(db, "no_claim_user")
    source = create_test_source(db, user)

    # 1. Pydantic validation error
    with pytest.raises(ValidationError) as exc_info:
        VerificationResultCreate(
            candidate_claim_id=None,
            evidence_source_id=source.id,
            verification_type=VerificationType.CLAIM_SUPPORT,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="v1",
            explanation="Claim support without claim",
        )
    assert "CLAIM_SUPPORT verification requires a candidate_claim_id" in str(
        exc_info.value
    )


def test_db_check_constraints_enforced(db: Session) -> None:
    """Verifies database-level check constraints on targets and required claim for CLAIM_SUPPORT."""
    # 1. Neither target present
    invalid_no_target = VerificationResult(
        candidate_claim_id=None,
        evidence_source_id=None,
        verification_type=VerificationType.OTHER,
        outcome=VerificationOutcome.INCONCLUSIVE,
        method_version="v1",
        explanation="Direct DB insert violation",
    )
    db.add(invalid_no_target)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.flush()
    db.rollback()

    # 2. CLAIM_SUPPORT without claim
    user = create_test_user(db, "db_chk_user")
    source = create_test_source(db, user)
    invalid_claim_support = VerificationResult(
        candidate_claim_id=None,
        evidence_source_id=source.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1",
        explanation="Direct DB insert claim support violation",
    )
    db.add(invalid_claim_support)
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.flush()
    db.rollback()


def test_empty_method_version_and_explanation_rejected(db: Session) -> None:
    """Verifies that empty strings or whitespace-only method_version and explanation are rejected."""
    user = create_test_user(db, "empty_str_user")
    claim = create_test_claim(db, user)

    # Empty method_version in schema
    with pytest.raises(ValidationError) as exc_ver:
        VerificationResultCreate(
            candidate_claim_id=claim.id,
            verification_type=VerificationType.CLAIM_SUPPORT,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="   ",
            explanation="Valid explanation",
        )
    assert "method_version cannot be empty" in str(exc_ver.value)

    # Empty explanation in schema
    with pytest.raises(ValidationError) as exc_exp:
        VerificationResultCreate(
            candidate_claim_id=claim.id,
            verification_type=VerificationType.CLAIM_SUPPORT,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="v1",
            explanation="   ",
        )
    assert "explanation cannot be empty" in str(exc_exp.value)


# =========================================================================
# 4. Evidence Associations, Duplicates & Cross-Reference Integrity
# =========================================================================


def test_duplicate_evidence_item_ids_rejected() -> None:
    """Verifies that duplicate evidence items in the create payload are rejected."""
    item_id = uuid.uuid4()
    with pytest.raises(ValidationError) as exc_info:
        VerificationResultCreate(
            candidate_claim_id=uuid.uuid4(),
            verification_type=VerificationType.CLAIM_SUPPORT,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="v1",
            explanation="Duplicate evidence test",
            evidence_item_ids=[item_id, item_id],
        )
    assert "Duplicate evidence item associations are not permitted" in str(
        exc_info.value
    )


def test_db_composite_pk_prevents_duplicate_evidence_links(db: Session) -> None:
    """Verifies that the verification_evidence composite primary key enforces uniqueness at the database level."""
    user = create_test_user(db, "dup_db_user")
    claim = create_test_claim(db, user)
    source = create_test_source(db, user)
    item = create_test_item(db, source)

    result = VerificationResult(
        candidate_claim_id=claim.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1",
        explanation="Testing composite primary key",
    )
    db.add(result)
    db.commit()

    link1 = VerificationEvidence(
        verification_result_id=result.id,
        evidence_item_id=item.id,
    )
    db.add(link1)
    db.commit()

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(
                text(
                    "INSERT INTO verification_evidence (verification_result_id, evidence_item_id) "
                    "VALUES (:res_id, :item_id)"
                ),
                {"res_id": result.id.hex, "item_id": item.id.hex},
            )
    db.rollback()


def test_source_scoped_check_rejects_evidence_from_different_source(
    db: Session,
) -> None:
    """
    Verifies invariant: 'Evidence must belong to the referenced source when the result is source-scoped.'
    When candidate_claim_id is None and evidence_source_id is source_a, linking an evidence item
    from source_b (even if owned by the same candidate) is rejected with 400 Bad Request.
    """
    user = create_test_user(db, "scope_user")
    source_a = create_test_source(
        db, user, source_uri="https://github.com/nextround/repo-a"
    )
    source_b = create_test_source(
        db, user, source_uri="https://github.com/nextround/repo-b"
    )
    item_from_b = create_test_item(db, source_b)
    service = VerificationResultService(db)

    payload = VerificationResultCreate(
        candidate_claim_id=None,
        evidence_source_id=source_a.id,
        verification_type=VerificationType.SOURCE_EXISTENCE,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1",
        explanation="Source A existence check",
        evidence_item_ids=[item_from_b.id],
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_verification_result(payload, user=user)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        f"does not belong to the referenced evidence source {source_a.id}"
        in exc_info.value.detail
    )


def test_claim_and_source_check_rejects_evidence_from_different_source(
    db: Session,
) -> None:
    """
    Verifies that when both candidate_claim_id and evidence_source_id are supplied,
    every linked EvidenceItem must belong to that specific referenced source.
    """
    user = create_test_user(db, "claim_src_scope_user")
    claim = create_test_claim(db, user)
    source_a = create_test_source(
        db, user, source_uri="https://github.com/nextround/repo-claim-a"
    )
    source_b = create_test_source(
        db, user, source_uri="https://github.com/nextround/repo-claim-b"
    )
    item_from_b = create_test_item(db, source_b)
    service = VerificationResultService(db)

    payload = VerificationResultCreate(
        candidate_claim_id=claim.id,
        evidence_source_id=source_a.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1",
        explanation="Claim check targeted to source A",
        evidence_item_ids=[item_from_b.id],
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_verification_result(payload, user=user)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert (
        f"does not belong to the referenced evidence source {source_a.id}"
        in exc_info.value.detail
    )


def test_claim_only_check_allows_evidence_from_multiple_candidate_sources(
    db: Session,
) -> None:
    """
    Verifies that when evidence_source_id is None, a claim-scoped verification
    check can link evidence items from multiple sources belonging to the candidate.
    """
    user = create_test_user(db, "multi_src_user")
    claim = create_test_claim(db, user)
    source_a = create_test_source(
        db, user, source_uri="https://github.com/nextround/multi-a"
    )
    source_b = create_test_source(
        db, user, source_uri="https://github.com/nextround/multi-b"
    )
    item_a = create_test_item(db, source_a)
    item_b = create_test_item(db, source_b)
    service = VerificationResultService(db)

    payload = VerificationResultCreate(
        candidate_claim_id=claim.id,
        evidence_source_id=None,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1",
        explanation="Claim-scoped multi-source check",
        evidence_item_ids=[item_a.id, item_b.id],
    )

    result = service.create_verification_result(payload, user=user)
    assert result.id is not None
    assert result.candidate_claim_id == claim.id
    assert result.evidence_source_id is None
    assert set(result.evidence_item_ids) == {item_a.id, item_b.id}


def test_nonexistent_targets_rejected(db: Session) -> None:
    """Verifies that non-existent claim, source, or evidence item IDs raise 404."""
    user = create_test_user(db, "missing_ref_user")
    service = VerificationResultService(db)
    random_id = uuid.uuid4()

    # Missing claim
    with pytest.raises(HTTPException) as exc_claim:
        service.create_verification_result(
            VerificationResultCreate(
                candidate_claim_id=random_id,
                verification_type=VerificationType.CLAIM_SUPPORT,
                outcome=VerificationOutcome.SUPPORTED,
                method_version="v1",
                explanation="Test",
            ),
            user=user,
        )
    assert exc_claim.value.status_code == status.HTTP_404_NOT_FOUND

    # Missing source
    with pytest.raises(HTTPException) as exc_source:
        service.create_verification_result(
            VerificationResultCreate(
                evidence_source_id=random_id,
                verification_type=VerificationType.SOURCE_EXISTENCE,
                outcome=VerificationOutcome.SUPPORTED,
                method_version="v1",
                explanation="Test",
            ),
            user=user,
        )
    assert exc_source.value.status_code == status.HTTP_404_NOT_FOUND

    # Missing evidence item
    claim = create_test_claim(db, user)
    with pytest.raises(HTTPException) as exc_item:
        service.create_verification_result(
            VerificationResultCreate(
                candidate_claim_id=claim.id,
                verification_type=VerificationType.CLAIM_SUPPORT,
                outcome=VerificationOutcome.SUPPORTED,
                method_version="v1",
                explanation="Test",
                evidence_item_ids=[random_id],
            ),
            user=user,
        )
    assert exc_item.value.status_code == status.HTTP_404_NOT_FOUND


# =========================================================================
# 5. Cross-User Claim/Source/Evidence Rejection
# =========================================================================


def test_cross_user_rejection_claim_and_source(db: Session) -> None:
    """Verifies that associating User A's claim with User B's source is rejected."""
    user_a = create_test_user(db, "user_a")
    user_b = create_test_user(db, "user_b")
    claim_a = create_test_claim(db, user_a)
    source_b = create_test_source(db, user_b)
    service = VerificationResultService(db)

    payload = VerificationResultCreate(
        candidate_claim_id=claim_a.id,
        evidence_source_id=source_b.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1",
        explanation="Attempting cross-user combination",
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_verification_result(payload, user=None)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "belong to different candidates" in exc_info.value.detail


def test_cross_user_rejection_evidence_item(db: Session) -> None:
    """Verifies that linking User B's evidence item to User A's claim verification is rejected."""
    user_a = create_test_user(db, "user_a_ev")
    user_b = create_test_user(db, "user_b_ev")
    claim_a = create_test_claim(db, user_a)
    source_b = create_test_source(db, user_b)
    item_b = create_test_item(db, source_b)
    service = VerificationResultService(db)

    payload = VerificationResultCreate(
        candidate_claim_id=claim_a.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1",
        explanation="Attempting cross-user evidence link",
        evidence_item_ids=[item_b.id],
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_verification_result(payload, user=user_a)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "belongs to a different candidate" in exc_info.value.detail


def test_candidate_authorization_boundaries(db: Session) -> None:
    """Verifies that Candidate B cannot access or list Candidate A's verification results."""
    user_a = create_test_user(db, "auth_a")
    user_b = create_test_user(db, "auth_b")
    claim_a = create_test_claim(db, user_a)
    source_a = create_test_source(db, user_a)
    service = VerificationResultService(db)

    result = service.create_verification_result(
        VerificationResultCreate(
            candidate_claim_id=claim_a.id,
            evidence_source_id=source_a.id,
            verification_type=VerificationType.CLAIM_SUPPORT,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="v1",
            explanation="Candidate A's result",
        ),
        user=user_a,
    )

    # User B cannot read User A's result
    with pytest.raises(HTTPException) as exc_read:
        service.get_verification_result(result.id, user=user_b)
    assert exc_read.value.status_code == status.HTTP_404_NOT_FOUND

    # User B cannot list results for User A's claim
    with pytest.raises(HTTPException) as exc_claim:
        service.list_results_for_claim(claim_a.id, user=user_b)
    assert exc_claim.value.status_code == status.HTTP_404_NOT_FOUND

    # User B cannot list results for User A's source
    with pytest.raises(HTTPException) as exc_source:
        service.list_results_for_source(source_a.id, user=user_b)
    assert exc_source.value.status_code == status.HTTP_404_NOT_FOUND


# =========================================================================
# 6. Historical Immutability and Deletion Restrictions
# =========================================================================


def test_repository_update_and_remove_blocked_for_immutability(
    db: Session,
) -> None:
    """Verifies that VerificationResult records are immutable and cannot be updated or deleted via repository."""
    user = create_test_user(db, "immutable_verif_user")
    claim = create_test_claim(db, user)
    repo = VerificationResultRepository(db)

    result = VerificationResult(
        candidate_claim_id=claim.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1",
        explanation="Immutable verification check",
    )
    repo.create(result)

    with pytest.raises(NotImplementedError) as exc_up:
        repo.update(result, {"explanation": "Mutated explanation"})
    assert "immutable audit records and cannot be modified" in str(exc_up.value)

    with pytest.raises(NotImplementedError) as exc_rm:
        repo.remove(result.id)
    assert "immutable audit records and cannot be deleted" in str(exc_rm.value)


def test_deleting_claim_blocked_by_restrict_constraint(db: Session) -> None:
    """Verifies that ON DELETE RESTRICT on candidate_claim_id prevents deleting a claim with verification results."""
    db.execute(text("PRAGMA foreign_keys = ON"))
    user = create_test_user(db, "del_claim_user")
    claim = create_test_claim(db, user)
    service = VerificationResultService(db)

    service.create_verification_result(
        VerificationResultCreate(
            candidate_claim_id=claim.id,
            verification_type=VerificationType.CLAIM_SUPPORT,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="v1",
            explanation="Claim check",
        ),
        user=user,
    )

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.delete(claim)

    db.expire_all()
    preserved = db.get(CandidateClaim, claim.id)
    assert preserved is not None


def test_deleting_source_blocked_by_restrict_constraint(db: Session) -> None:
    """Verifies that ON DELETE RESTRICT on evidence_source_id prevents deleting a source with verification results."""
    db.execute(text("PRAGMA foreign_keys = ON"))
    user = create_test_user(db, "del_src_user")
    source = create_test_source(db, user)
    service = VerificationResultService(db)

    service.create_verification_result(
        VerificationResultCreate(
            evidence_source_id=source.id,
            verification_type=VerificationType.SOURCE_EXISTENCE,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="v1",
            explanation="Source existence check",
        ),
        user=user,
    )

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.delete(source)

    db.expire_all()
    preserved = db.get(EvidenceSource, source.id)
    assert preserved is not None


def test_deleting_evidence_item_blocked_by_restrict_constraint(
    db: Session,
) -> None:
    """Verifies that ON DELETE RESTRICT in verification_evidence prevents deleting an evidence item linked to a verification result."""
    db.execute(text("PRAGMA foreign_keys = ON"))
    user = create_test_user(db, "del_item_user")
    source = create_test_source(db, user)
    item = create_test_item(db, source)
    service = VerificationResultService(db)

    service.create_verification_result(
        VerificationResultCreate(
            evidence_source_id=source.id,
            verification_type=VerificationType.SOURCE_EXISTENCE,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="v1",
            explanation="Check linking evidence item",
            evidence_item_ids=[item.id],
        ),
        user=user,
    )

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(
                text("DELETE FROM evidence_items WHERE id = :id"),
                {"id": item.id.hex},
            )

    db.expire_all()
    preserved = db.get(EvidenceItem, item.id)
    assert preserved is not None


def test_deleting_verification_result_with_evidence_blocked_by_restrict(
    db: Session,
) -> None:
    """Verifies that ON DELETE RESTRICT prevents deleting a verification result while rows in verification_evidence exist."""
    db.execute(text("PRAGMA foreign_keys = ON"))
    user = create_test_user(db, "del_verif_user")
    source = create_test_source(db, user)
    item = create_test_item(db, source)
    service = VerificationResultService(db)

    created = service.create_verification_result(
        VerificationResultCreate(
            evidence_source_id=source.id,
            verification_type=VerificationType.SOURCE_EXISTENCE,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="v1",
            explanation="Check linking evidence item",
            evidence_item_ids=[item.id],
        ),
        user=user,
    )

    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.execute(
                text("DELETE FROM verification_results WHERE id = :id"),
                {"id": created.id.hex},
            )

    db.expire_all()
    preserved = db.get(VerificationResult, created.id)
    assert preserved is not None


# =========================================================================
# 7. Timestamp Handling and Server-Managed Created At
# =========================================================================


def test_created_at_cannot_be_supplied_in_create_payload() -> None:
    """Verifies that callers cannot forge created_at; extra fields are strictly forbidden."""
    with pytest.raises(ValidationError) as exc_info:
        VerificationResultCreate(  # type: ignore[call-arg]
            candidate_claim_id=uuid.uuid4(),
            verification_type=VerificationType.CLAIM_SUPPORT,
            outcome=VerificationOutcome.SUPPORTED,
            method_version="v1",
            explanation="Attempting to forge created_at",
            created_at=datetime(2020, 1, 1, tzinfo=UTC),
        )
    assert "Extra inputs are not permitted" in str(exc_info.value)


def test_custom_checked_at_preserved_and_normalized_to_utc(db: Session) -> None:
    """Verifies that caller-provided checked_at is preserved and normalized to UTC."""
    user = create_test_user(db, "time_user")
    claim = create_test_claim(db, user)
    service = VerificationResultService(db)

    past_time = datetime(2026, 8, 1, 12, 0, tzinfo=UTC)
    payload = VerificationResultCreate(
        candidate_claim_id=claim.id,
        verification_type=VerificationType.CLAIM_SUPPORT,
        outcome=VerificationOutcome.SUPPORTED,
        method_version="v1",
        explanation="Testing historical timestamp preservation",
        checked_at=past_time,
    )

    created = service.create_verification_result(payload, user=user)
    assert created.checked_at == past_time
    assert created.created_at is not None
    assert created.created_at.tzinfo is not None
    assert created.created_at != past_time


# =========================================================================
# 8. Absence of Public / Candidate-Facing Verification Write Endpoints
# =========================================================================


def test_no_candidate_facing_verification_endpoints_exposed(
    client: TestClient,
) -> None:
    """
    Verifies the architectural constraint that no candidate-facing API endpoints
    exist for creating, updating, or deleting VerificationResult entities.
    All write requests to candidate-facing URLs must return 404 Not Found.
    """
    random_id = uuid.uuid4()
    dummy_payload = {
        "candidate_claim_id": str(random_id),
        "verification_type": "CLAIM_SUPPORT",
        "outcome": "SUPPORTED",
        "method_version": "v1",
        "explanation": "Self-asserted verification attempt",
    }

    # Direct verification-results endpoints must not exist
    assert (
        client.post("/api/v1/verification-results", json=dummy_payload).status_code
        == status.HTTP_404_NOT_FOUND
    )
    assert (
        client.get(f"/api/v1/verification-results/{random_id}").status_code
        == status.HTTP_404_NOT_FOUND
    )
    assert (
        client.put(
            f"/api/v1/verification-results/{random_id}", json=dummy_payload
        ).status_code
        == status.HTTP_404_NOT_FOUND
    )
    assert (
        client.delete(f"/api/v1/verification-results/{random_id}").status_code
        == status.HTTP_404_NOT_FOUND
    )

    # Nested claim verifications endpoints must not exist
    assert (
        client.post(
            f"/api/v1/candidate-claims/{random_id}/verifications",
            json=dummy_payload,
        ).status_code
        == status.HTTP_404_NOT_FOUND
    )

    # Nested source verifications endpoints must not exist
    assert (
        client.post(
            f"/api/v1/evidence-sources/{random_id}/verifications",
            json=dummy_payload,
        ).status_code
        == status.HTTP_404_NOT_FOUND
    )
