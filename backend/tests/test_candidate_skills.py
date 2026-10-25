import uuid

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.models.candidate_skill import CandidateSkill, CandidateSkillEvidence
from app.models.evidence_item import EvidenceItem, EvidenceType
from app.models.evidence_source import (
    AccessMode,
    EvidenceSource,
    EvidenceSourceStatus,
    EvidenceSourceType,
)
from app.models.skill import Skill
from app.models.user import User
from app.repositories.candidate_skill import CandidateSkillRepository
from app.schemas.candidate_skill import (
    CandidateSkillCreate,
    CandidateSkillEvidenceCreate,
    CandidateSkillResponse,
)
from app.services.candidate_skill_service import CandidateSkillService

# =============================================================================
# Helper Fixtures and Factories
# =============================================================================


def create_test_user(db: Session, prefix: str = "cand_skill_user") -> User:
    """Helper to persist a test User."""
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


def create_test_skill(
    db: Session,
    name: str = "Python",
    category: str = "Programming Language",
    aliases: list[str] | None = None,
) -> Skill:
    """Helper to persist a canonical Skill."""
    skill = Skill(
        canonical_name=name,
        category=category,
        aliases=aliases or [],
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def create_test_claim(
    db: Session,
    user: User,
    claim_type: ClaimType = ClaimType.SKILL,
    claim_text: str = "Proficient in Python and asynchronous microservices.",
) -> CandidateClaim:
    """Helper to persist a CandidateClaim."""
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


def create_test_source_and_item(
    db: Session,
    user: User,
    description: str = "Python asyncio code sample in repo.",
) -> tuple[EvidenceSource, EvidenceItem]:
    """Helper to persist an EvidenceSource and an EvidenceItem."""
    source = EvidenceSource(
        user_id=user.id,
        source_type=EvidenceSourceType.GITHUB_REPOSITORY,
        source_uri=f"https://github.com/testcandidate/{uuid.uuid4().hex[:8]}",
        access_mode=AccessMode.PUBLIC,
        access_status=EvidenceSourceStatus.AVAILABLE,
    )
    db.add(source)
    db.commit()
    db.refresh(source)

    item = EvidenceItem(
        evidence_source_id=source.id,
        evidence_type=EvidenceType.CODE_ARTIFACT,
        description=description,
        observed_data={"language": "Python"},
    )
    db.add(item)
    db.commit()
    db.refresh(item)
    return source, item


def get_auth_headers(client: TestClient, email: str) -> dict[str, str]:
    """Helper to register and login a user via API and return Authorization headers."""
    password = "SecurePassword123!"
    client.post(
        "/api/v1/auth/register",
        json={"email": email, "password": password, "name": "API Candidate"},
    )
    res = client.post(
        "/api/v1/auth/login",
        data={"username": email, "password": password},
    )
    token = res.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}


# =============================================================================
# 1. Database-Level Constraint Tests
# =============================================================================


def test_db_candidate_skill_uniqueness_user_and_skill(db: Session) -> None:
    """Verify that (user_id, skill_id) is strictly unique at the database level."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="PostgreSQL", category="Database")

    cs1 = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cs1)
    db.commit()

    cs2 = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cs2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_db_candidate_skill_different_users_same_skill(db: Session) -> None:
    """Verify multiple distinct candidates can associate with the same canonical skill."""
    user1 = create_test_user(db, prefix="user1")
    user2 = create_test_user(db, prefix="user2")
    skill = create_test_skill(db, name="Docker", category="DevOps")

    cs1 = CandidateSkill(user_id=user1.id, skill_id=skill.id)
    cs2 = CandidateSkill(user_id=user2.id, skill_id=skill.id)
    db.add_all([cs1, cs2])
    db.commit()

    assert cs1.id != cs2.id
    assert cs1.user_id == user1.id
    assert cs2.user_id == user2.id


def test_db_candidate_skill_same_user_different_skills(db: Session) -> None:
    """Verify a single candidate can associate with multiple different canonical skills."""
    user = create_test_user(db)
    skill1 = create_test_skill(db, name="FastAPI", category="Framework")
    skill2 = create_test_skill(db, name="Redis", category="Database")

    cs1 = CandidateSkill(user_id=user.id, skill_id=skill1.id)
    cs2 = CandidateSkill(user_id=user.id, skill_id=skill2.id)
    db.add_all([cs1, cs2])
    db.commit()

    assert cs1.skill_id == skill1.id
    assert cs2.skill_id == skill2.id


def test_db_candidate_skill_evidence_both_null_rejected(db: Session) -> None:
    """Verify check constraint rejects CandidateSkillEvidence where both sources are null."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="Rust", category="Programming Language")
    cs = CandidateSkill(user_id=user.id, skill_id=skill.id)
    db.add(cs)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cs.id,
        candidate_claim_id=None,
        evidence_item_id=None,
    )
    db.add(link)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_db_candidate_skill_evidence_both_populated_rejected(db: Session) -> None:
    """Verify check constraint rejects CandidateSkillEvidence where both sources are populated."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="Go", category="Programming Language")
    cs = CandidateSkill(user_id=user.id, skill_id=skill.id)
    claim = create_test_claim(db, user)
    _, item = create_test_source_and_item(db, user)
    db.add(cs)
    db.commit()

    link = CandidateSkillEvidence(
        candidate_skill_id=cs.id,
        candidate_claim_id=claim.id,
        evidence_item_id=item.id,
    )
    db.add(link)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_db_candidate_skill_evidence_duplicate_claim_link_rejected(db: Session) -> None:
    """Verify partial unique index prevents linking the same claim twice to the same candidate skill."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="Kubernetes", category="DevOps")
    cs = CandidateSkill(user_id=user.id, skill_id=skill.id)
    claim = create_test_claim(db, user)
    db.add(cs)
    db.commit()

    link1 = CandidateSkillEvidence(
        candidate_skill_id=cs.id,
        candidate_claim_id=claim.id,
        evidence_item_id=None,
    )
    link2 = CandidateSkillEvidence(
        candidate_skill_id=cs.id,
        candidate_claim_id=claim.id,
        evidence_item_id=None,
    )
    db.add(link1)
    db.commit()

    db.add(link2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_db_candidate_skill_evidence_duplicate_evidence_item_link_rejected(
    db: Session,
) -> None:
    """Verify partial unique index prevents linking the same evidence item twice to the same candidate skill."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="TypeScript", category="Programming Language")
    cs = CandidateSkill(user_id=user.id, skill_id=skill.id)
    _, item = create_test_source_and_item(db, user)
    db.add(cs)
    db.commit()

    link1 = CandidateSkillEvidence(
        candidate_skill_id=cs.id,
        candidate_claim_id=None,
        evidence_item_id=item.id,
    )
    link2 = CandidateSkillEvidence(
        candidate_skill_id=cs.id,
        candidate_claim_id=None,
        evidence_item_id=item.id,
    )
    db.add(link1)
    db.commit()

    db.add(link2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_db_candidate_skill_cascade_delete(db: Session) -> None:
    """Verify deleting a CandidateSkill cascades to CandidateSkillEvidence without deleting the claim or item."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="GraphQL", category="API")
    cs = CandidateSkill(user_id=user.id, skill_id=skill.id)
    claim = create_test_claim(db, user)
    _, item = create_test_source_and_item(db, user)
    db.add(cs)
    db.commit()

    link_claim = CandidateSkillEvidence(
        candidate_skill_id=cs.id,
        candidate_claim_id=claim.id,
        evidence_item_id=None,
    )
    link_item = CandidateSkillEvidence(
        candidate_skill_id=cs.id,
        candidate_claim_id=None,
        evidence_item_id=item.id,
    )
    db.add_all([link_claim, link_item])
    db.commit()

    link_claim_id = link_claim.id
    link_item_id = link_item.id
    claim_id = claim.id
    item_id = item.id

    # Delete candidate skill association
    db.delete(cs)
    db.commit()

    # Join records are cascade-deleted
    assert db.get(CandidateSkillEvidence, link_claim_id) is None
    assert db.get(CandidateSkillEvidence, link_item_id) is None

    # Underlying claim and evidence item remain intact and unmutated
    persisted_claim = db.get(CandidateClaim, claim_id)
    persisted_item = db.get(EvidenceItem, item_id)
    assert persisted_claim is not None
    assert persisted_item is not None


# =============================================================================
# 2. Repository Tests
# =============================================================================


def test_candidate_skill_repository_crud(db: Session) -> None:
    """Test CandidateSkillRepository queries, eager loading, and evidence linking."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="Kafka", category="Streaming")
    claim = create_test_claim(db, user)
    repo = CandidateSkillRepository(db)

    cs = CandidateSkill(user_id=user.id, skill_id=skill.id)
    created = repo.create(cs)
    assert created.id is not None

    # Add evidence link
    link = CandidateSkillEvidence(
        candidate_skill_id=created.id,
        candidate_claim_id=claim.id,
    )
    repo.add_evidence_link(link)

    # Fetch by ID with eager loading
    fetched = repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.skill.canonical_name == "Kafka"
    assert len(fetched.evidence_links) == 1
    assert fetched.evidence_links[0].candidate_claim_id == claim.id

    # Fetch by user and skill
    by_user_skill = repo.get_by_user_and_skill(user.id, skill.id)
    assert by_user_skill is not None
    assert by_user_skill.id == created.id

    # List by user
    all_user_skills = repo.list_by_user(user.id)
    assert len(all_user_skills) == 1
    assert all_user_skills[0].id == created.id

    # Get evidence link
    ev_link = repo.get_evidence_link(created.id, claim_id=claim.id)
    assert ev_link is not None
    assert ev_link.id == link.id

    # Remove
    repo.remove(created.id)
    assert repo.get_by_id(created.id) is None


# =============================================================================
# 3. Service Layer Tests
# =============================================================================


def test_service_create_skill_association_with_claim(db: Session) -> None:
    """Test creating CandidateSkill via CandidateSkillService with claim provenance."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="Django", category="Framework")
    claim = create_test_claim(db, user)
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=skill.id,
        candidate_claim_id=claim.id,
    )
    result = service.create_candidate_skill(user, payload)

    assert isinstance(result, CandidateSkillResponse)
    assert result.user_id == user.id
    assert result.skill_id == skill.id
    assert result.skill is not None
    assert result.skill.canonical_name == "Django"
    assert len(result.evidence_links) == 1
    assert result.evidence_links[0].candidate_claim_id == claim.id
    assert result.evidence_links[0].evidence_item_id is None


def test_service_create_skill_association_with_evidence_item(db: Session) -> None:
    """Test creating CandidateSkill via CandidateSkillService with evidence item provenance."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="C++", category="Programming Language")
    _, item = create_test_source_and_item(db, user)
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=skill.id,
        evidence_item_id=item.id,
    )
    result = service.create_candidate_skill(user, payload)

    assert result.user_id == user.id
    assert result.skill_id == skill.id
    assert len(result.evidence_links) == 1
    assert result.evidence_links[0].evidence_item_id == item.id
    assert result.evidence_links[0].candidate_claim_id is None


def test_service_create_skill_association_with_multiple_provenance_sources(
    db: Session,
) -> None:
    """Test creating CandidateSkill with both claim and evidence item provenance."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="AWS", category="Cloud")
    claim = create_test_claim(db, user)
    _, item = create_test_source_and_item(db, user)
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=skill.id,
        evidence=[
            CandidateSkillEvidenceCreate(candidate_claim_id=claim.id),
            CandidateSkillEvidenceCreate(evidence_item_id=item.id),
        ],
    )
    result = service.create_candidate_skill(user, payload)

    assert len(result.evidence_links) == 2
    claim_links = [
        link for link in result.evidence_links if link.candidate_claim_id == claim.id
    ]
    item_links = [
        link for link in result.evidence_links if link.evidence_item_id == item.id
    ]
    assert len(claim_links) == 1
    assert len(item_links) == 1


def test_service_create_skill_association_rejects_missing_skill(db: Session) -> None:
    """Test service raises 404 if canonical skill is not in catalog."""
    user = create_test_user(db)
    claim = create_test_claim(db, user)
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=uuid.uuid4(),
        candidate_claim_id=claim.id,
    )
    with pytest.raises(HTTPException) as exc_info:
        service.create_candidate_skill(user, payload)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Canonical skill" in exc_info.value.detail


def test_service_create_skill_association_rejects_missing_claim(db: Session) -> None:
    """Test service raises 404 if referenced claim ID does not exist."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="RabbitMQ", category="Message Broker")
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=skill.id,
        candidate_claim_id=uuid.uuid4(),
    )
    with pytest.raises(HTTPException) as exc_info:
        service.create_candidate_skill(user, payload)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Candidate claim" in exc_info.value.detail


def test_service_create_skill_association_rejects_missing_evidence_item(
    db: Session,
) -> None:
    """Test service raises 404 if referenced evidence item ID does not exist."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="MongoDB", category="Database")
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=skill.id,
        evidence_item_id=uuid.uuid4(),
    )
    with pytest.raises(HTTPException) as exc_info:
        service.create_candidate_skill(user, payload)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Evidence item" in exc_info.value.detail


def test_service_create_skill_association_rejects_other_user_claim(
    db: Session,
) -> None:
    """Test service raises 400 if referenced claim belongs to another candidate."""
    user1 = create_test_user(db, prefix="cand1")
    user2 = create_test_user(db, prefix="cand2")
    skill = create_test_skill(db, name="Golang", category="Programming Language")
    foreign_claim = create_test_claim(db, user2)
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=skill.id,
        candidate_claim_id=foreign_claim.id,
    )
    with pytest.raises(HTTPException) as exc_info:
        service.create_candidate_skill(user1, payload)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "belongs to a different candidate" in exc_info.value.detail


def test_service_create_skill_association_rejects_other_user_evidence_item(
    db: Session,
) -> None:
    """Test service raises 400 if referenced evidence item belongs to another candidate."""
    user1 = create_test_user(db, prefix="cand1")
    user2 = create_test_user(db, prefix="cand2")
    skill = create_test_skill(db, name="Terraform", category="DevOps")
    _, foreign_item = create_test_source_and_item(db, user2)
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=skill.id,
        evidence_item_id=foreign_item.id,
    )
    with pytest.raises(HTTPException) as exc_info:
        service.create_candidate_skill(user1, payload)
    assert exc_info.value.status_code == status.HTTP_400_BAD_REQUEST
    assert "belongs to a different candidate" in exc_info.value.detail


def test_service_create_skill_association_rejects_duplicate(db: Session) -> None:
    """Test service raises 409 Conflict if association for user and skill already exists."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="React", category="Frontend")
    claim = create_test_claim(db, user)
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=skill.id,
        candidate_claim_id=claim.id,
    )
    service.create_candidate_skill(user, payload)

    with pytest.raises(HTTPException) as exc_info:
        service.create_candidate_skill(user, payload)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "already has an association" in exc_info.value.detail


def test_service_add_evidence_link_and_reject_duplicates(db: Session) -> None:
    """Test adding additional evidence link to existing association and rejecting duplicates."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="Kubernetes", category="DevOps")
    claim1 = create_test_claim(db, user, claim_text="Kubernetes cluster management")
    claim2 = create_test_claim(db, user, claim_text="Helm chart deployments")
    service = CandidateSkillService(db)

    created = service.create_candidate_skill(
        user,
        CandidateSkillCreate(skill_id=skill.id, candidate_claim_id=claim1.id),
    )
    assert len(created.evidence_links) == 1

    # Attach claim2
    updated = service.add_evidence_link(
        user,
        created.id,
        CandidateSkillEvidenceCreate(candidate_claim_id=claim2.id),
    )
    assert len(updated.evidence_links) == 2

    # Attempt to attach claim2 again -> 409
    with pytest.raises(HTTPException) as exc_info:
        service.add_evidence_link(
            user,
            created.id,
            CandidateSkillEvidenceCreate(candidate_claim_id=claim2.id),
        )
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT


def test_service_get_and_delete_candidate_skill_ownership(db: Session) -> None:
    """Test that candidate skill retrieval and deletion enforce candidate ownership."""
    user1 = create_test_user(db, prefix="owner")
    user2 = create_test_user(db, prefix="stranger")
    skill = create_test_skill(db, name="Redis", category="Database")
    claim = create_test_claim(db, user1)
    service = CandidateSkillService(db)

    created = service.create_candidate_skill(
        user1,
        CandidateSkillCreate(skill_id=skill.id, candidate_claim_id=claim.id),
    )

    # Owner can get
    res = service.get_candidate_skill(user1, created.id)
    assert res.id == created.id

    # Stranger cannot get -> 404
    with pytest.raises(HTTPException) as exc_info:
        service.get_candidate_skill(user2, created.id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    # Stranger cannot delete -> 404
    with pytest.raises(HTTPException) as exc_info:
        service.delete_candidate_skill(user2, created.id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    # Owner deletes
    service.delete_candidate_skill(user1, created.id)
    with pytest.raises(HTTPException) as exc_info:
        service.get_candidate_skill(user1, created.id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_service_no_mutation_side_effects_on_claims_or_evidence(db: Session) -> None:
    """Verify creating and deleting skill associations does not mutate underlying claims or evidence."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="Postgres", category="Database")
    claim = create_test_claim(db, user, claim_text="Database architecture")
    source, item = create_test_source_and_item(db, user, description="Postgres repo")
    service = CandidateSkillService(db)

    original_claim_text = claim.claim_text
    original_claim_origin = claim.origin
    original_item_desc = item.description
    original_item_observed = item.observed_data
    original_source_status = source.access_status

    created = service.create_candidate_skill(
        user,
        CandidateSkillCreate(
            skill_id=skill.id,
            evidence=[
                CandidateSkillEvidenceCreate(candidate_claim_id=claim.id),
                CandidateSkillEvidenceCreate(evidence_item_id=item.id),
            ],
        ),
    )
    service.delete_candidate_skill(user, created.id)

    db.refresh(claim)
    db.refresh(item)
    db.refresh(source)

    assert claim.claim_text == original_claim_text
    assert claim.origin == original_claim_origin
    assert item.description == original_item_desc
    assert item.observed_data == original_item_observed
    assert source.access_status == original_source_status


# =============================================================================
# 4. API Endpoint & Security Tests
# =============================================================================


def test_api_unauthenticated_requests_rejected(client: TestClient) -> None:
    """Verify unauthenticated requests to /candidate-skills return 401."""
    res_get = client.get("/api/v1/candidate-skills")
    assert res_get.status_code == status.HTTP_401_UNAUTHORIZED

    res_post = client.post(
        "/api/v1/candidate-skills",
        json={"skill_id": str(uuid.uuid4())},
    )
    assert res_post.status_code == status.HTTP_401_UNAUTHORIZED

    res_del = client.delete(f"/api/v1/candidate-skills/{uuid.uuid4()}")
    assert res_del.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_create_and_get_candidate_skill(client: TestClient, db: Session) -> None:
    """Test full authenticated workflow: create candidate skill and get by ID."""
    email = f"api_candidate_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)

    # Get user model from db
    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    skill = create_test_skill(db, name="FastAPI", category="Framework")
    claim = create_test_claim(db, user)

    # 1. Create candidate skill
    create_payload = {
        "skill_id": str(skill.id),
        "candidate_claim_id": str(claim.id),
    }
    res_create = client.post(
        "/api/v1/candidate-skills", json=create_payload, headers=headers
    )
    assert res_create.status_code == status.HTTP_201_CREATED
    data = res_create.json()
    assert data["skill_id"] == str(skill.id)
    assert data["user_id"] == str(user.id)
    assert len(data["evidence_links"]) == 1
    assert data["evidence_links"][0]["candidate_claim_id"] == str(claim.id)
    created_id = data["id"]

    # 2. Get by ID
    res_get = client.get(f"/api/v1/candidate-skills/{created_id}", headers=headers)
    assert res_get.status_code == status.HTTP_200_OK
    assert res_get.json()["id"] == created_id

    # 3. List
    res_list = client.get("/api/v1/candidate-skills", headers=headers)
    assert res_list.status_code == status.HTTP_200_OK
    items = res_list.json()
    assert len(items) == 1
    assert items[0]["id"] == created_id

    # 4. Check alias path /api/v1/candidate-profile/skills
    res_alias = client.get("/api/v1/candidate-profile/skills", headers=headers)
    assert res_alias.status_code == status.HTTP_200_OK
    assert len(res_alias.json()) == 1


def test_api_attach_evidence_to_candidate_skill(
    client: TestClient, db: Session
) -> None:
    """Test attaching evidence item to existing candidate skill via POST /candidate-skills/{id}/evidence."""
    email = f"api_attach_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)
    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    skill = create_test_skill(db, name="Docker", category="DevOps")
    claim = create_test_claim(db, user)
    _, item = create_test_source_and_item(db, user)

    # Create with initial claim
    res_create = client.post(
        "/api/v1/candidate-skills",
        json={"skill_id": str(skill.id), "candidate_claim_id": str(claim.id)},
        headers=headers,
    )
    created_id = res_create.json()["id"]

    # Attach evidence item
    res_attach = client.post(
        f"/api/v1/candidate-skills/{created_id}/evidence",
        json={"evidence_item_id": str(item.id)},
        headers=headers,
    )
    assert res_attach.status_code == status.HTTP_201_CREATED
    updated = res_attach.json()
    assert len(updated["evidence_links"]) == 2


def test_api_delete_candidate_skill(client: TestClient, db: Session) -> None:
    """Test deleting candidate skill via DELETE /candidate-skills/{id}."""
    email = f"api_del_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)
    user = db.query(User).filter(User.email == email).first()
    assert user is not None
    skill = create_test_skill(db, name="PyTest", category="Testing")
    claim = create_test_claim(db, user)

    res_create = client.post(
        "/api/v1/candidate-skills",
        json={"skill_id": str(skill.id), "candidate_claim_id": str(claim.id)},
        headers=headers,
    )
    created_id = res_create.json()["id"]

    # Delete
    res_del = client.delete(f"/api/v1/candidate-skills/{created_id}", headers=headers)
    assert res_del.status_code == status.HTTP_204_NO_CONTENT

    # Verify not found
    res_get = client.get(f"/api/v1/candidate-skills/{created_id}", headers=headers)
    assert res_get.status_code == status.HTTP_404_NOT_FOUND


def test_api_create_rejects_missing_provenance(client: TestClient, db: Session) -> None:
    """Test creating association with no evidence links is rejected with 422."""
    email = f"api_noprov_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)
    skill = create_test_skill(db, name="Scala", category="Programming Language")

    res = client.post(
        "/api/v1/candidate-skills",
        json={"skill_id": str(skill.id)},
        headers=headers,
    )
    assert res.status_code in (
        status.HTTP_422_UNPROCESSABLE_ENTITY,
        422,
    )


def test_api_create_rejects_cross_candidate_reference(
    client: TestClient, db: Session
) -> None:
    """Test API rejects attempting to associate a skill using another user's claim."""
    email1 = f"cand1_{uuid.uuid4().hex[:6]}@nextround.in"
    email2 = f"cand2_{uuid.uuid4().hex[:6]}@nextround.in"
    headers1 = get_auth_headers(client, email1)
    _ = get_auth_headers(client, email2)

    user2 = db.query(User).filter(User.email == email2).first()
    assert user2 is not None
    skill = create_test_skill(db, name="Elixir", category="Programming Language")
    foreign_claim = create_test_claim(db, user2)

    res = client.post(
        "/api/v1/candidate-skills",
        json={"skill_id": str(skill.id), "candidate_claim_id": str(foreign_claim.id)},
        headers=headers1,
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "belongs to a different candidate" in res.json()["detail"]


# =============================================================================
# 5. Concurrency & Dialect Compilation Tests
# =============================================================================


def test_service_concurrent_duplicate_association_handling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that concurrent duplicate creation hitting the database unique constraint raises 409 Conflict."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="C#", category="Programming Language")
    claim = create_test_claim(db, user)
    service = CandidateSkillService(db)

    payload = CandidateSkillCreate(
        skill_id=skill.id,
        candidate_claim_id=claim.id,
    )

    # First insert succeeds
    service.create_candidate_skill(user, payload)

    # Simulate race condition where repo.get_by_user_and_skill returns None
    monkeypatch.setattr(
        service.candidate_skill_repo, "get_by_user_and_skill", lambda uid, sid: None
    )
    with pytest.raises(HTTPException) as exc_info:
        service.create_candidate_skill(user, payload)
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "already has an association" in exc_info.value.detail


def test_service_concurrent_duplicate_evidence_link_handling(
    db: Session, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Test that concurrent duplicate evidence link hitting partial unique index raises 409 Conflict."""
    user = create_test_user(db)
    skill = create_test_skill(db, name="Kotlin", category="Programming Language")
    claim = create_test_claim(db, user)
    service = CandidateSkillService(db)

    created = service.create_candidate_skill(
        user,
        CandidateSkillCreate(skill_id=skill.id, candidate_claim_id=claim.id),
    )

    # Simulate race condition where get_evidence_link returns None, but db commit hits duplicate constraint
    monkeypatch.setattr(
        service.candidate_skill_repo,
        "get_evidence_link",
        lambda cs_id, **kwargs: None,
    )
    with pytest.raises(HTTPException) as exc_info:
        service.add_evidence_link(
            user,
            created.id,
            CandidateSkillEvidenceCreate(candidate_claim_id=claim.id),
        )
    assert exc_info.value.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in exc_info.value.detail


def test_postgresql_dialect_ddl_compilation() -> None:
    """Verify that models compile valid PostgreSQL DDL with partial indexes and check constraints."""
    from typing import cast

    from sqlalchemy import Table
    from sqlalchemy.dialects import postgresql
    from sqlalchemy.schema import CreateIndex, CreateTable

    pg_dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    cs_table = cast(Table, CandidateSkill.__table__)
    cse_table = cast(Table, CandidateSkillEvidence.__table__)

    # CandidateSkill
    cs_ddl = str(CreateTable(cs_table).compile(dialect=pg_dialect))
    assert (
        "CONSTRAINT uq_candidate_skills_user_skill UNIQUE (user_id, skill_id)" in cs_ddl
    )
    assert "FOREIGN KEY(user_id) REFERENCES users (id) ON DELETE CASCADE" in cs_ddl
    assert "FOREIGN KEY(skill_id) REFERENCES skills (id) ON DELETE RESTRICT" in cs_ddl

    # CandidateSkillEvidence
    cse_ddl = str(CreateTable(cse_table).compile(dialect=pg_dialect))
    assert "CONSTRAINT ck_candidate_skill_evidence_exactly_one_source CHECK" in cse_ddl
    assert (
        "FOREIGN KEY(candidate_skill_id) REFERENCES candidate_skills (id) ON DELETE CASCADE"
        in cse_ddl
    )
    assert (
        "FOREIGN KEY(candidate_claim_id) REFERENCES candidate_claims (id) ON DELETE RESTRICT"
        in cse_ddl
    )
    assert (
        "FOREIGN KEY(evidence_item_id) REFERENCES evidence_items (id) ON DELETE RESTRICT"
        in cse_ddl
    )

    # Check partial unique indexes
    indexes_ddl = [
        str(CreateIndex(idx).compile(dialect=pg_dialect)) for idx in cse_table.indexes
    ]
    claim_idx = [
        s for s in indexes_ddl if "uq_candidate_skill_evidence_skill_claim" in s
    ]
    item_idx = [s for s in indexes_ddl if "uq_candidate_skill_evidence_skill_item" in s]
    assert len(claim_idx) == 1
    assert "WHERE candidate_claim_id IS NOT NULL" in claim_idx[0]
    assert len(item_idx) == 1
    assert "WHERE evidence_item_id IS NOT NULL" in item_idx[0]
