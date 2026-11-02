import uuid
from typing import cast

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy import Table, text
from sqlalchemy.dialects import postgresql
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session
from sqlalchemy.schema import CreateIndex, CreateTable

from app.models.candidate_profile import CandidateProfile
from app.models.candidate_target import CandidateTarget
from app.models.role_requirement import (
    RequirementImportance,
    RequirementSourceType,
    RequirementType,
    RoleRequirement,
)
from app.models.skill import Skill
from app.models.user import User
from app.schemas.candidate_target import CandidateTargetCreate
from app.schemas.role_requirement import (
    RoleRequirementCreate,
)
from app.services.candidate_service import CandidateService
from app.services.role_requirement_service import RoleRequirementService


def create_test_user(db: Session, email_prefix: str = "req_user") -> User:
    """Create a unique test user in the database."""
    unique_email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@nextround.in"
    user = User(
        email=unique_email,
        hashed_password="hashed_test_password",
        name="Test Candidate",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_test_profile_and_target(
    db: Session, user: User, role_title: str = "Senior Backend Engineer"
) -> tuple[CandidateProfile, CandidateTarget]:
    """Create a profile and candidate target for the test user."""
    service = CandidateService(db)
    profile = service.get_or_create_profile(user)
    target = service.create_target(
        user,
        CandidateTargetCreate(
            role_title=role_title,
            company="NextRound Tech",
            job_description="Seeking a backend engineer with Python, FastAPI, and PostgreSQL experience.",
            is_active=True,
        ),
    )
    db_target = db.query(CandidateTarget).filter(CandidateTarget.id == target.id).one()
    return profile, db_target


def create_test_skill(
    db: Session,
    name: str = "Python",
    category: str = "Programming Language",
) -> Skill:
    """Create a canonical test skill in the database."""
    skill = Skill(
        canonical_name=name,
        category=category,
        aliases=["py", "python3"],
    )
    db.add(skill)
    db.commit()
    db.refresh(skill)
    return skill


def get_auth_headers(client: TestClient, email: str) -> dict[str, str]:
    """Helper to register/authenticate a candidate and return Authorization headers."""
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
# 1. Schema & Enum Validation Tests
# =============================================================================


def test_schema_valid_role_requirement_unmapped() -> None:
    """Validate creating an unmapped role requirement schema with skill_id=None."""
    req_in = RoleRequirementCreate(
        skill_id=None,
        requirement_text="5+ years of experience designing distributed systems",
        requirement_type=RequirementType.EXPERIENCE,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    assert req_in.skill_id is None
    assert (
        req_in.requirement_text
        == "5+ years of experience designing distributed systems"
    )
    assert req_in.requirement_type == RequirementType.EXPERIENCE
    assert req_in.importance == RequirementImportance.REQUIRED
    assert req_in.source_type == RequirementSourceType.JOB_DESCRIPTION


def test_schema_valid_role_requirement_mapped() -> None:
    """Validate creating a mapped role requirement schema with a valid skill_id."""
    skill_id = uuid.uuid4()
    req_in = RoleRequirementCreate(
        skill_id=skill_id,
        requirement_text="Proficiency in Python and async paradigms",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.CURATED_ROLE,
    )
    assert req_in.skill_id == skill_id
    assert req_in.requirement_text == "Proficiency in Python and async paradigms"
    assert req_in.requirement_type == RequirementType.SKILL
    assert req_in.importance == RequirementImportance.REQUIRED
    assert req_in.source_type == RequirementSourceType.CURATED_ROLE


def test_schema_rejects_empty_or_whitespace_text() -> None:
    """Validate that empty or whitespace-only requirement text is rejected by schema validator."""
    with pytest.raises(
        ValueError, match="Requirement text cannot be empty or whitespace-only"
    ):
        RoleRequirementCreate(
            skill_id=None,
            requirement_text="   ",
            requirement_type=RequirementType.SKILL,
            importance=RequirementImportance.REQUIRED,
            source_type=RequirementSourceType.JOB_DESCRIPTION,
        )

    with pytest.raises(
        ValueError, match="Requirement text cannot be empty or whitespace-only"
    ):
        RoleRequirementCreate(
            skill_id=None,
            requirement_text="",
            requirement_type=RequirementType.SKILL,
            importance=RequirementImportance.REQUIRED,
            source_type=RequirementSourceType.JOB_DESCRIPTION,
        )


def test_schema_and_service_preserve_whitespace_verbatim(db: Session) -> None:
    """
    Regression test: verify that leading and trailing whitespace is NOT stripped
    from valid original requirement text, strictly honoring contract requirement to preserve wording.
    """
    user = create_test_user(db)
    _, target = create_test_profile_and_target(db, user)
    service = RoleRequirementService(db)

    raw_text = "  Proficient in event-driven architectures and message brokers  "
    payload = RoleRequirementCreate(
        skill_id=None,
        requirement_text=raw_text,
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    # Schema preserves original whitespace
    assert payload.requirement_text == raw_text
    assert payload.requirement_text.startswith("  ")
    assert payload.requirement_text.endswith("  ")

    # Service persists verbatim without trimming
    created = service.create_requirement(user, target.id, payload)
    assert created.requirement_text == raw_text
    assert created.requirement_text.startswith("  ")

    # DB reload check
    reloaded = service.get_requirement(user, target.id, created.id)
    assert reloaded.requirement_text == raw_text


def test_schema_rejects_invalid_enums() -> None:
    """Validate that unrecognized enum values are rejected by schema."""
    with pytest.raises(ValueError):
        RoleRequirementCreate.model_validate(
            {
                "requirement_text": "BS in Computer Science",
                "requirement_type": "INVALID_TYPE",
                "importance": "REQUIRED",
                "source_type": "JOB_DESCRIPTION",
            }
        )

    with pytest.raises(ValueError):
        RoleRequirementCreate.model_validate(
            {
                "requirement_text": "BS in Computer Science",
                "requirement_type": "QUALIFICATION",
                "importance": "CRITICAL",  # Invalid enum value
                "source_type": "JOB_DESCRIPTION",
            }
        )

    with pytest.raises(ValueError):
        RoleRequirementCreate.model_validate(
            {
                "requirement_text": "BS in Computer Science",
                "requirement_type": "QUALIFICATION",
                "importance": "REQUIRED",
                "source_type": "AI_INFERRED",  # Invalid source type
            }
        )


# =============================================================================
# 2. Database Constraint & Cascade Tests
# =============================================================================


def test_db_role_requirement_text_not_empty_constraint(db: Session) -> None:
    """Direct database test verifying check constraint ck_role_requirements_text_not_empty."""
    user = create_test_user(db)
    _, target = create_test_profile_and_target(db, user)

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=None,
        requirement_text="   ",  # Fails length(trim(text)) > 0
        requirement_type=RequirementType.OTHER,
        importance=RequirementImportance.UNSPECIFIED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_db_role_requirement_target_restrict_delete(db: Session) -> None:
    """Direct database test verifying that deleting a candidate target with requirements is restricted."""
    if db.bind and db.bind.dialect.name == "sqlite":
        db.execute(text("PRAGMA foreign_keys = ON"))

    user = create_test_user(db)
    _, target = create_test_profile_and_target(db, user)

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=None,
        requirement_text="Must have experience with microservices",
        requirement_type=RequirementType.EXPERIENCE,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )
    db.add(req)
    db.commit()

    # Attempt to delete target must fail due to ON DELETE RESTRICT
    db.delete(target)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_db_role_requirement_skill_restrict_delete(db: Session) -> None:
    """Direct database test verifying that deleting a canonical skill referenced by requirement is restricted."""
    if db.bind and db.bind.dialect.name == "sqlite":
        db.execute(text("PRAGMA foreign_keys = ON"))

    user = create_test_user(db)
    _, target = create_test_profile_and_target(db, user)
    skill = create_test_skill(db, name="Rust", category="Programming Language")

    req = RoleRequirement(
        candidate_target_id=target.id,
        skill_id=skill.id,
        requirement_text="Strong fluency in Rust systems programming",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.CURATED_ROLE,
    )
    db.add(req)
    db.commit()

    # Attempt to delete skill must fail due to ON DELETE RESTRICT
    db.delete(skill)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# =============================================================================
# 3. Service Layer & Domain Invariants Tests
# =============================================================================


def test_service_create_unmapped_requirement(db: Session) -> None:
    """Verify service creates an unmapped requirement with skill_id=None and exact text."""
    user = create_test_user(db)
    _, target = create_test_profile_and_target(db, user)
    service = RoleRequirementService(db)

    payload = RoleRequirementCreate(
        skill_id=None,
        requirement_text="B.S. or M.S. in Computer Science or related engineering field",
        requirement_type=RequirementType.QUALIFICATION,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )

    created = service.create_requirement(user, target.id, payload)
    assert created.id is not None
    assert created.candidate_target_id == target.id
    assert created.skill_id is None
    assert (
        created.requirement_text
        == "B.S. or M.S. in Computer Science or related engineering field"
    )
    assert created.requirement_type == RequirementType.QUALIFICATION
    assert created.importance == RequirementImportance.REQUIRED
    assert created.source_type == RequirementSourceType.JOB_DESCRIPTION


def test_service_create_mapped_requirement(db: Session) -> None:
    """Verify service creates a requirement mapped to an existing canonical skill."""
    user = create_test_user(db)
    _, target = create_test_profile_and_target(db, user)
    skill = create_test_skill(db, name="PostgreSQL", category="Database")
    service = RoleRequirementService(db)

    payload = RoleRequirementCreate(
        skill_id=skill.id,
        requirement_text="Hands-on experience with PostgreSQL query optimization and indexing",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.CURATED_ROLE,
    )

    created = service.create_requirement(user, target.id, payload)
    assert created.skill_id == skill.id
    assert (
        created.requirement_text
        == "Hands-on experience with PostgreSQL query optimization and indexing"
    )


def test_service_create_preserves_original_text_without_canonical_substitution(
    db: Session,
) -> None:
    """Verify that requirement text is preserved verbatim and NOT replaced with the canonical skill name."""
    user = create_test_user(db)
    _, target = create_test_profile_and_target(db, user)
    skill = create_test_skill(db, name="Kubernetes", category="DevOps")
    service = RoleRequirementService(db)

    custom_text = "Familiarity with container orchestration tools like Kube / k8s cluster operations"
    payload = RoleRequirementCreate(
        skill_id=skill.id,
        requirement_text=custom_text,
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.PREFERRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )

    created = service.create_requirement(user, target.id, payload)
    # Must preserve custom_text verbatim, NOT replace with skill.canonical_name ("Kubernetes")
    assert created.requirement_text == custom_text
    assert created.requirement_text != skill.canonical_name


def test_service_create_rejects_missing_canonical_skill(db: Session) -> None:
    """Verify that referencing a non-existent skill ID returns 404 Not Found."""
    user = create_test_user(db)
    _, target = create_test_profile_and_target(db, user)
    service = RoleRequirementService(db)

    missing_skill_id = uuid.uuid4()
    payload = RoleRequirementCreate(
        skill_id=missing_skill_id,
        requirement_text="Experience with NonExistentSkill",
        requirement_type=RequirementType.SKILL,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )

    with pytest.raises(HTTPException) as exc_info:
        service.create_requirement(user, target.id, payload)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert (
        f"Canonical skill {missing_skill_id} not found in catalog."
        in exc_info.value.detail
    )


def test_service_rejects_unowned_or_missing_target(db: Session) -> None:
    """Verify that attempting to create or list requirements for an unowned target returns 404."""
    user1 = create_test_user(db, email_prefix="user1")
    user2 = create_test_user(db, email_prefix="user2")
    _, target1 = create_test_profile_and_target(db, user1)
    service = RoleRequirementService(db)

    payload = RoleRequirementCreate(
        skill_id=None,
        requirement_text="Experience with CI/CD pipelines",
        requirement_type=RequirementType.EXPERIENCE,
        importance=RequirementImportance.REQUIRED,
        source_type=RequirementSourceType.JOB_DESCRIPTION,
    )

    # User 2 attempting to operate on User 1's target
    with pytest.raises(HTTPException) as exc_info:
        service.create_requirement(user2, target1.id, payload)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND
    assert "Candidate target not found." in exc_info.value.detail

    with pytest.raises(HTTPException) as exc_info:
        service.list_requirements(user2, target1.id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    # Non-existent target ID
    with pytest.raises(HTTPException) as exc_info:
        service.create_requirement(user1, uuid.uuid4(), payload)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


def test_requirement_history_across_target_switching_and_deactivation(
    db: Session,
) -> None:
    """
    Verify that requirements remain strictly attached to their target configuration.
    Switching active target or deactivating target does NOT delete or auto-transfer requirements.
    """
    user = create_test_user(db)
    cand_service = CandidateService(db)
    req_service = RoleRequirementService(db)

    # 1. Create Target A (Active) with 2 requirements
    cand_service.get_or_create_profile(user)
    target_a_dto = cand_service.create_target(
        user,
        CandidateTargetCreate(
            role_title="Backend Engineer",
            company="Startup A",
            is_active=True,
        ),
    )
    req_a1 = req_service.create_requirement(
        user,
        target_a_dto.id,
        RoleRequirementCreate(
            skill_id=None,
            requirement_text="3+ years Python experience",
            requirement_type=RequirementType.EXPERIENCE,
            importance=RequirementImportance.REQUIRED,
            source_type=RequirementSourceType.JOB_DESCRIPTION,
        ),
    )
    req_a2 = req_service.create_requirement(
        user,
        target_a_dto.id,
        RoleRequirementCreate(
            skill_id=None,
            requirement_text="Knowledge of Redis caching",
            requirement_type=RequirementType.SKILL,
            importance=RequirementImportance.PREFERRED,
            source_type=RequirementSourceType.JOB_DESCRIPTION,
        ),
    )

    # 2. Create Target B (Active), which automatically deactivates Target A
    target_b_dto = cand_service.create_target(
        user,
        CandidateTargetCreate(
            role_title="Data Platform Engineer",
            company="BigCo B",
            is_active=True,
        ),
    )
    req_b1 = req_service.create_requirement(
        user,
        target_b_dto.id,
        RoleRequirementCreate(
            skill_id=None,
            requirement_text="Experience with Apache Spark / Databricks",
            requirement_type=RequirementType.SKILL,
            importance=RequirementImportance.REQUIRED,
            source_type=RequirementSourceType.JOB_DESCRIPTION,
        ),
    )

    # 3. Verify Target A still has its 2 requirements and Target B has its 1 requirement
    reqs_a = req_service.list_requirements(user, target_a_dto.id)
    assert len(reqs_a) == 2
    assert {r.id for r in reqs_a} == {req_a1.id, req_a2.id}

    reqs_b = req_service.list_requirements(user, target_b_dto.id)
    assert len(reqs_b) == 1
    assert reqs_b[0].id == req_b1.id

    # 4. Deactivate Target B
    cand_service.deactivate_target(user, target_b_dto.id)

    # 5. Verify requirements for both targets are completely preserved
    reqs_b_after = req_service.list_requirements(user, target_b_dto.id)
    assert len(reqs_b_after) == 1
    assert reqs_b_after[0].id == req_b1.id

    reqs_a_after = req_service.list_requirements(user, target_a_dto.id)
    assert len(reqs_a_after) == 2


# =============================================================================
# 4. Authenticated API Endpoints Tests
# =============================================================================


def test_api_unauthenticated_requests_rejected(client: TestClient) -> None:
    """Verify that unauthenticated requests return 401 Unauthorized."""
    tid = uuid.uuid4()

    res_post = client.post(
        f"/api/v1/candidate-targets/{tid}/requirements",
        json={"requirement_text": "Python 3"},
    )
    assert res_post.status_code == status.HTTP_401_UNAUTHORIZED

    res_get = client.get(f"/api/v1/candidate-targets/{tid}/requirements")
    assert res_get.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_create_and_list_target_requirements(
    client: TestClient, db: Session
) -> None:
    """Test full authenticated API workflow: create requirement and list by target."""
    email = f"api_req_{uuid.uuid4().hex[:6]}@nextround.in"
    headers = get_auth_headers(client, email)

    user = db.query(User).filter(User.email == email).one()
    skill = create_test_skill(db, name="FastAPI", category="Framework")
    _, target = create_test_profile_and_target(db, user)

    # 1. Create mapped requirement
    req_payload = {
        "skill_id": str(skill.id),
        "requirement_text": "3+ years building production APIs with FastAPI",
        "requirement_type": "SKILL",
        "importance": "REQUIRED",
        "source_type": "CURATED_ROLE",
    }
    res_create = client.post(
        f"/api/v1/candidate-targets/{target.id}/requirements",
        json=req_payload,
        headers=headers,
    )
    assert res_create.status_code == status.HTTP_201_CREATED
    data = res_create.json()
    assert data["candidate_target_id"] == str(target.id)
    assert data["skill_id"] == str(skill.id)
    assert data["requirement_text"] == "3+ years building production APIs with FastAPI"
    assert data["requirement_type"] == "SKILL"
    assert data["importance"] == "REQUIRED"
    assert data["source_type"] == "CURATED_ROLE"
    created_id = data["id"]

    # 2. Create unmapped requirement
    unmapped_payload = {
        "skill_id": None,
        "requirement_text": "Experience leading agile sprint retrospectives",
        "requirement_type": "EXPERIENCE",
        "importance": "PREFERRED",
        "source_type": "JOB_DESCRIPTION",
    }
    res_unmapped = client.post(
        f"/api/v1/candidate-targets/{target.id}/requirements",
        json=unmapped_payload,
        headers=headers,
    )
    assert res_unmapped.status_code == status.HTTP_201_CREATED

    # 3. List requirements
    res_list = client.get(
        f"/api/v1/candidate-targets/{target.id}/requirements",
        headers=headers,
    )
    assert res_list.status_code == status.HTTP_200_OK
    items = res_list.json()
    assert len(items) == 2

    # 4. Filter by requirement_type
    res_filter = client.get(
        f"/api/v1/candidate-targets/{target.id}/requirements?requirement_type=SKILL",
        headers=headers,
    )
    assert res_filter.status_code == status.HTTP_200_OK
    skill_items = res_filter.json()
    assert len(skill_items) == 1
    assert skill_items[0]["id"] == created_id

    # 5. Get by ID
    res_get = client.get(
        f"/api/v1/candidate-targets/{target.id}/requirements/{created_id}",
        headers=headers,
    )
    assert res_get.status_code == status.HTTP_200_OK
    assert res_get.json()["id"] == created_id


def test_api_cross_candidate_isolation(client: TestClient, db: Session) -> None:
    """Verify API prevents accessing or creating requirements across candidates."""
    email1 = f"cand1_{uuid.uuid4().hex[:6]}@nextround.in"
    email2 = f"cand2_{uuid.uuid4().hex[:6]}@nextround.in"
    _ = get_auth_headers(client, email1)
    headers2 = get_auth_headers(client, email2)

    user1 = db.query(User).filter(User.email == email1).one()
    _, target1 = create_test_profile_and_target(db, user1)

    # User 2 tries to create requirement on User 1's target
    res_post = client.post(
        f"/api/v1/candidate-targets/{target1.id}/requirements",
        json={
            "requirement_text": "Unauthorized requirement creation",
            "requirement_type": "SKILL",
            "importance": "REQUIRED",
            "source_type": "JOB_DESCRIPTION",
        },
        headers=headers2,
    )
    assert res_post.status_code == status.HTTP_404_NOT_FOUND
    assert "Candidate target not found." in res_post.json()["detail"]

    # User 2 tries to list requirements on User 1's target
    res_list = client.get(
        f"/api/v1/candidate-targets/{target1.id}/requirements",
        headers=headers2,
    )
    assert res_list.status_code == status.HTTP_404_NOT_FOUND


# =============================================================================
# 5. Dialect DDL Compilation Test
# =============================================================================


def test_postgresql_dialect_ddl_compilation() -> None:
    """Verify that RoleRequirement compiles valid PostgreSQL DDL with foreign keys and check constraint."""
    pg_dialect = postgresql.dialect()  # type: ignore[no-untyped-call]
    table = cast(Table, RoleRequirement.__table__)

    ddl = str(CreateTable(table).compile(dialect=pg_dialect))

    # Foreign Keys
    assert (
        "FOREIGN KEY(candidate_target_id) REFERENCES candidate_targets (id) ON DELETE RESTRICT"
        in ddl
    )
    assert "FOREIGN KEY(skill_id) REFERENCES skills (id) ON DELETE RESTRICT" in ddl

    # Check Constraint
    assert (
        "CONSTRAINT ck_role_requirements_text_not_empty CHECK (length(trim(requirement_text)) > 0)"
        in ddl
    )

    # Indexes
    indexes_ddl = [
        str(CreateIndex(idx).compile(dialect=pg_dialect)) for idx in table.indexes
    ]
    target_idx = [
        s for s in indexes_ddl if "ix_role_requirements_candidate_target_id" in s
    ]
    skill_idx = [s for s in indexes_ddl if "ix_role_requirements_skill_id" in s]
    target_created_idx = [
        s for s in indexes_ddl if "ix_role_requirements_target_created" in s
    ]

    assert len(target_idx) == 1
    assert len(skill_idx) == 1
    assert len(target_created_idx) == 1
