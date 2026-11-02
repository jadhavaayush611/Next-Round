import io
import uuid
from unittest.mock import patch

import pytest
from fastapi import status
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.config.settings import settings
from app.models.resume import Resume
from app.models.user import User
from app.repositories.resume import ResumeRepository
from app.services.storage import LocalStorageService


def get_auth_token(client: TestClient, email: str, name: str) -> str:
    user_data = {
        "email": email,
        "password": "Password123!",
        "name": name,
    }
    client.post("/api/v1/auth/register", json=user_data)
    login_data = {"username": email, "password": "Password123!"}
    res = client.post("/api/v1/auth/login", data=login_data)
    return str(res.json()["access_token"])


def test_upload_pdf_success(client: TestClient, db: Session) -> None:
    token = get_auth_token(client, "pdf_user@nextround.in", "PDF User")
    headers = {"Authorization": f"Bearer {token}"}

    pdf_content = b"%PDF-1.4\n%Binary test content for valid PDF document"
    response = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                "resume_software_engineer.pdf",
                io.BytesIO(pdf_content),
                "application/pdf",
            )
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["original_filename"] == "resume_software_engineer.pdf"
    assert data["mime_type"] == "application/pdf"
    assert data["file_size"] == len(pdf_content)
    assert data["version"] == 1
    assert data["status"] == "UPLOADED"
    assert "id" in data
    assert "created_at" in data
    assert "updated_at" in data

    # Verify sensitive storage details are NEVER exposed
    assert "storage_key" not in data
    assert "file_path" not in data

    # Verify file existence on disk
    resume_id = uuid.UUID(data["id"])
    repo = ResumeRepository(db)
    resume = repo.get_by_id(resume_id)
    assert resume is not None
    assert resume.version == 1

    storage = LocalStorageService()
    assert storage.file_exists(resume.storage_key) is True
    # Clean up test file
    storage.delete_file(resume.storage_key)


def test_upload_docx_success(client: TestClient, db: Session) -> None:
    token = get_auth_token(client, "docx_user@nextround.in", "DOCX User")
    headers = {"Authorization": f"Bearer {token}"}

    docx_content = b"PK\x03\x04\nBinary test content for valid DOCX document"
    response = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                "candidate_profile.docx",
                io.BytesIO(docx_content),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )

    assert response.status_code == status.HTTP_201_CREATED
    data = response.json()
    assert data["original_filename"] == "candidate_profile.docx"
    assert (
        data["mime_type"]
        == "application/vnd.openxmlformats-officedocument.wordprocessingml.document"
    )
    assert data["file_size"] == len(docx_content)
    assert data["version"] == 1
    assert data["status"] == "UPLOADED"

    resume_id = uuid.UUID(data["id"])
    repo = ResumeRepository(db)
    resume = repo.get_by_id(resume_id)
    assert resume is not None

    storage = LocalStorageService()
    assert storage.file_exists(resume.storage_key) is True
    storage.delete_file(resume.storage_key)


def test_upload_version_incrementing(client: TestClient, db: Session) -> None:
    token = get_auth_token(client, "multi_ver@nextround.in", "Multi Version User")
    headers = {"Authorization": f"Bearer {token}"}

    storage = LocalStorageService()
    keys_to_clean: list[str] = []

    try:
        # Version 1 upload
        res1 = client.post(
            "/api/v1/resumes",
            headers=headers,
            files={
                "file": (
                    "v1.pdf",
                    io.BytesIO(b"%PDF-1.4 Version 1 content"),
                    "application/pdf",
                )
            },
        )
        assert res1.status_code == status.HTTP_201_CREATED
        assert res1.json()["version"] == 1

        # Version 2 upload
        res2 = client.post(
            "/api/v1/resumes",
            headers=headers,
            files={
                "file": (
                    "v2.pdf",
                    io.BytesIO(b"%PDF-1.4 Version 2 content"),
                    "application/pdf",
                )
            },
        )
        assert res2.status_code == status.HTTP_201_CREATED
        assert res2.json()["version"] == 2

        # Version 3 upload
        res3 = client.post(
            "/api/v1/resumes",
            headers=headers,
            files={
                "file": (
                    "v3.pdf",
                    io.BytesIO(b"%PDF-1.4 Version 3 content"),
                    "application/pdf",
                )
            },
        )
        assert res3.status_code == status.HTTP_201_CREATED
        assert res3.json()["version"] == 3

        repo = ResumeRepository(db)
        r1 = repo.get_by_id(uuid.UUID(res1.json()["id"]))
        r2 = repo.get_by_id(uuid.UUID(res2.json()["id"]))
        r3 = repo.get_by_id(uuid.UUID(res3.json()["id"]))
        assert r1 and r2 and r3
        keys_to_clean.extend([r1.storage_key, r2.storage_key, r3.storage_key])

    finally:
        for key in keys_to_clean:
            storage.delete_file(key)


def test_upload_case_insensitive_extension(client: TestClient, db: Session) -> None:
    token = get_auth_token(client, "caps_user@nextround.in", "Caps User")
    headers = {"Authorization": f"Bearer {token}"}

    storage = LocalStorageService()
    res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                "UPPERCASE_RESUME.PDF",
                io.BytesIO(b"%PDF-1.4 uppercase test"),
                "application/pdf",
            )
        },
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    assert data["version"] == 1

    repo = ResumeRepository(db)
    resume = repo.get_by_id(uuid.UUID(data["id"]))
    assert resume is not None
    storage.delete_file(resume.storage_key)


def test_upload_rejects_unsupported_extension(client: TestClient) -> None:
    token = get_auth_token(client, "bad_ext@nextround.in", "Bad Ext User")
    headers = {"Authorization": f"Bearer {token}"}

    # .txt extension
    res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                "resume.txt",
                io.BytesIO(b"Just plain text"),
                "text/plain",
            )
        },
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Unsupported file extension" in res.json()["detail"]

    # .exe extension
    res_exe = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                "malware.exe",
                io.BytesIO(b"MZ executable"),
                "application/x-msdownload",
            )
        },
    )
    assert res_exe.status_code == status.HTTP_400_BAD_REQUEST


def test_upload_rejects_unsupported_or_mismatched_mime_type(
    client: TestClient,
) -> None:
    token = get_auth_token(client, "mime_user@nextround.in", "MIME User")
    headers = {"Authorization": f"Bearer {token}"}

    # PDF extension but arbitrary octet-stream MIME
    res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                "resume.pdf",
                io.BytesIO(b"%PDF-1.4 test"),
                "application/octet-stream",
            )
        },
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Unsupported MIME type" in res.json()["detail"]

    # PDF extension with DOCX MIME type
    res_mismatch = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                "resume.pdf",
                io.BytesIO(b"%PDF-1.4 test"),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res_mismatch.status_code == status.HTTP_400_BAD_REQUEST
    assert "MIME type does not match PDF" in res_mismatch.json()["detail"]


def test_upload_rejects_invalid_pdf_signature(client: TestClient) -> None:
    token = get_auth_token(client, "sig_pdf@nextround.in", "Signature PDF")
    headers = {"Authorization": f"Bearer {token}"}

    # Content does not begin with %PDF-
    fake_pdf = b"NOT_A_REAL_PDF_HEADER_12345"
    res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={"file": ("fake.pdf", io.BytesIO(fake_pdf), "application/pdf")},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid file signature" in res.json()["detail"]


def test_upload_rejects_invalid_docx_signature(client: TestClient) -> None:
    token = get_auth_token(client, "sig_docx@nextround.in", "Signature DOCX")
    headers = {"Authorization": f"Bearer {token}"}

    # Content does not begin with PK
    fake_docx = b"NOT_A_REAL_ZIP_HEADER_12345"
    res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                "fake.docx",
                io.BytesIO(fake_docx),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
        },
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "Invalid file signature" in res.json()["detail"]


def test_upload_rejects_empty_file(client: TestClient) -> None:
    token = get_auth_token(client, "empty@nextround.in", "Empty File User")
    headers = {"Authorization": f"Bearer {token}"}

    res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={"file": ("empty.pdf", io.BytesIO(b""), "application/pdf")},
    )
    assert res.status_code == status.HTTP_400_BAD_REQUEST
    assert "empty" in res.json()["detail"].lower()


def test_upload_rejects_oversized_file(client: TestClient) -> None:
    token = get_auth_token(client, "oversized@nextround.in", "Oversized User")
    headers = {"Authorization": f"Bearer {token}"}

    # Construct payload slightly larger than 5 MB
    large_payload = b"%PDF-" + b"0" * (settings.MAX_UPLOAD_SIZE_BYTES + 1024)
    res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": ("large_resume.pdf", io.BytesIO(large_payload), "application/pdf")
        },
    )
    assert res.status_code == status.HTTP_413_REQUEST_ENTITY_TOO_LARGE
    assert "exceeds maximum allowed limit" in res.json()["detail"]


def test_upload_requires_authentication(client: TestClient) -> None:
    # No auth header
    res = client.post(
        "/api/v1/resumes",
        files={
            "file": (
                "resume.pdf",
                io.BytesIO(b"%PDF-1.4 test"),
                "application/pdf",
            )
        },
    )
    assert res.status_code == status.HTTP_401_UNAUTHORIZED


def test_upload_security_path_traversal_filename(
    client: TestClient, db: Session
) -> None:
    token = get_auth_token(client, "traversal@nextround.in", "Traversal User")
    headers = {"Authorization": f"Bearer {token}"}

    # Malicious filename attempting path traversal
    malicious_filename = "../../../../../etc/passwd.pdf"
    pdf_content = b"%PDF-1.4 security test"

    res = client.post(
        "/api/v1/resumes",
        headers=headers,
        files={
            "file": (
                malicious_filename,
                io.BytesIO(pdf_content),
                "application/pdf",
            )
        },
    )
    assert res.status_code == status.HTTP_201_CREATED
    data = res.json()
    # Metadata should only store sanitized base name
    assert data["original_filename"] == "passwd.pdf"

    # Verify storage key is derived safely with resume UUID and not original filename
    repo = ResumeRepository(db)
    resume = repo.get_by_id(uuid.UUID(data["id"]))
    assert resume is not None
    assert "passwd.pdf" not in resume.storage_key
    assert str(resume.id) in resume.storage_key

    storage = LocalStorageService()
    assert storage.file_exists(resume.storage_key) is True
    # Ensure resolved path is strictly inside root
    resolved = storage.resolve_path(resume.storage_key)
    assert resolved.is_relative_to(storage.root_path)

    storage.delete_file(resume.storage_key)


def test_upload_ownership_isolation(client: TestClient, db: Session) -> None:
    token_a = get_auth_token(client, "user_owner_a@nextround.in", "Owner A")
    token_b = get_auth_token(client, "user_owner_b@nextround.in", "Owner B")

    storage = LocalStorageService()
    keys_to_clean: list[str] = []

    try:
        # User A uploads resume
        res_a = client.post(
            "/api/v1/resumes",
            headers={"Authorization": f"Bearer {token_a}"},
            files={
                "file": (
                    "user_a.pdf",
                    io.BytesIO(b"%PDF-1.4 User A"),
                    "application/pdf",
                )
            },
        )
        assert res_a.status_code == status.HTTP_201_CREATED
        id_a = uuid.UUID(res_a.json()["id"])

        # User B uploads resume
        res_b = client.post(
            "/api/v1/resumes",
            headers={"Authorization": f"Bearer {token_b}"},
            files={
                "file": (
                    "user_b.pdf",
                    io.BytesIO(b"%PDF-1.4 User B"),
                    "application/pdf",
                )
            },
        )
        assert res_b.status_code == status.HTTP_201_CREATED
        id_b = uuid.UUID(res_b.json()["id"])
        # Both user's initial uploads get version 1
        assert res_a.json()["version"] == 1
        assert res_b.json()["version"] == 1

        repo = ResumeRepository(db)
        r_a = repo.get_by_id(id_a)
        r_b = repo.get_by_id(id_b)
        assert r_a and r_b
        keys_to_clean.extend([r_a.storage_key, r_b.storage_key])

        # Verify database user_id matches
        user_a = (
            db.query(User).filter(User.email == "user_owner_a@nextround.in").first()
        )
        user_b = (
            db.query(User).filter(User.email == "user_owner_b@nextround.in").first()
        )
        assert user_a and user_b
        assert r_a.user_id == user_a.id
        assert r_b.user_id == user_b.id
        assert r_a.user_id != r_b.user_id

    finally:
        for key in keys_to_clean:
            storage.delete_file(key)


def test_upload_db_failure_cleans_up_stored_file(
    client: TestClient, db: Session
) -> None:
    token = get_auth_token(client, "db_fail@nextround.in", "DB Fail User")
    headers = {"Authorization": f"Bearer {token}"}

    storage = LocalStorageService()
    persisted_keys: list[str] = []

    # Spy on save_file to capture the storage_key written to disk
    real_save_file = storage.save_file

    def tracking_save_file(
        storage_key: str,
        file_obj: io.BytesIO,
        max_size_bytes: int | None = None,
        chunk_size: int = 64 * 1024,
    ) -> int:
        persisted_keys.append(storage_key)
        return real_save_file(storage_key, file_obj, max_size_bytes, chunk_size)

    # Mock create_resume to simulate a database failure after file is persisted
    with (
        patch.object(LocalStorageService, "save_file", side_effect=tracking_save_file),
        patch.object(
            ResumeRepository,
            "create_resume",
            side_effect=RuntimeError("Simulated DB connection failure"),
        ),
        pytest.raises(RuntimeError, match="Simulated DB connection failure"),
    ):
        client.post(
            "/api/v1/resumes",
            headers=headers,
            files={
                "file": (
                    "failed_resume.pdf",
                    io.BytesIO(b"%PDF-1.4 will fail db"),
                    "application/pdf",
                )
            },
        )

    # Verify that the file was deleted from disk and no orphan remains
    assert len(persisted_keys) == 1
    storage_key = persisted_keys[0]
    assert storage.file_exists(storage_key) is False

    # Verify that no orphaned Resume record was created
    orphans = db.query(Resume).filter(Resume.storage_key == storage_key).all()
    assert len(orphans) == 0
