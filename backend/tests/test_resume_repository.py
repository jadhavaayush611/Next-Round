import uuid

import pytest
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models.resume import Resume, ResumeStatus
from app.models.user import User
from app.repositories.resume import ResumeRepository


def create_sample_user(db: Session, email_prefix: str = "user") -> User:
    unique_email = f"{email_prefix}_{uuid.uuid4().hex[:8]}@nextround.in"
    user = User(
        email=unique_email,
        name="Sample User",
        hashed_password="hashed_pw_dummy",
        username=f"user_{uuid.uuid4().hex[:8]}",
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


def test_create_and_retrieve_resume_by_id(db: Session) -> None:
    user = create_sample_user(db)
    repo = ResumeRepository(db)

    resume = Resume(
        user_id=user.id,
        original_filename="resume_v1.pdf",
        storage_key=f"resumes/{user.id}/resume_v1_{uuid.uuid4().hex}.pdf",
        mime_type="application/pdf",
        file_size=102400,
        version=1,
        status=ResumeStatus.UPLOADED,
    )
    created = repo.create_resume(resume)
    assert created.id is not None
    assert created.status == ResumeStatus.UPLOADED
    assert created.version == 1
    assert created.file_size == 102400

    fetched = repo.get_by_id(created.id)
    assert fetched is not None
    assert fetched.id == created.id
    assert fetched.original_filename == "resume_v1.pdf"
    assert fetched.user_id == user.id


def test_get_user_resume_and_ownership_isolation(db: Session) -> None:
    user1 = create_sample_user(db, "owner1")
    user2 = create_sample_user(db, "owner2")
    repo = ResumeRepository(db)

    resume1 = repo.create_resume(
        Resume(
            user_id=user1.id,
            original_filename="user1_resume.pdf",
            storage_key=f"resumes/{user1.id}/resume_{uuid.uuid4().hex}.pdf",
            mime_type="application/pdf",
            file_size=204800,
            version=1,
        )
    )

    # User 1 can fetch their own resume
    fetched_by_owner = repo.get_user_resume(resume1.id, user1.id)
    assert fetched_by_owner is not None
    assert fetched_by_owner.id == resume1.id

    # User 2 cannot fetch User 1's resume
    fetched_by_other = repo.get_user_resume(resume1.id, user2.id)
    assert fetched_by_other is None


def test_get_nonexistent_resume(db: Session) -> None:
    user = create_sample_user(db)
    repo = ResumeRepository(db)
    fake_id = uuid.uuid4()

    assert repo.get_by_id(fake_id) is None
    assert repo.get_user_resume(fake_id, user.id) is None


def test_list_user_resumes_and_multiple_versions(db: Session) -> None:
    user = create_sample_user(db)
    repo = ResumeRepository(db)

    # Initial version query with no resumes
    assert repo.get_latest_version(user.id) == 0
    assert len(repo.list_user_resumes(user.id)) == 0

    # Create multiple versions
    for v in [1, 2, 3]:
        repo.create_resume(
            Resume(
                user_id=user.id,
                original_filename=f"resume_v{v}.pdf",
                storage_key=f"resumes/{user.id}/resume_v{v}_{uuid.uuid4().hex}.pdf",
                mime_type="application/pdf",
                file_size=150000 + (v * 1000),
                version=v,
            )
        )

    assert repo.get_latest_version(user.id) == 3

    resumes = repo.list_user_resumes(user.id)
    assert len(resumes) == 3
    # Ordered descending by version
    assert [r.version for r in resumes] == [3, 2, 1]


def test_archive_resume(db: Session) -> None:
    user1 = create_sample_user(db, "archiver")
    user2 = create_sample_user(db, "intruder")
    repo = ResumeRepository(db)

    resume = repo.create_resume(
        Resume(
            user_id=user1.id,
            original_filename="to_archive.pdf",
            storage_key=f"resumes/{user1.id}/archive_{uuid.uuid4().hex}.pdf",
            mime_type="application/pdf",
            file_size=50000,
            version=1,
            status=ResumeStatus.READY,
        )
    )

    # Other user cannot archive user1's resume
    unauthorized_archive = repo.archive_resume(resume.id, user2.id)
    assert unauthorized_archive is None

    # Owner archives resume
    archived = repo.archive_resume(resume.id, user1.id)
    assert archived is not None
    assert archived.status == ResumeStatus.ARCHIVED
    assert archived.updated_at is not None

    # Verify state in DB
    refetched = repo.get_by_id(resume.id)
    assert refetched is not None
    assert refetched.status == ResumeStatus.ARCHIVED


def test_user_resume_relationship(db: Session) -> None:
    user = create_sample_user(db, "rel_user")
    repo = ResumeRepository(db)

    resume1 = repo.create_resume(
        Resume(
            user_id=user.id,
            original_filename="rel1.pdf",
            storage_key=f"resumes/{user.id}/rel1_{uuid.uuid4().hex}.pdf",
            mime_type="application/pdf",
            file_size=10000,
            version=1,
        )
    )

    # Check bidirectional relationship
    assert resume1.user.id == user.id
    assert resume1 in user.resumes
    assert user.resumes[0].original_filename == "rel1.pdf"


def test_constraint_file_size_positive(db: Session) -> None:
    user = create_sample_user(db, "size_test")
    repo = ResumeRepository(db)

    with pytest.raises(IntegrityError):
        repo.create_resume(
            Resume(
                user_id=user.id,
                original_filename="bad_size.pdf",
                storage_key=f"resumes/{user.id}/bad_size_{uuid.uuid4().hex}.pdf",
                mime_type="application/pdf",
                file_size=0,
                version=1,
            )
        )
    db.rollback()


def test_constraint_version_positive(db: Session) -> None:
    user = create_sample_user(db, "version_test")
    repo = ResumeRepository(db)

    with pytest.raises(IntegrityError):
        repo.create_resume(
            Resume(
                user_id=user.id,
                original_filename="bad_version.pdf",
                storage_key=f"resumes/{user.id}/bad_version_{uuid.uuid4().hex}.pdf",
                mime_type="application/pdf",
                file_size=1000,
                version=0,
            )
        )
    db.rollback()


def test_resume_response_schema(db: Session) -> None:
    from app.schemas.resume import ResumeListResponse, ResumeResponse

    user = create_sample_user(db, "schema_test")
    repo = ResumeRepository(db)

    resume = repo.create_resume(
        Resume(
            user_id=user.id,
            original_filename="my_resume.pdf",
            storage_key=f"resumes/{user.id}/secret_storage_path.pdf",
            mime_type="application/pdf",
            file_size=12345,
            version=1,
            status=ResumeStatus.UPLOADED,
        )
    )

    schema_data = ResumeResponse.model_validate(resume)
    dumped = schema_data.model_dump()

    # Verify exposed fields
    assert dumped["id"] == resume.id
    assert dumped["original_filename"] == "my_resume.pdf"
    assert dumped["mime_type"] == "application/pdf"
    assert dumped["file_size"] == 12345
    assert dumped["version"] == 1
    assert dumped["status"] == "UPLOADED"
    assert "created_at" in dumped
    assert "updated_at" in dumped

    # Verify hidden/unexposed fields
    assert "storage_key" not in dumped
    assert "user_id" not in dumped

    list_response = ResumeListResponse(items=[schema_data], total=1)
    assert len(list_response.items) == 1
    assert list_response.total == 1


def test_constraint_user_version_unique(db: Session) -> None:
    user = create_sample_user(db, "dup_version")
    repo = ResumeRepository(db)

    # First resume with version 1
    repo.create_resume(
        Resume(
            user_id=user.id,
            original_filename="v1.pdf",
            storage_key=f"resumes/{user.id}/v1_{uuid.uuid4().hex}.pdf",
            mime_type="application/pdf",
            file_size=1000,
            version=1,
        )
    )

    # Second resume with same user and same version 1 -> must fail with IntegrityError
    with pytest.raises(IntegrityError):
        repo.create_resume(
            Resume(
                user_id=user.id,
                original_filename="v1_duplicate.pdf",
                storage_key=f"resumes/{user.id}/v1_dup_{uuid.uuid4().hex}.pdf",
                mime_type="application/pdf",
                file_size=1000,
                version=1,
            )
        )
    db.rollback()


def test_updated_at_automatically_changes_on_orm_modification(db: Session) -> None:
    import time

    user = create_sample_user(db, "timestamp_test")
    repo = ResumeRepository(db)

    resume = repo.create_resume(
        Resume(
            user_id=user.id,
            original_filename="initial.pdf",
            storage_key=f"resumes/{user.id}/init_{uuid.uuid4().hex}.pdf",
            mime_type="application/pdf",
            file_size=10000,
            version=1,
            status=ResumeStatus.UPLOADED,
        )
    )
    initial_updated_at = resume.updated_at
    assert initial_updated_at is not None

    time.sleep(0.01)

    # Modify through ORM session
    resume.status = ResumeStatus.PROCESSING
    db.add(resume)
    db.commit()
    db.refresh(resume)

    assert resume.updated_at >= initial_updated_at
    assert resume.status == ResumeStatus.PROCESSING
