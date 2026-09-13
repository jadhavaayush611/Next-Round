import io
import uuid

import pytest
from fastapi import HTTPException, status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.models.resume import Resume, ResumeStatus
from app.models.resume_parse import ParseStatus, ResumeParse
from app.models.user import User
from app.repositories.resume_parse import ResumeParseRepository
from app.schemas.canonical_resume import CanonicalResume
from app.services.parse_service import ResumeParseService
from app.services.parser.constants import (
    PARSER_VERSION,
    SCHEMA_VERSION,
)
from app.services.storage import LocalStorageService
from tests.test_extraction import create_pdf_bytes


def create_test_user(db: Session, prefix: str = "parse_user") -> User:
    """Helper to create an active user."""
    uid = uuid.uuid4().hex[:8]
    user = User(
        email=f"{prefix}_{uid}@nextround.in",
        name=f"User {uid}",
        hashed_password="hashed_pw_dummy",
        username=f"{prefix}_{uid}",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def get_user_auth_token(client: TestClient, email: str, name: str) -> str:
    """Helper to register and login a user via API."""
    user_data = {
        "email": email,
        "password": "Password123!",
        "name": name,
    }
    client.post("/api/v1/auth/register", json=user_data)
    login_data = {"username": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/login", data=login_data)
    return str(res.json()["access_token"])


def create_safe_pdf_bytes(pages_text: list[str]) -> bytes:
    """Helper to convert unicode bullet and dash characters to ASCII before building raw PDF stream."""
    clean_pages = [
        txt.replace("•", "*").replace("–", "-").replace("—", "-").replace("’", "'")
        for txt in pages_text
    ]
    return create_pdf_bytes(clean_pages)


def create_stored_pdf_resume(
    db: Session,
    user: User,
    pages_text: list[str],
    version: int = 1,
    storage_service: LocalStorageService | None = None,
) -> Resume:
    """Creates a valid PDF on storage and persists the Resume record."""
    storage = storage_service or LocalStorageService()
    pdf_bytes = create_safe_pdf_bytes(pages_text)
    resume_id = uuid.uuid4()
    storage_key = f"users/{user.id}/resumes/{resume_id}.pdf"
    storage.save_file(storage_key, io.BytesIO(pdf_bytes))

    resume = Resume(
        id=resume_id,
        user_id=user.id,
        original_filename="candidate_resume.pdf",
        storage_key=storage_key,
        mime_type="application/pdf",
        file_size=len(pdf_bytes),
        version=version,
        status=ResumeStatus.UPLOADED,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return resume


# =========================================================================
# 1. Repository & Persistence Tests
# =========================================================================


def test_resume_parse_repository_crud_and_queries(db: Session) -> None:
    user = create_test_user(db)
    resume = create_stored_pdf_resume(
        db, user, ["John Doe\njohn@example.com\n\nEDUCATION\nIIT Bombay"]
    )
    repo = ResumeParseRepository(db)

    # 1. Create parse record
    parse = ResumeParse(
        resume_id=resume.id,
        resume_version=resume.version,
        parser_version="1.0.0",
        schema_version="1.0.0",
        status=ParseStatus.READY,
        canonical_data={"identity": {"name": "John Doe", "email": "john@example.com"}},
        extraction_metadata={"character_count": 100, "status": "COMPLETE"},
        error_message=None,
    )
    created = repo.create_parse(parse)
    assert created.id is not None
    assert created.status == ParseStatus.READY
    assert created.resume_version == 1
    assert created.parser_version == "1.0.0"

    # 2. Get by ID
    fetched = repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.canonical_data["identity"]["name"] == "John Doe"

    # 3. List by resume
    parses = repo.list_by_resume(resume.id)
    assert len(parses) == 1
    assert parses[0].id == created.id


def test_resume_parse_repository_idempotency_lookup(db: Session) -> None:
    user = create_test_user(db)
    resume = create_stored_pdf_resume(
        db, user, ["Jane Smith\njane@example.com\n\nEXPERIENCE\nGoogle"]
    )
    repo = ResumeParseRepository(db)

    # Initial check - no snapshot
    assert (
        repo.get_successful_snapshot(resume.id, resume.version, "1.0.0", "1.0.0")
        is None
    )

    # Create failed snapshot
    failed_parse = ResumeParse(
        resume_id=resume.id,
        resume_version=resume.version,
        parser_version="1.0.0",
        schema_version="1.0.0",
        status=ParseStatus.FAILED,
        error_message="Test failure",
    )
    repo.create_parse(failed_parse)

    # Successful snapshot query still returns None
    assert (
        repo.get_successful_snapshot(resume.id, resume.version, "1.0.0", "1.0.0")
        is None
    )

    # Create READY snapshot
    ready_parse = ResumeParse(
        resume_id=resume.id,
        resume_version=resume.version,
        parser_version="1.0.0",
        schema_version="1.0.0",
        status=ParseStatus.READY,
        canonical_data={"identity": {"name": "Jane Smith"}},
    )
    repo.create_parse(ready_parse)

    # Successful snapshot query returns the READY snapshot
    snapshot = repo.get_successful_snapshot(resume.id, resume.version, "1.0.0", "1.0.0")
    assert snapshot is not None
    assert snapshot.id == ready_parse.id
    assert snapshot.status == ParseStatus.READY


def test_resume_parse_repository_latest_successful_parse(db: Session) -> None:
    user = create_test_user(db)
    resume = create_stored_pdf_resume(
        db, user, ["Alice Doe\nalice@example.com\n\nEDUCATION\nMIT"]
    )
    repo = ResumeParseRepository(db)

    # Create snapshot A with parser 1.0.0
    snap_a = ResumeParse(
        resume_id=resume.id,
        resume_version=resume.version,
        parser_version="1.0.0",
        schema_version="1.0.0",
        status=ParseStatus.READY,
        canonical_data={"identity": {"name": "Alice Doe v1.0"}},
    )
    repo.create_parse(snap_a)

    # Create snapshot B with parser 1.1.0
    snap_b = ResumeParse(
        resume_id=resume.id,
        resume_version=resume.version,
        parser_version="1.1.0",
        schema_version="1.0.0",
        status=ParseStatus.READY,
        canonical_data={"identity": {"name": "Alice Doe v1.1"}},
    )
    repo.create_parse(snap_b)

    # Latest should return snapshot B
    latest = repo.get_latest_successful_parse(resume.id)
    assert latest is not None
    assert latest.id == snap_b.id
    assert latest.parser_version == "1.1.0"


# =========================================================================
# 2. Service Layer & Parsing Integration Tests
# =========================================================================


def test_resume_parse_service_successful_parse(db: Session) -> None:
    user = create_test_user(db)
    resume_text = """
Rahul Sharma
rahul.sharma@iitb.ac.in | +91 98765 43210 | linkedin.com/in/rahulsharma

EDUCATION
Indian Institute of Technology Bombay
B.Tech in Computer Science and Engineering (2020 - 2024)
• Cumulative GPA: 9.42 / 10.0

WORK EXPERIENCE
Software Engineer Intern at Microsoft, Bangalore
May 2023 - Jul 2023
• Built real-time stream processing pipeline handling 100k events/sec.

TECHNICAL SKILLS
Languages: Python, C++, Go, TypeScript
Frameworks: FastAPI, React, PyTorch
"""
    resume = create_stored_pdf_resume(db, user, [resume_text])
    service = ResumeParseService(db)

    parse_record = service.parse_resume(user, resume.id)

    assert parse_record.id is not None
    assert parse_record.status == ParseStatus.READY
    assert parse_record.resume_version == 1
    assert parse_record.parser_version == PARSER_VERSION
    assert parse_record.schema_version == SCHEMA_VERSION
    assert parse_record.canonical_data is not None

    # Validate canonical data structure
    canonical = CanonicalResume.model_validate(parse_record.canonical_data)
    assert canonical.identity.name == "Rahul Sharma"
    assert canonical.identity.email == "rahul.sharma@iitb.ac.in"
    assert len(canonical.education) == 1
    assert "Indian Institute of Technology Bombay" in canonical.education[0].institution
    assert len(canonical.experience) == 1
    assert canonical.experience[0].organization == "Microsoft"
    assert len(canonical.skills) == 2


def test_resume_parse_service_idempotency_reuses_existing(db: Session) -> None:
    user = create_test_user(db)
    resume = create_stored_pdf_resume(
        db, user, ["Aayush Jadhav\naayush@nextround.in\n\nEXPERIENCE\nDev"]
    )
    service = ResumeParseService(db)
    repo = ResumeParseRepository(db)

    # First parse
    first_parse = service.parse_resume(user, resume.id)
    assert first_parse.status == ParseStatus.READY

    # Second parse with exact same versions
    second_parse = service.parse_resume(user, resume.id)

    # Should reuse the exact same record without creating a second snapshot
    assert second_parse.id == first_parse.id

    # Total records in DB for this resume must be exactly 1
    all_parses = repo.list_by_resume(resume.id)
    assert len(all_parses) == 1


def test_resume_parse_service_version_upgrade_creates_new_snapshot(
    db: Session,
) -> None:
    user = create_test_user(db)
    resume = create_stored_pdf_resume(
        db, user, ["Candidate Name\ncandidate@nextround.in\n\nEDUCATION\nBITS Pilani"]
    )
    service = ResumeParseService(db)
    repo = ResumeParseRepository(db)

    # Parse with parser 1.0.0
    parse_v1 = service.parse_resume(user, resume.id, parser_version="1.0.0")
    assert parse_v1.parser_version == "1.0.0"

    # Re-parse with same parser 1.0.0 -> reused
    parse_v1_reused = service.parse_resume(user, resume.id, parser_version="1.0.0")
    assert parse_v1_reused.id == parse_v1.id

    # Parse with upgraded parser 1.1.0 -> creates new snapshot
    parse_v2 = service.parse_resume(user, resume.id, parser_version="1.1.0")
    assert parse_v2.parser_version == "1.1.0"
    assert parse_v2.id != parse_v1.id

    # Verify both snapshots remain stored in DB (immutability)
    all_parses = repo.list_by_resume(resume.id)
    assert len(all_parses) == 2
    assert {p.parser_version for p in all_parses} == {"1.0.0", "1.1.0"}

    # Latest canonical retrieval returns the upgraded parser snapshot
    latest = service.get_latest_canonical(user, resume.id)
    assert latest.parser_version == "1.1.0"


def test_resume_parse_service_new_resume_version_independent_snapshots(
    db: Session,
) -> None:
    user = create_test_user(db)
    # Resume Version 1
    resume_v1 = create_stored_pdf_resume(
        db, user, ["Student v1\nstudent@college.edu"], version=1
    )
    # Resume Version 2
    resume_v2 = create_stored_pdf_resume(
        db, user, ["Student v2\nstudent@college.edu\n\nEXPERIENCE\nNew Job"], version=2
    )

    service = ResumeParseService(db)

    parse_v1 = service.parse_resume(user, resume_v1.id)
    parse_v2 = service.parse_resume(user, resume_v2.id)

    assert parse_v1.resume_version == 1
    assert parse_v2.resume_version == 2
    assert parse_v1.id != parse_v2.id


def test_resume_parse_service_failed_parse_persistence_and_retry(
    db: Session,
) -> None:
    user = create_test_user(db)
    resume = create_stored_pdf_resume(db, user, ["Initial Text"])
    service = ResumeParseService(db)
    repo = ResumeParseRepository(db)

    # Delete underlying storage file to induce extraction failure
    storage = LocalStorageService()
    storage.delete_file(resume.storage_key)

    # Parse should fail and record a FAILED parse record
    with pytest.raises(HTTPException):
        service.parse_resume(user, resume.id)

    # Check FAILED record was saved
    parses = repo.list_by_resume(resume.id)
    assert len(parses) == 1
    assert parses[0].status == ParseStatus.FAILED
    assert parses[0].error_message is not None

    # Re-create file in storage to simulate fix / retry
    storage.save_file(
        resume.storage_key,
        io.BytesIO(
            create_safe_pdf_bytes(
                ["Fixed Candidate\nfixed@example.com\n\nEDUCATION\nStanford"]
            )
        ),
    )

    # Retry parse -> should succeed and create a READY snapshot
    successful_parse = service.parse_resume(user, resume.id)
    assert successful_parse.status == ParseStatus.READY
    assert successful_parse.canonical_data is not None

    # Total records in DB: 1 FAILED + 1 READY
    all_parses = repo.list_by_resume(resume.id)
    assert len(all_parses) == 2


def test_resume_parse_service_ownership_isolation(db: Session) -> None:
    user1 = create_test_user(db, "owner1")
    user2 = create_test_user(db, "owner2")
    resume = create_stored_pdf_resume(db, user1, ["Owner 1 Resume"])
    service = ResumeParseService(db)

    # User 2 cannot trigger parsing of User 1's resume (raises 404)
    with pytest.raises(HTTPException) as exc_info:
        service.parse_resume(user2, resume.id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND

    # User 2 cannot retrieve canonical representation of User 1's resume (raises 404)
    with pytest.raises(HTTPException) as exc_info:
        service.get_latest_canonical(user2, resume.id)
    assert exc_info.value.status_code == status.HTTP_404_NOT_FOUND


# =========================================================================
# 3. API Endpoints Tests
# =========================================================================


def test_api_parse_resume_success(client: TestClient, db: Session) -> None:
    token = get_user_auth_token(client, "api_user1@nextround.in", "API User 1")
    headers = {"Authorization": f"Bearer {token}"}

    # Upload resume
    pdf_content = create_safe_pdf_bytes(
        [
            "Siddharth Rao\nsiddharth.rao@example.in | +91 91234 56789\n\nEDUCATION\nIIT Delhi\nB.Tech Electrical Eng (2019 - 2023)\n\nWORK EXPERIENCE\nAssociate at Flipkart\nJul 2023 - Present\n• Optimized supply chain fulfillment routing."
        ]
    )
    upload_res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                "siddharth_resume.pdf",
                io.BytesIO(pdf_content),
                "application/pdf",
            )
        },
    )
    assert upload_res.status_code == status.HTTP_201_CREATED
    resume_id = upload_res.json()["id"]

    # Trigger parse
    parse_res = client.post(f"/api/v1/resumes/{resume_id}/parse", headers=headers)
    assert parse_res.status_code == status.HTTP_200_OK
    data = parse_res.json()
    assert data["resume_id"] == resume_id
    assert data["resume_version"] == 1
    assert data["parser_version"] == PARSER_VERSION
    assert data["schema_version"] == SCHEMA_VERSION
    assert data["status"] == "READY"
    assert data["canonical_data"]["identity"]["name"] == "Siddharth Rao"
    assert data["canonical_data"]["identity"]["email"] == "siddharth.rao@example.in"
    assert len(data["canonical_data"]["education"]) == 1
    assert len(data["canonical_data"]["experience"]) == 1

    # Fetch canonical representation via GET endpoint
    canon_res = client.get(f"/api/v1/resumes/{resume_id}/canonical", headers=headers)
    assert canon_res.status_code == status.HTTP_200_OK
    canon_data = canon_res.json()
    assert canon_data["resume_id"] == resume_id
    assert canon_data["resume_version"] == 1
    assert canon_data["canonical_resume"]["identity"]["name"] == "Siddharth Rao"
    assert len(canon_data["canonical_resume"]["experience"]) == 1
    assert canon_data["canonical_resume"]["experience"][0]["organization"] == "Flipkart"


def test_api_parse_resume_idempotent_repeated_call(
    client: TestClient, db: Session
) -> None:
    token = get_user_auth_token(
        client, "idempotent_user@nextround.in", "Idempotent User"
    )
    headers = {"Authorization": f"Bearer {token}"}

    pdf_content = create_safe_pdf_bytes(["Test Candidate\ntest@candidate.com"])
    upload_res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={"file": ("test_resume.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    resume_id = upload_res.json()["id"]

    # First parse call
    res1 = client.post(f"/api/v1/resumes/{resume_id}/parse", headers=headers)
    assert res1.status_code == status.HTTP_200_OK
    snap_id_1 = res1.json()["id"]

    # Second parse call
    res2 = client.post(f"/api/v1/resumes/{resume_id}/parse", headers=headers)
    assert res2.status_code == status.HTTP_200_OK
    snap_id_2 = res2.json()["id"]

    # Reused the exact same snapshot
    assert snap_id_1 == snap_id_2


def test_api_parse_resume_unauthorized(client: TestClient) -> None:
    fake_id = uuid.uuid4()
    # No auth header
    res = client.post(f"/api/v1/resumes/{fake_id}/parse")
    assert res.status_code == status.HTTP_401_UNAUTHORIZED

    # Invalid token
    res_inv = client.post(
        f"/api/v1/resumes/{fake_id}/parse",
        headers={"Authorization": "Bearer invalid_token"},
    )
    assert res_inv.status_code == status.HTTP_401_UNAUTHORIZED


def test_api_parse_resume_forbidden_cross_user(client: TestClient, db: Session) -> None:
    user1_token = get_user_auth_token(client, "user_one@nextround.in", "User One")
    user2_token = get_user_auth_token(client, "user_two@nextround.in", "User Two")

    # User 1 uploads resume
    pdf_content = create_safe_pdf_bytes(["User One Resume\nuser1@nextround.in"])
    upload_res = client.post(
        "/api/v1/resumes",
        headers={"Authorization": f"Bearer {user1_token}"},
        files={"file": ("user1.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    resume_id = upload_res.json()["id"]

    # User 2 attempts to parse User 1's resume -> 404 (ownership isolation)
    cross_parse = client.post(
        f"/api/v1/resumes/{resume_id}/parse",
        headers={"Authorization": f"Bearer {user2_token}"},
    )
    assert cross_parse.status_code == status.HTTP_404_NOT_FOUND

    # User 2 attempts to get canonical data of User 1's resume -> 404
    cross_get = client.get(
        f"/api/v1/resumes/{resume_id}/canonical",
        headers={"Authorization": f"Bearer {user2_token}"},
    )
    assert cross_get.status_code == status.HTTP_404_NOT_FOUND


def test_api_get_canonical_resume_not_parsed_yet(
    client: TestClient, db: Session
) -> None:
    token = get_user_auth_token(client, "unparsed_user@nextround.in", "Unparsed")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_content = create_safe_pdf_bytes(["Unparsed resume text"])
    upload_res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={"file": ("unparsed.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    resume_id = upload_res.json()["id"]

    # GET canonical before parsing -> 404
    canon_res = client.get(f"/api/v1/resumes/{resume_id}/canonical", headers=headers)
    assert canon_res.status_code == status.HTTP_404_NOT_FOUND
    assert (
        "No successful canonical parse" in canon_res.json()["detail"]
        or "not found" in canon_res.json()["detail"].lower()
    )


def test_api_get_canonical_resume_corrupted_data_rejection(
    client: TestClient, db: Session
) -> None:
    token = get_user_auth_token(
        client, "corrupt_data_user@nextround.in", "Corrupt User"
    )
    headers = {"Authorization": f"Bearer {token}"}

    pdf_content = create_safe_pdf_bytes(["Valid candidate"])
    upload_res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={"file": ("c.pdf", io.BytesIO(pdf_content), "application/pdf")},
    )
    resume_id = uuid.UUID(upload_res.json()["id"])

    # Manually insert a corrupted/invalid JSONB payload in resume_parses
    corrupt_parse = ResumeParse(
        resume_id=resume_id,
        resume_version=1,
        parser_version=PARSER_VERSION,
        schema_version=SCHEMA_VERSION,
        status=ParseStatus.READY,
        canonical_data={
            "experience": "NOT_A_LIST_INVALID_TYPE"
        },  # Violates list[ExperienceItem] schema
    )
    db.add(corrupt_parse)
    db.commit()

    # GET canonical should safely reject malformed stored data with 500
    res = client.get(f"/api/v1/resumes/{resume_id}/canonical", headers=headers)
    assert res.status_code == status.HTTP_500_INTERNAL_SERVER_ERROR
    assert (
        "schema validation" in res.json()["detail"].lower()
        or "invalid" in res.json()["detail"].lower()
    )


def test_cascade_delete_resumes_removes_parses(db: Session) -> None:
    user = create_test_user(db)
    resume = create_stored_pdf_resume(db, user, ["Delete test\ndelete@example.com"])
    repo = ResumeParseRepository(db)

    # Create parse
    parse = ResumeParse(
        resume_id=resume.id,
        resume_version=resume.version,
        parser_version="1.0.0",
        schema_version="1.0.0",
        status=ParseStatus.READY,
        canonical_data={"identity": {"name": "Delete Test"}},
    )
    repo.create_parse(parse)
    assert repo.get_by_id(parse.id) is not None

    # Delete resume
    db.delete(resume)
    db.commit()

    # Resume parse should be cascade-deleted
    assert repo.get_by_id(parse.id) is None
