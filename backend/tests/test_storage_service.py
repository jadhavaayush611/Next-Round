import io
from pathlib import Path

import pytest

from app.services.storage import (
    LocalStorageService,
    StorageEmptyFileError,
    StorageLimitExceededError,
    StoragePathTraversalError,
)


def test_storage_save_and_retrieve_file(tmp_path: Path) -> None:
    storage = LocalStorageService(root_dir=tmp_path)
    storage_key = "users/123/resumes/resume.pdf"
    content = b"%PDF-1.4 sample content bytes"
    file_obj = io.BytesIO(content)

    bytes_written = storage.save_file(storage_key, file_obj)
    assert bytes_written == len(content)
    assert storage.file_exists(storage_key) is True

    resolved_path = storage.resolve_path(storage_key)
    assert resolved_path.exists()
    assert resolved_path.read_bytes() == content


def test_storage_delete_file(tmp_path: Path) -> None:
    storage = LocalStorageService(root_dir=tmp_path)
    storage_key = "users/123/resumes/to_delete.pdf"
    content = b"%PDF-1.4 to delete"

    storage.save_file(storage_key, io.BytesIO(content))
    assert storage.file_exists(storage_key) is True

    deleted = storage.delete_file(storage_key)
    assert deleted is True
    assert storage.file_exists(storage_key) is False

    # Deleting non-existent file returns False gracefully
    assert storage.delete_file(storage_key) is False


def test_storage_path_traversal_prevention(tmp_path: Path) -> None:
    storage = LocalStorageService(root_dir=tmp_path)

    traversal_keys = [
        "../secret.txt",
        "../../etc/passwd",
        "users/../../escaped.pdf",
        "..\\..\\windows\\system32\\calc.exe",
    ]

    for key in traversal_keys:
        with pytest.raises(StoragePathTraversalError):
            storage.resolve_path(key)


def test_storage_rejects_empty_file(tmp_path: Path) -> None:
    storage = LocalStorageService(root_dir=tmp_path)
    storage_key = "users/123/resumes/empty.pdf"

    with pytest.raises(StorageEmptyFileError):
        storage.save_file(storage_key, io.BytesIO(b""))

    assert storage.file_exists(storage_key) is False


def test_storage_enforces_max_size_limit(tmp_path: Path) -> None:
    storage = LocalStorageService(root_dir=tmp_path)
    storage_key = "users/123/resumes/oversized.pdf"
    large_content = b"%PDF-" + b"A" * 1024  # 1029 bytes

    # Limit to 500 bytes -> must raise and remove partial file
    with pytest.raises(StorageLimitExceededError):
        storage.save_file(
            storage_key,
            io.BytesIO(large_content),
            max_size_bytes=500,
            chunk_size=100,
        )

    assert storage.file_exists(storage_key) is False
