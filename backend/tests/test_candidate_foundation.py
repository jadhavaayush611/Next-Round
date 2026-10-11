import uuid

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.candidate_claim import CandidateClaim, ClaimOrigin, ClaimType
from app.models.candidate_profile import CandidateProfile
from app.models.candidate_target import CandidateTarget
from app.models.resume import Resume, ResumeStatus
from app.models.resume_parse import ParseStatus, ResumeParse
from app.models.user import User
from app.schemas.candidate_target import CandidateTargetCreate
from app.services.candidate_service import CandidateService


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


def create_user_model(db: Session, prefix: str = "candidate_usr") -> User:
    """Helper to persist a user model directly in the database."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@nextround.in",
        name=f"User {uid}",
        hashed_password="dummy_hashed_password",
        username=f"{prefix}_{uid}",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def create_ready_resume_parse(db: Session, user: User) -> ResumeParse:
    """Helper to persist a Resume and an immutable READY ResumeParse snapshot."""
    resume = Resume(
        user_id=user.id,
        original_filename="sample_resume.pdf",
        storage_key=f"resumes/{user.id}/{uuid.uuid4()}.pdf",
        mime_type="application/pdf",
        file_size=1024,
        version=1,
        status=ResumeStatus.READY,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)

    parse = ResumeParse(
        resume_id=resume.id,
        resume_version=1,
        parser_version="1.0.0",
        schema_version="1.0.0",
        status=ParseStatus.READY,
        canonical_data={
            "identity": {"name": user.name, "email": user.email},
            "experience": [{"role": "Backend Engineer", "company": "Acme Inc"}],
            "projects": [
                {
                    "name": "Supply Chain Router",
                    "technologies": ["Python", "PostgreSQL"],
                }
            ],
            "skills": [
                {
                    "category": "Languages",
                    "skills": ["Python", "Rust"],
                    "special/key": "escaped_slash_val",
                    "version~flag": "escaped_tilde_val",
                }
            ],
        },
    )
    db.add(parse)
    db.commit()
    db.refresh(parse)
    return parse


# =========================================================================
# 1. CandidateProfile Tests
# =========================================================================


def test_create_and_get_candidate_profile_success(client: TestClient) -> None:
    _, headers = register_user(client, "profile_success@nextround.in", "Alice Dev")

    # Profile does not exist initially
    get_res = client.get("/api/v1/candidate-profile", headers=headers)
    assert get_res.status_code == status.HTTP_404_NOT_FOUND

    # Create profile
    payload = {
        "preferred_locations": ["Bengaluru", "Remote"],
        "graduation_year": 2025,
    }
    create_res = client.post("/api/v1/candidate-profile", headers=headers, json=payload)
    assert create_res.status_code == status.HTTP_201_CREATED
    data = create_res.json()
    assert "id" in data
    assert data["preferred_locations"] == ["Bengaluru", "Remote"]
    assert data["graduation_year"] == 2025
    assert data["created_at"] is not None
    assert data["updated_at"] is not None
    assert data["active_target"] is None

    # Retrieve profile
    get_res2 = client.get("/api/v1/candidate-profile", headers=headers)
    assert get_res2.status_code == status.HTTP_200_OK
    assert get_res2.json()["id"] == data["id"]
    assert get_res2.json()["graduation_year"] == 2025

    # Retrieve via /candidate-profile/me alias
    get_res_alias = client.get("/api/v1/candidate-profile/me", headers=headers)
    assert get_res_alias.status_code == status.HTTP_200_OK
    assert get_res_alias.json()["id"] == data["id"]


def test_enforce_one_profile_per_user(client: TestClient, db: Session) -> None:
    _, headers = register_user(client, "one_profile@nextround.in", "Bob Dev")

    payload = {"preferred_locations": ["Hyderabad"], "graduation_year": 2024}
    res1 = client.post("/api/v1/candidate-profile", headers=headers, json=payload)
    assert res1.status_code == status.HTTP_201_CREATED

    # Attempting to create a second profile returns 409 Conflict
    res2 = client.post("/api/v1/candidate-profile", headers=headers, json=payload)
    assert res2.status_code == status.HTTP_409_CONFLICT
    assert "already exists" in res2.json()["detail"].lower()

    # Verify at the database level: inserting duplicate user_id raises IntegrityError
    user = create_user_model(db, "db_dup_user")
    p1 = CandidateProfile(user_id=user.id, graduation_year=2023)
    db.add(p1)
    db.commit()

    p2 = CandidateProfile(user_id=user.id, graduation_year=2024)
    db.add(p2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_update_candidate_profile_success(client: TestClient) -> None:
    _, headers = register_user(client, "profile_update@nextround.in", "Charlie Dev")

    client.post(
        "/api/v1/candidate-profile",
        headers=headers,
        json={"preferred_locations": ["Pune"], "graduation_year": 2022},
    )

    update_payload = {"preferred_locations": ["Pune", "Mumbai", "Remote"]}
    patch_res = client.patch(
        "/api/v1/candidate-profile", headers=headers, json=update_payload
    )
    assert patch_res.status_code == status.HTTP_200_OK
    data = patch_res.json()
    assert data["preferred_locations"] == ["Pune", "Mumbai", "Remote"]
    assert data["graduation_year"] == 2022


def test_update_candidate_profile_rejects_empty_and_immutable(
    client: TestClient,
) -> None:
    _, headers = register_user(client, "profile_reject@nextround.in", "Dave Dev")

    client.post(
        "/api/v1/candidate-profile",
        headers=headers,
        json={"graduation_year": 2023},
    )

    # Empty payload
    empty_res = client.patch("/api/v1/candidate-profile", headers=headers, json={})
    assert empty_res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Immutable user_id
    immutable_res = client.patch(
        "/api/v1/candidate-profile",
        headers=headers,
        json={"user_id": str(uuid.uuid4())},
    )
    assert immutable_res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Immutable id
    immutable_res2 = client.patch(
        "/api/v1/candidate-profile",
        headers=headers,
        json={"id": str(uuid.uuid4())},
    )
    assert immutable_res2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_candidate_profile_validation_rules(client: TestClient, db: Session) -> None:
    _, headers = register_user(client, "profile_rules@nextround.in", "Eve Dev")

    # Invalid graduation year (out of calendar range 1950 - 2100)
    bad_year_res = client.post(
        "/api/v1/candidate-profile",
        headers=headers,
        json={"graduation_year": 1899},
    )
    assert bad_year_res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    bad_future_res = client.post(
        "/api/v1/candidate-profile",
        headers=headers,
        json={"graduation_year": 2150},
    )
    assert bad_future_res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Invalid location list (empty strings)
    bad_loc_res = client.post(
        "/api/v1/candidate-profile",
        headers=headers,
        json={"preferred_locations": ["   ", "Valid Location"]},
    )
    assert bad_loc_res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Database CheckConstraint for graduation_year
    user = create_user_model(db, "db_year_user")
    bad_prof = CandidateProfile(user_id=user.id, graduation_year=1800)
    db.add(bad_prof)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


# =========================================================================
# 2. CandidateTarget Tests
# =========================================================================


def test_create_target_and_switch_active_targets(client: TestClient) -> None:
    _, headers = register_user(client, "target_switch@nextround.in", "Frank Dev")

    # Create first target
    target1_payload = {
        "role_title": "Backend Software Engineer",
        "company": "NextRound Labs",
        "job_description": "Build high-throughput FastAPI services.",
        "is_active": True,
    }
    t1_res = client.post(
        "/api/v1/candidate-targets", headers=headers, json=target1_payload
    )
    assert t1_res.status_code == status.HTTP_201_CREATED
    t1_data = t1_res.json()
    assert t1_data["role_title"] == "Backend Software Engineer"
    assert t1_data["is_active"] is True
    t1_id = t1_data["id"]

    # Active target check
    active_res = client.get("/api/v1/candidate-targets/active", headers=headers)
    assert active_res.status_code == status.HTTP_200_OK
    assert active_res.json()["id"] == t1_id

    # Create second target (should switch active target and deactivate target 1)
    target2_payload = {
        "role_title": "Full Stack Platform Engineer",
        "company": "Another Corp",
        "is_active": True,
    }
    t2_res = client.post(
        "/api/v1/candidate-targets", headers=headers, json=target2_payload
    )
    assert t2_res.status_code == status.HTTP_201_CREATED
    t2_data = t2_res.json()
    assert t2_data["role_title"] == "Full Stack Platform Engineer"
    assert t2_data["is_active"] is True
    t2_id = t2_data["id"]

    # Historical target 1 is preserved and deactivated
    targets_res = client.get("/api/v1/candidate-targets", headers=headers)
    assert targets_res.status_code == status.HTTP_200_OK
    targets = targets_res.json()
    assert len(targets) == 2

    # Map by ID
    targets_by_id = {t["id"]: t for t in targets}
    assert targets_by_id[t1_id]["is_active"] is False
    assert targets_by_id[t1_id]["role_title"] == "Backend Software Engineer"
    assert targets_by_id[t2_id]["is_active"] is True

    # Switching: reactivate target 1
    act_res = client.patch(
        f"/api/v1/candidate-targets/{t1_id}/activate", headers=headers
    )
    assert act_res.status_code == status.HTTP_200_OK
    assert act_res.json()["is_active"] is True

    # Verify target 2 is now deactivated
    active_now = client.get("/api/v1/candidate-targets/active", headers=headers).json()
    assert active_now["id"] == t1_id

    targets_after = client.get("/api/v1/candidate-targets", headers=headers).json()
    targets_after_map = {t["id"]: t for t in targets_after}
    assert targets_after_map[t2_id]["is_active"] is False


def test_deactivate_target_allows_no_active_target(client: TestClient) -> None:
    _, headers = register_user(client, "target_deactivate@nextround.in", "Grace Dev")

    t_res = client.post(
        "/api/v1/candidate-targets",
        headers=headers,
        json={"role_title": "Distributed Systems Engineer", "is_active": True},
    )
    t_id = t_res.json()["id"]

    # Deactivate target
    deact_res = client.patch(
        f"/api/v1/candidate-targets/{t_id}/deactivate", headers=headers
    )
    assert deact_res.status_code == status.HTTP_200_OK
    assert deact_res.json()["is_active"] is False

    # Active target endpoint returns 404
    active_res = client.get("/api/v1/candidate-targets/active", headers=headers)
    assert active_res.status_code == status.HTTP_404_NOT_FOUND


def test_db_enforces_at_most_one_active_target(db: Session) -> None:
    user = create_user_model(db, "db_target_user")
    profile = CandidateProfile(user_id=user.id)
    db.add(profile)
    db.commit()
    profile_id = profile.id

    t1 = CandidateTarget(
        candidate_profile_id=profile_id, role_title="Target 1", is_active=True
    )
    db.add(t1)
    db.commit()

    # Second active target for same profile must violate partial unique index
    t2 = CandidateTarget(
        candidate_profile_id=profile_id, role_title="Target 2", is_active=True
    )
    db.add(t2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # Re-fetch profile to ensure session is clean
    prof_fresh = CandidateProfile(user_id=uuid.uuid4())
    db.add(prof_fresh)
    db.commit()
    fresh_profile_id = prof_fresh.id

    # Inactive historical targets can coexist
    t3 = CandidateTarget(
        candidate_profile_id=fresh_profile_id, role_title="Target 3", is_active=False
    )
    t4 = CandidateTarget(
        candidate_profile_id=fresh_profile_id, role_title="Target 4", is_active=False
    )
    db.add(t3)
    db.add(t4)
    db.commit()
    assert t3.id is not None
    assert t4.id is not None


def test_target_cross_user_access_prevented(client: TestClient) -> None:
    _, headers1 = register_user(client, "target_owner1@nextround.in", "User 1")
    _, headers2 = register_user(client, "target_owner2@nextround.in", "User 2")

    t1_res = client.post(
        "/api/v1/candidate-targets",
        headers=headers1,
        json={"role_title": "Private Role", "is_active": True},
    )
    target_id = t1_res.json()["id"]

    # User 2 cannot activate or deactivate User 1's target
    act_res = client.patch(
        f"/api/v1/candidate-targets/{target_id}/activate", headers=headers2
    )
    assert act_res.status_code == status.HTTP_404_NOT_FOUND

    deact_res = client.patch(
        f"/api/v1/candidate-targets/{target_id}/deactivate", headers=headers2
    )
    assert deact_res.status_code == status.HTTP_404_NOT_FOUND


# =========================================================================
# 3. CandidateClaim Tests
# =========================================================================


def test_create_user_declared_claim_success(client: TestClient) -> None:
    _, headers = register_user(client, "declared_claim@nextround.in", "Hannah Dev")

    claim_payload = {
        "claim_type": "SKILL",
        "claim_text": "Built real-time messaging pipeline using Kafka and FastAPI.",
        "origin": "USER_DECLARED",
    }
    res = client.post("/api/v1/candidate-claims", headers=headers, json=claim_payload)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["claim_type"] == "SKILL"
    assert data["origin"] == "USER_DECLARED"
    assert data["resume_parse_id"] is None
    assert data["canonical_path"] is None
    assert data["created_at"] is not None

    # Retrieve claim by ID
    get_res = client.get(f"/api/v1/candidate-claims/{data['id']}", headers=headers)
    assert get_res.status_code == status.HTTP_200_OK
    assert get_res.json()["id"] == data["id"]


def test_reject_user_declared_claim_with_resume_provenance(client: TestClient) -> None:
    _, headers = register_user(client, "bad_declared@nextround.in", "Ian Dev")

    bad_payload = {
        "claim_type": "SKILL",
        "claim_text": "Python experience",
        "origin": "USER_DECLARED",
        "resume_parse_id": str(uuid.uuid4()),  # Forbidden for USER_DECLARED
    }
    res = client.post("/api/v1/candidate-claims", headers=headers, json=bad_payload)
    assert res.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    bad_payload2 = {
        "claim_type": "SKILL",
        "claim_text": "Python experience",
        "origin": "USER_DECLARED",
        "canonical_path": "/skills/0",  # Forbidden for USER_DECLARED
    }
    res2 = client.post("/api/v1/candidate-claims", headers=headers, json=bad_payload2)
    assert res2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_create_resume_derived_claim_success(client: TestClient, db: Session) -> None:
    _, headers = register_user(client, "resume_claim_usr@nextround.in", "Jane Dev")
    user = db.query(User).filter(User.email == "resume_claim_usr@nextround.in").first()
    assert user is not None

    # Setup a valid READY parse snapshot owned by this user
    parse = create_ready_resume_parse(db, user)

    claim_payload = {
        "claim_type": "PROJECT",
        "claim_text": "Built high-throughput supply chain fulfillment routing engine.",
        "origin": "RESUME",
        "resume_parse_id": str(parse.id),
        "canonical_path": "/projects/0/technologies/1",
    }
    res = client.post("/api/v1/candidate-claims", headers=headers, json=claim_payload)
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["origin"] == "RESUME"
    assert data["resume_parse_id"] == str(parse.id)
    assert data["canonical_path"] == "/projects/0/technologies/1"
    assert data["claim_type"] == "PROJECT"


def test_reject_resume_derived_claim_missing_or_invalid_provenance(
    client: TestClient, db: Session
) -> None:
    _, headers = register_user(client, "bad_provenance@nextround.in", "Karl Dev")
    user = db.query(User).filter(User.email == "bad_provenance@nextround.in").first()
    assert user is not None
    parse = create_ready_resume_parse(db, user)

    # Missing resume_parse_id
    res1 = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "SKILL",
            "claim_text": "Rust",
            "origin": "RESUME",
            "canonical_path": "/skills/0",
        },
    )
    assert res1.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Missing canonical_path
    res2 = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "SKILL",
            "claim_text": "Rust",
            "origin": "RESUME",
            "resume_parse_id": str(parse.id),
        },
    )
    assert res2.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY

    # Invalid JSON Pointer syntax (not starting with /)
    res3 = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "SKILL",
            "claim_text": "Rust",
            "origin": "RESUME",
            "resume_parse_id": str(parse.id),
            "canonical_path": "invalid_path_without_leading_slash",
        },
    )
    assert res3.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_reject_resume_parse_owned_by_another_user(
    client: TestClient, db: Session
) -> None:
    _, headers1 = register_user(client, "legit_owner@nextround.in", "Owner User")
    _, headers2 = register_user(client, "attacker@nextround.in", "Attacker User")

    owner = db.query(User).filter(User.email == "legit_owner@nextround.in").first()
    assert owner is not None
    parse = create_ready_resume_parse(db, owner)

    # Attacker tries to create a claim referencing Owner's resume parse
    attack_payload = {
        "claim_type": "EXPERIENCE",
        "claim_text": "Associate Software Engineer at Google",
        "origin": "RESUME",
        "resume_parse_id": str(parse.id),
        "canonical_path": "/experience/0",
    }
    res = client.post("/api/v1/candidate-claims", headers=headers2, json=attack_payload)
    # Server rejects referencing another candidate's parse snapshot
    assert res.status_code == status.HTTP_404_NOT_FOUND
    assert "not owned by the current user" in res.json()["detail"].lower()


def test_claims_db_level_provenance_constraints(db: Session) -> None:
    # 1. RESUME without parse_id -> DB IntegrityError
    u1 = create_user_model(db, "db_claims_u1")
    c1 = CandidateClaim(
        user_id=u1.id,
        claim_type=ClaimType.SKILL,
        claim_text="PostgreSQL",
        origin=ClaimOrigin.RESUME,
        canonical_path="/skills/0",
        resume_parse_id=None,
    )
    db.add(c1)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 2. RESUME without canonical_path -> DB IntegrityError
    u2 = create_user_model(db, "db_claims_u2")
    c2 = CandidateClaim(
        user_id=u2.id,
        claim_type=ClaimType.SKILL,
        claim_text="PostgreSQL",
        origin=ClaimOrigin.RESUME,
        canonical_path=None,
        resume_parse_id=uuid.uuid4(),
    )
    db.add(c2)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    # 3. USER_DECLARED with resume_parse_id -> DB IntegrityError
    u3 = create_user_model(db, "db_claims_u3")
    c3 = CandidateClaim(
        user_id=u3.id,
        claim_type=ClaimType.SKILL,
        claim_text="PostgreSQL",
        origin=ClaimOrigin.USER_DECLARED,
        resume_parse_id=uuid.uuid4(),
        canonical_path=None,
    )
    db.add(c3)
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()


def test_claims_filtering_and_cross_user_isolation(
    client: TestClient, db: Session
) -> None:
    _, headers1 = register_user(client, "filter_user1@nextround.in", "User 1")
    _, headers2 = register_user(client, "filter_user2@nextround.in", "User 2")

    # Create claims for User 1
    c1_res = client.post(
        "/api/v1/candidate-claims",
        headers=headers1,
        json={
            "claim_type": "SKILL",
            "claim_text": "Docker containerization",
            "origin": "USER_DECLARED",
        },
    )
    c1_id = c1_res.json()["id"]

    client.post(
        "/api/v1/candidate-claims",
        headers=headers1,
        json={
            "claim_type": "EDUCATION",
            "claim_text": "B.Tech in Computer Science",
            "origin": "USER_DECLARED",
        },
    )

    # User 2 lists claims -> sees 0 claims
    u2_list = client.get("/api/v1/candidate-claims", headers=headers2).json()
    assert len(u2_list) == 0

    # User 2 attempts to get User 1's claim by ID -> 404
    u2_get = client.get(f"/api/v1/candidate-claims/{c1_id}", headers=headers2)
    assert u2_get.status_code == status.HTTP_404_NOT_FOUND

    # User 1 filters by claim_type=SKILL
    skills_only = client.get(
        "/api/v1/candidate-claims?claim_type=SKILL", headers=headers1
    ).json()
    assert len(skills_only) == 1
    assert skills_only[0]["claim_text"] == "Docker containerization"


def test_claims_contract_contains_no_readiness_or_verification_scores(
    client: TestClient,
) -> None:
    _, headers = register_user(client, "contract_check@nextround.in", "Contract Dev")

    res = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "SKILL",
            "claim_text": "Python",
            "origin": "USER_DECLARED",
        },
    )
    data = res.json()
    # Invariant: No confidence_score, is_verified, proficiency_score, readiness_score
    assert "confidence_score" not in data
    assert "is_verified" not in data
    assert "proficiency_score" not in data
    assert "readiness_score" not in data


def test_unauthorized_requests_rejected(client: TestClient) -> None:
    # All candidate intelligence endpoints require authentication
    assert (
        client.get("/api/v1/candidate-profile").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.post("/api/v1/candidate-profile", json={}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.get("/api/v1/candidate-targets").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.post("/api/v1/candidate-targets", json={}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.get("/api/v1/candidate-claims").status_code
        == status.HTTP_401_UNAUTHORIZED
    )
    assert (
        client.post("/api/v1/candidate-claims", json={}).status_code
        == status.HTTP_401_UNAUTHORIZED
    )


def test_resume_claim_pointer_resolution_and_escaping(
    client: TestClient, db: Session
) -> None:
    """Verifies that valid JSON pointer paths and RFC 6901 escaped paths resolve against canonical_data."""
    _, headers = register_user(client, "pointer_escape@nextround.in", "Escape Dev")
    user = db.query(User).filter(User.email == "pointer_escape@nextround.in").first()
    assert user is not None
    parse = create_ready_resume_parse(db, user)

    # 1. Valid nested object and array index: /projects/0/technologies/1 ("PostgreSQL")
    res1 = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "SKILL",
            "claim_text": "PostgreSQL",
            "origin": "RESUME",
            "resume_parse_id": str(parse.id),
            "canonical_path": "/projects/0/technologies/1",
        },
    )
    assert res1.status_code == status.HTTP_201_CREATED
    assert res1.json()["canonical_path"] == "/projects/0/technologies/1"

    # 2. Escaped slash '~1' pointing to key 'special/key'
    res2 = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "SKILL",
            "claim_text": "FastAPI with slash",
            "origin": "RESUME",
            "resume_parse_id": str(parse.id),
            "canonical_path": "/skills/0/special~1key",
        },
    )
    assert res2.status_code == status.HTTP_201_CREATED
    assert res2.json()["canonical_path"] == "/skills/0/special~1key"

    # 3. Escaped tilde '~0' pointing to key 'version~flag'
    res3 = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "SKILL",
            "claim_text": "Version tilde",
            "origin": "RESUME",
            "resume_parse_id": str(parse.id),
            "canonical_path": "/skills/0/version~0flag",
        },
    )
    assert res3.status_code == status.HTTP_201_CREATED
    assert res3.json()["canonical_path"] == "/skills/0/version~0flag"


def test_resume_claim_rejects_missing_or_invalid_pointer(
    client: TestClient, db: Session
) -> None:
    """Verifies that missing keys, out-of-range array indices, and invalid indices return HTTP 422."""
    _, headers = register_user(client, "pointer_fail@nextround.in", "Fail Dev")
    user = db.query(User).filter(User.email == "pointer_fail@nextround.in").first()
    assert user is not None
    parse = create_ready_resume_parse(db, user)

    # 1. Missing object key
    res_missing_key = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "SKILL",
            "claim_text": "Missing key",
            "origin": "RESUME",
            "resume_parse_id": str(parse.id),
            "canonical_path": "/skills/0/nonexistent_key",
        },
    )
    assert res_missing_key.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "does not resolve" in res_missing_key.json()["detail"]

    # 2. Out of bounds array index
    res_oob = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "PROJECT",
            "claim_text": "Missing index",
            "origin": "RESUME",
            "resume_parse_id": str(parse.id),
            "canonical_path": "/projects/99/technologies/0",
        },
    )
    assert res_oob.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY
    assert "does not resolve" in res_oob.json()["detail"]

    # 3. Non-numeric array index where list is expected
    res_bad_idx = client.post(
        "/api/v1/candidate-claims",
        headers=headers,
        json={
            "claim_type": "PROJECT",
            "claim_text": "Bad index",
            "origin": "RESUME",
            "resume_parse_id": str(parse.id),
            "canonical_path": "/projects/abc/name",
        },
    )
    assert res_bad_idx.status_code == status.HTTP_422_UNPROCESSABLE_ENTITY


def test_delete_parse_with_claims_blocked_by_restrict_constraint(
    db: Session,
) -> None:
    """Verifies that deleting a ResumeParse with associated CandidateClaim records is blocked by ON DELETE RESTRICT."""
    from sqlalchemy import text

    db.execute(text("PRAGMA foreign_keys = ON"))
    user = create_user_model(db, "db_restrict_user")
    parse = create_ready_resume_parse(db, user)

    claim = CandidateClaim(
        user_id=user.id,
        resume_parse_id=parse.id,
        claim_type=ClaimType.SKILL,
        claim_text="Python",
        canonical_path="/skills/0/skills/0",
        origin=ClaimOrigin.RESUME,
    )
    db.add(claim)
    db.commit()

    parse_id = parse.id
    claim_id = claim.id

    # Attempting to delete the referenced ResumeParse must be rejected with IntegrityError
    with pytest.raises(IntegrityError):
        with db.begin_nested():
            db.delete(parse)

    # Verify parse still exists and claim provenance remains intact
    fetched_parse = db.get(ResumeParse, parse_id)
    assert fetched_parse is not None
    fetched_claim = db.get(CandidateClaim, claim_id)
    assert fetched_claim is not None


def test_create_target_concurrency_conflict_returns_409(
    client: TestClient, db: Session
) -> None:
    """Verifies that create_target catches active-target uniqueness conflicts, rolls back, and returns HTTP 409."""
    from unittest.mock import patch

    _, headers = register_user(
        client, "target_conflict_create@nextround.in", "Conflict Create User"
    )
    user = (
        db.query(User)
        .filter(User.email == "target_conflict_create@nextround.in")
        .first()
    )
    assert user is not None

    service = CandidateService(db)
    sqlite_err = IntegrityError(
        "UNIQUE constraint failed: candidate_targets.candidate_profile_id",
        params={},
        orig=Exception(),
    )
    with patch.object(service.target_repo, "create", side_effect=sqlite_err):
        with pytest.raises(HTTPException) as exc_info:
            service.create_target(
                user, CandidateTargetCreate(role_title="Backend", is_active=True)
            )
        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert "Target conflict" in exc_info.value.detail


def test_activate_target_concurrency_conflict_returns_409(
    client: TestClient, db: Session
) -> None:
    """Verifies that activate_target catches active-target uniqueness conflicts, rolls back, and returns HTTP 409."""
    from unittest.mock import patch

    _, headers = register_user(
        client, "target_conflict_activate@nextround.in", "Conflict Activate User"
    )
    user = (
        db.query(User)
        .filter(User.email == "target_conflict_activate@nextround.in")
        .first()
    )
    assert user is not None

    service = CandidateService(db)
    profile = service.get_or_create_profile(user)
    t2 = CandidateTarget(
        candidate_profile_id=profile.id, role_title="Historical", is_active=False
    )
    db.add(t2)
    db.commit()

    pg_err = IntegrityError(
        'duplicate key value violates unique constraint "uq_candidate_targets_active_profile"',
        params={},
        orig=Exception(),
    )
    with patch.object(db, "commit", side_effect=pg_err):
        with pytest.raises(HTTPException) as exc_info:
            service.activate_target(user, t2.id)
        assert exc_info.value.status_code == status.HTTP_409_CONFLICT
        assert "Target conflict" in exc_info.value.detail


def test_create_target_unrelated_integrity_error_is_reraised(
    client: TestClient, db: Session
) -> None:
    """Verifies that unrelated IntegrityError exceptions are reraised and not translated to HTTP 409."""
    from unittest.mock import patch

    _, headers = register_user(
        client, "target_unrelated_err@nextround.in", "Unrelated Error User"
    )
    user = (
        db.query(User).filter(User.email == "target_unrelated_err@nextround.in").first()
    )
    assert user is not None

    service = CandidateService(db)
    unrelated_err = IntegrityError(
        "FOREIGN KEY constraint failed", params={}, orig=Exception()
    )
    with patch.object(service.target_repo, "create", side_effect=unrelated_err):
        with pytest.raises(IntegrityError):
            service.create_target(
                user, CandidateTargetCreate(role_title="Backend", is_active=True)
            )
