from abc import ABC, abstractmethod
from pathlib import Path
from typing import BinaryIO

from app.config.settings import settings


class StorageError(Exception):
    """Base exception for file storage operations."""

    pass


class StoragePathTraversalError(StorageError):
    """Raised when a storage key attempts to traverse outside the storage root."""

    pass


class StorageLimitExceededError(StorageError):
    """Raised when an uploaded file stream exceeds the maximum permitted byte size."""

    pass


class StorageEmptyFileError(StorageError):
    """Raised when an uploaded file is empty (0 bytes)."""

    pass


class BaseStorageService(ABC):
    """Abstract base class defining file storage operations."""

    @abstractmethod
    def save_file(
        self,
        storage_key: str,
        file_obj: BinaryIO,
        max_size_bytes: int | None = None,
        chunk_size: int = 64 * 1024,
    ) -> int:
        """
        Save a binary file stream under the given storage_key.
        Enforces max_size_bytes during chunked stream reading.
        Returns the total number of bytes written.
        """
        pass

    @abstractmethod
    def delete_file(self, storage_key: str) -> bool:
        """
        Delete a file associated with storage_key.
        Returns True if deleted, False if file did not exist.
        """
        pass

    @abstractmethod
    def file_exists(self, storage_key: str) -> bool:
        """Check if file associated with storage_key exists."""
        pass

    @abstractmethod
    def resolve_path(self, storage_key: str) -> Path:
        """
        Resolve storage_key to a safe internal Path.
        Guarantees that the resolved path cannot escape the storage root.
        """
        pass


class LocalStorageService(BaseStorageService):
    """Local filesystem implementation of BaseStorageService."""

    def __init__(self, root_dir: str | Path | None = None):
        self.root_path = Path(root_dir or settings.STORAGE_LOCAL_ROOT).resolve()

    def resolve_path(self, storage_key: str) -> Path:
        # Strip leading slashes to prevent absolute path escapes
        clean_key = storage_key.lstrip("/\\")
        target_path = (self.root_path / clean_key).resolve()

        # Path traversal verification
        try:
            target_path.relative_to(self.root_path)
        except ValueError:
            raise StoragePathTraversalError(
                f"Storage key '{storage_key}' attempts path traversal outside storage root."
            ) from None
        return target_path

    def save_file(
        self,
        storage_key: str,
        file_obj: BinaryIO,
        max_size_bytes: int | None = None,
        chunk_size: int = 64 * 1024,
    ) -> int:
        target_path = self.resolve_path(storage_key)
        target_path.parent.mkdir(parents=True, exist_ok=True)

        bytes_written = 0
        try:
            with open(target_path, "wb") as dest:
                while True:
                    chunk = file_obj.read(chunk_size)
                    if not chunk:
                        break
                    bytes_written += len(chunk)
                    if max_size_bytes is not None and bytes_written > max_size_bytes:
                        dest.close()
                        self._safe_unlink(target_path)
                        raise StorageLimitExceededError(
                            f"File size exceeds maximum allowed limit of {max_size_bytes} bytes."
                        )
                    dest.write(chunk)
        except Exception:
            self._safe_unlink(target_path)
            raise

        if bytes_written == 0:
            self._safe_unlink(target_path)
            raise StorageEmptyFileError("Uploaded file is empty.")

        return bytes_written

    def delete_file(self, storage_key: str) -> bool:
        try:
            target_path = self.resolve_path(storage_key)
            if target_path.is_file():
                target_path.unlink()
                return True
            return False
        except Exception:
            return False

    def file_exists(self, storage_key: str) -> bool:
        try:
            target_path = self.resolve_path(storage_key)
            return target_path.is_file()
        except Exception:
            return False

    def _safe_unlink(self, path: Path) -> None:
        try:
            if path.exists():
                path.unlink()
        except OSError:
            pass
